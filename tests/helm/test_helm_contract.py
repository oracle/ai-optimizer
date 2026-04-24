"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract tests for the Helm chart: enforce explicit operator configuration of
the client cookie-signing secret, mirroring the existing apiKey pattern.
"""
# spell-checker: disable

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART_DIR = Path(__file__).resolve().parent.parent.parent / "helm"

helm_bin = shutil.which("helm")
pytestmark = pytest.mark.skipif(
    helm_bin is None, reason="helm binary not available on PATH"
)


def _render(*extra_sets: str) -> subprocess.CompletedProcess:
    """Run helm template with a minimal baseline plus extra --set flags."""
    cmd = [
        "helm",
        "template",
        "test",
        str(CHART_DIR),
        "--set",
        "global.api.apiKey=dummy-api-key",
    ]
    for s in extra_sets:
        cmd.extend(["--set", s])
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _render_raw(*extra_args: str) -> subprocess.CompletedProcess:
    """Run helm template with arbitrary CLI args (supports --set-string for whitespace values)."""
    cmd = [
        "helm",
        "template",
        "test",
        str(CHART_DIR),
        "--set",
        "global.api.apiKey=dummy-api-key",
        *extra_args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _docs(stdout: str) -> list[dict]:
    """Parse helm output into a list of YAML documents (dicts only)."""
    return [d for d in yaml.safe_load_all(stdout) if isinstance(d, dict)]


def _client_deployment(docs: list[dict]) -> dict:
    """Return the client Deployment document."""
    for d in docs:
        if (
            d.get("kind") == "Deployment"
            and d.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "client"
        ):
            return d
    raise AssertionError("client Deployment not found in rendered output")


def _cookie_env(deployment: dict) -> dict:
    """Return the AIO_CLIENT_COOKIE_SECRET env var dict from the client container."""
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    return next(e for e in env if e["name"] == "AIO_CLIENT_COOKIE_SECRET")


def _chart_rendered_cookie_secrets(docs: list[dict]) -> list[dict]:
    """Return Secrets that this chart rendered (identified by the cookieSecret data key)."""
    return [
        d for d in docs
        if d.get("kind") == "Secret" and d.get("data", {}).get("cookieSecret") is not None
    ]


class TestClientCookieSecretContract:
    """client.cookieSecret must be operator-supplied — no silent fallback."""

    def test_fails_when_neither_provided(self):
        """helm template must fail if neither client.cookieSecret nor client.cookieSecretName is set."""
        result = _render()
        assert result.returncode != 0, (
            "helm template should fail when no cookie secret is configured; "
            f"got rc={result.returncode}\nstdout={result.stdout[:500]}"
        )
        assert "cookieSecret" in result.stderr or "cookieSecretName" in result.stderr, (
            f"expected failure message to mention cookieSecret/cookieSecretName; got: {result.stderr[:500]}"
        )

    def test_succeeds_with_inline_value(self):
        """helm template must succeed when client.cookieSecret is set inline."""
        result = _render("client.cookieSecret=inline-cookie-value")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        assert "aW5saW5lLWNvb2tpZS12YWx1ZQ==" in result.stdout, (
            "rendered Secret should contain b64('inline-cookie-value')"
        )

    def test_succeeds_with_external_secret_name(self):
        """helm template must succeed when client.cookieSecretName references an external Secret."""
        result = _render("client.cookieSecretName=my-external-cookie-secret")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        # No Secret should be rendered for the client cookie — operator owns it
        assert "-client-cookie\n" not in result.stdout, (
            "should not render our own Secret when an external Secret is referenced"
        )
        # Deployment env entry must reference the external Secret
        assert "my-external-cookie-secret" in result.stdout

    def test_fails_when_both_provided(self):
        """helm template must fail if both inline value and external name are set."""
        result = _render(
            "client.cookieSecret=inline-val",
            "client.cookieSecretName=external-name",
        )
        assert result.returncode != 0, (
            "helm template should fail when both cookieSecret and cookieSecretName are set"
        )

    def test_rollout_checksum_present(self):
        """Deployment pod template must carry a checksum annotation keyed to the Secret."""
        result = _render("client.cookieSecret=inline-cookie-value")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        assert "checksum/client-cookie-secret:" in result.stdout, (
            "deployment.yaml should include checksum/client-cookie-secret annotation "
            "so pods roll when the Secret is rotated"
        )

    def test_rollout_checksum_changes_on_rotation(self):
        """Rotating client.cookieSecret must produce a different checksum annotation."""
        r1 = _render("client.cookieSecret=value-one")
        r2 = _render("client.cookieSecret=value-two")
        assert r1.returncode == 0 and r2.returncode == 0
        c1 = _extract_checksum(r1.stdout)
        c2 = _extract_checksum(r2.stdout)
        assert c1 and c2, "checksum annotation missing from one of the renders"
        assert c1 != c2, "rotating client.cookieSecret should change the checksum"

    def test_external_path_helper_uses_lookup(self):
        """White-box regression gate for P2.

        The only way a chart can detect content changes in an externally-owned
        Secret at helm upgrade time is the `lookup` built-in. If this string
        disappears from _helpers.tpl, rotating an external Secret in place will
        silently stop triggering rollouts and the fix is regressed.
        """
        helpers_tpl = (CHART_DIR / "templates" / "_helpers.tpl").read_text()
        assert 'lookup "v1" "Secret"' in helpers_tpl, (
            "_helpers.tpl must use `lookup \"v1\" \"Secret\"` so the "
            "cookieSecret checksum reflects the live content of an external "
            "Secret; see reviewer finding P2"
        )

    def test_whitespace_only_cookie_secret_routes_to_external_path(self):
        """P2: whitespace cookieSecret + external cookieSecretName must take external path.

        The validator already trims both values, so this combination passes the
        "exactly one" check. But the render paths used raw values — meaning the
        chart would render its OWN Secret named after the external name,
        silently clobbering the operator-owned Secret. The fix is to trim
        consistently across every site that branches on these values.
        """
        result = _render_raw(
            "--set-string", "client.cookieSecret=   ",
            "--set", "client.cookieSecretName=operator-owned-cookie-secret",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        chart_cookie_secrets = _chart_rendered_cookie_secrets(docs)
        assert chart_cookie_secrets == [], (
            "whitespace-only cookieSecret must route to external path; the "
            "chart must NOT render its own cookie Secret, else it can clobber "
            f"the operator-owned Secret. got: {[s['metadata']['name'] for s in chart_cookie_secrets]}"
        )
        deployment = _client_deployment(docs)
        assert _cookie_env(deployment)["valueFrom"]["secretKeyRef"]["name"] == "operator-owned-cookie-secret"

    def test_whitespace_only_cookie_secret_name_falls_back_to_default(self):
        """P2: whitespace cookieSecretName + inline value must fall back to default name.

        The cookieSecretName resolver used `default` after `Values...`, but
        `default` only fires on Helm's false values (""/nil) — whitespace is
        truthy, so it passed through verbatim and produced `metadata.name: `.
        The fix is to trim before the default fallback.
        """
        result = _render_raw(
            "--set", "client.cookieSecret=valid-inline-value",
            "--set-string", "client.cookieSecretName=   ",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        chart_cookie_secrets = _chart_rendered_cookie_secrets(docs)
        assert len(chart_cookie_secrets) == 1, (
            f"expected exactly 1 chart-rendered cookie Secret, got {len(chart_cookie_secrets)}"
        )
        name = chart_cookie_secrets[0]["metadata"]["name"]
        assert name and name.strip() == name, (
            f"Secret metadata.name must not be blank/whitespace; got {name!r}"
        )
        assert name.endswith("-client-cookie"), (
            f"whitespace-only cookieSecretName must fall back to <release>-client-cookie; got {name!r}"
        )
        deployment = _client_deployment(docs)
        assert _cookie_env(deployment)["valueFrom"]["secretKeyRef"]["name"] == name

    def test_whitespace_only_both_fails_validation(self):
        """P2 invariant: both-whitespace must still fail validation (not slip through)."""
        result = _render_raw(
            "--set-string", "client.cookieSecret=   ",
            "--set-string", "client.cookieSecretName=   ",
        )
        assert result.returncode != 0, (
            "both whitespace-only values must fail the required validator, "
            "just like both empty would"
        )

    def test_external_secret_checksum_varies_by_name(self):
        """Black-box check: two different cookieSecretName values must produce
        different checksums.

        Under the broken implementation the checksum was a constant hash of an
        empty secret.yaml render regardless of which external Secret was named
        — meaning the fix is required for this assertion to pass. Under the
        fixed implementation, even when `lookup` returns empty (helm template
        has no cluster), the render incorporates the Secret name into a
        deterministic sentinel so misconfigurations are still distinguishable.
        """
        r1 = _render("client.cookieSecretName=external-secret-a")
        r2 = _render("client.cookieSecretName=external-secret-b")
        assert r1.returncode == 0 and r2.returncode == 0
        c1 = _extract_checksum(r1.stdout)
        c2 = _extract_checksum(r2.stdout)
        assert c1 and c2, "checksum missing on one of the renders"
        assert c1 != c2, (
            "checksums for different external Secret names must differ; a "
            "constant-across-renders hash means the helper ignores the "
            "referenced Secret and will not detect rotations"
        )


def _extract_checksum(rendered: str) -> str:
    """Return the value of the checksum/client-cookie-secret annotation, or empty string."""
    for line in rendered.splitlines():
        stripped = line.strip()
        if stripped.startswith("checksum/client-cookie-secret:"):
            return stripped.split(":", 1)[1].strip().strip('"')
    return ""
