"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract tests for the Helm chart: enforce explicit operator configuration of
the client cookie-signing secret, mirroring the existing apiKey pattern.
"""
# spell-checker: disable

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART_DIR = Path(__file__).resolve().parent.parent.parent / "helm"

helm_bin = shutil.which("helm")
pytestmark = pytest.mark.skipif(helm_bin is None, reason="helm binary not available on PATH")


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


def _render_with_notes(*extra_sets: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Render manifests and NOTES.txt without contacting a Kubernetes cluster."""
    cmd = [
        "helm",
        "install",
        "--dry-run=client",
        "--server-side=false",
        "test",
        str(CHART_DIR),
        "--namespace",
        "test-ns",
        "--set",
        "global.api.apiKey=dummy-api-key",
    ]
    for s in extra_sets:
        cmd.extend(["--set", s])
    return subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)


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
    return [d for d in docs if d.get("kind") == "Secret" and d.get("data", {}).get("cookieSecret") is not None]


def _set_args(*sets: str) -> list[str]:
    """Expand bare ``key=value`` strings into ``--set key=value`` argv pairs."""
    return [arg for s in sets for arg in ("--set", s)]


def _extract_checksum(rendered: str) -> str:
    """Return the value of the checksum/client-cookie-secret annotation, or empty string."""
    for line in rendered.splitlines():
        stripped = line.strip()
        if stripped.startswith("checksum/client-cookie-secret:"):
            return stripped.split(":", 1)[1].strip().strip('"')
    return ""


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
        assert result.returncode != 0, "helm template should fail when both cookieSecret and cookieSecretName are set"

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
            '_helpers.tpl must use `lookup "v1" "Secret"` so the '
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
            "--set-string",
            "client.cookieSecret=   ",
            "--set",
            "client.cookieSecretName=operator-owned-cookie-secret",
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
            "--set",
            "client.cookieSecret=valid-inline-value",
            "--set-string",
            "client.cookieSecretName=   ",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        chart_cookie_secrets = _chart_rendered_cookie_secrets(docs)
        assert len(chart_cookie_secrets) == 1, (
            f"expected exactly 1 chart-rendered cookie Secret, got {len(chart_cookie_secrets)}"
        )
        name = chart_cookie_secrets[0]["metadata"]["name"]
        assert name and name.strip() == name, f"Secret metadata.name must not be blank/whitespace; got {name!r}"
        assert name.endswith("-client-cookie"), (
            f"whitespace-only cookieSecretName must fall back to <release>-client-cookie; got {name!r}"
        )
        deployment = _client_deployment(docs)
        assert _cookie_env(deployment)["valueFrom"]["secretKeyRef"]["name"] == name

    def test_whitespace_only_both_fails_validation(self):
        """P2 invariant: both-whitespace must still fail validation (not slip through)."""
        result = _render_raw(
            "--set-string",
            "client.cookieSecret=   ",
            "--set-string",
            "client.cookieSecretName=   ",
        )
        assert result.returncode != 0, (
            "both whitespace-only values must fail the required validator, just like both empty would"
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


class TestClientEnvSecretContract:
    """Chart-derived server URL/port must reach the client pod regardless of
    how the client env Secret is sourced.

    The env Secret only carries operator overrides + client SSL settings; the
    chart-managed Secret is skipped entirely when client.envSecret.secretName
    points at a pre-existing operator-owned Secret. AIO_SERVER_URL and
    AIO_SERVER_PORT are derived from the in-cluster Service and have no
    sensible operator override, so they must travel via direct pod env —
    otherwise the client falls back to http://localhost:8000 (the Pydantic
    defaults in src/client/app/core/settings.py) and cannot reach the
    in-cluster server.
    """

    def test_server_url_and_port_present_with_external_env_secret(self):
        """When client.envSecret.secretName references an external Secret, the
        chart skips its own env-secret render. AIO_SERVER_URL/PORT must still
        be wired into the pod via direct env, not the mounted .env file."""
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "client.envSecret.secretName=operator-owned-client-env",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _client_deployment(_docs(result.stdout))
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        url_entry = next((e for e in env if e["name"] == "AIO_SERVER_URL"), None)
        port_entry = next((e for e in env if e["name"] == "AIO_SERVER_PORT"), None)
        assert url_entry is not None, (
            "AIO_SERVER_URL must be set as direct pod env so external-Secret "
            "operators reach the in-cluster server; otherwise the client "
            "Pydantic default (http://localhost) wins"
        )
        assert port_entry is not None, "AIO_SERVER_PORT must be set as direct pod env for the same reason"
        assert url_entry["value"].startswith("http://test-ai-optimizer-server-http"), (
            f"AIO_SERVER_URL should resolve to the in-cluster server Service; got {url_entry['value']!r}"
        )
        assert port_entry["value"] == "8000", f"AIO_SERVER_PORT should default to 8000; got {port_entry['value']!r}"


def _server_deployment(docs: list[dict]) -> dict:
    """Return the server Deployment document."""
    for d in docs:
        if (
            d.get("kind") == "Deployment"
            and d.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "server"
        ):
            return d
    raise AssertionError("server Deployment not found in rendered output")


def _server_env(deployment: dict, name: str) -> dict | None:
    """Return the named env var dict from the server container, or None if absent."""
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    return next((e for e in env if e["name"] == name), None)


def _client_env(deployment: dict, name: str) -> dict | None:
    """Return the named env var dict from the client container, or None if absent."""
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    return next((e for e in env if e["name"] == name), None)


def _server_env_content(docs: list[dict]) -> str:
    """Return the chart-managed server dotenv content."""
    for doc in docs:
        if (
            doc.get("kind") == "Secret"
            and doc.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "server"
            and doc.get("stringData")
        ):
            return next(iter(doc["stringData"].values()))
    raise AssertionError("chart-managed server environment Secret not found")


class TestApplicationEnvironmentNames:
    """Chart-generated application settings use the AIO_ namespace."""

    _COOKIE = "client.cookieSecret=cccccccccccccccccccccccccccccccc"

    def test_database_and_model_secret_bindings_use_aio_names(self):
        result = _render(
            self._COOKIE,
            "server.database.type=OTHER",
            "server.database.other.dsn=mydbhost.example.com:1521/MYSERVICE",
            "server.database.authn.secretName=database-credentials",
            "server.models.openai.secretName=openai-credentials",
            "server.models.perplexity.secretName=perplexity-credentials",
            "server.models.cohere.secretName=cohere-credentials",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        env_names = {entry["name"] for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}

        assert {
            "AIO_DB_USERNAME",
            "AIO_DB_PASSWORD",
            "AIO_DB_DSN",
            "AIO_OPENAI_API_KEY",
            "AIO_PPLX_API_KEY",
            "AIO_COHERE_API_KEY",
        } <= env_names
        assert {
            "DB_USERNAME",
            "DB_PASSWORD",
            "DB_DSN",
            "OPENAI_API_KEY",
            "PPLX_API_KEY",
            "COHERE_API_KEY",
        }.isdisjoint(env_names)

    def test_adb_wallet_binding_uses_aio_name(self):
        result = _render(
            self._COOKIE,
            "server.database.type=ADB-S",
            "server.database.oci.ocid=ocid1.autonomousdatabase.oc1..test",
            "server.database.adb.serviceName=mydb_low",
            "server.database.adb.skipCrdCheck=true",
            "server.database.username=admin",
            "server.database.password=wallet-password",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        env_names = {entry["name"] for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}

        assert "AIO_DB_WALLET_PASSWORD" in env_names
        assert "DB_WALLET_PASSWORD" not in env_names

    def test_chart_managed_env_file_uses_aio_names(self):
        result = _render(
            self._COOKIE,
            "server.ociConfig.oke=true",
            "server.ociConfig.region=us-ashburn-1",
            "ollama.enabled=true",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        content = _server_env_content(_docs(result.stdout))

        assert "AIO_OCI_CLI_REGION=us-ashburn-1" in content
        assert "AIO_OCI_CLI_AUTH=oke_workload_identity" in content
        assert "AIO_ON_PREM_OLLAMA_URL=" in content
        assert re.search(r"(?m)^(OCI_CLI_REGION|OCI_CLI_AUTH|ON_PREM_OLLAMA_URL)=", content) is None

    def test_database_provisioning_uses_aio_names(self):
        result = _render(
            self._COOKIE,
            "server.database.type=SIDB-FREE",
            "server.database.image.repository=database/free",
            "server.database.image.tag=1.0.0",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"

        assert all(name in result.stdout for name in ("AIO_DB_USERNAME", "AIO_DB_PASSWORD", "AIO_DB_DSN"))
        assert re.search(r"(?<!AIO_)\bDB_(USERNAME|PASSWORD|DSN)\b", result.stdout) is None


def _docs_for_required_defaults() -> list[dict]:
    result = _render("client.cookieSecret=cccccccccccccccccccccccccccccccc")
    assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
    return _docs(result.stdout)


class TestHelmBestPracticeContracts:
    """Contracts for Helm chart best-practice cleanup."""

    def test_default_render_has_no_database_owned_resources(self):
        docs = _docs_for_required_defaults()
        db_docs = [
            d for d in docs if d.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "database"
        ]
        assert db_docs == [], (
            "server.database.type defaults to empty, so the chart must not "
            f"""
            render database resources by default. got:
            {[(d.get("kind"), d.get("metadata", {}).get("name")) for d in db_docs]}
            """
        )
        server = _server_deployment(docs)
        env_names = {e["name"] for e in server["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert {"DB_USERNAME", "DB_PASSWORD", "DB_DSN"}.isdisjoint(env_names)

    def test_default_render_has_no_metadata_namespace(self):
        docs = _docs_for_required_defaults()
        namespaced = [
            (d.get("kind"), d.get("metadata", {}).get("name")) for d in docs if d.get("metadata", {}).get("namespace")
        ]
        assert namespaced == [], (
            "release-scoped resources should inherit the Helm release namespace "
            f"instead of setting metadata.namespace: {namespaced}"
        )

    def test_default_render_has_no_comment_only_documents(self):
        result = _render("client.cookieSecret=cccccccccccccccccccccccccccccccc")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        chunks = [chunk for chunk in result.stdout.split("---\n") if chunk.strip()]
        empty_sources = [
            chunk.splitlines()[0] for chunk in chunks if "# Source:" in chunk and "apiVersion:" not in chunk
        ]
        assert empty_sources == []

    def test_rendered_default_images_do_not_use_floating_tags(self):
        docs = _docs_for_required_defaults()
        images: list[str] = []
        for d in docs:
            pod_spec = d.get("spec", {}).get("template", {}).get("spec", {})
            for c in pod_spec.get("containers", []):
                images.append(c.get("image", ""))
        assert images
        assert all(not image.endswith(":latest") for image in images), images
        assert all(not image.endswith(":head") for image in images), images
        assert all(not image.endswith(":canary") for image in images), images

    def test_old_breaking_value_keys_are_rejected(self):
        cases = [
            "server.oci_config.region=us-ashburn-1",
            "server.database.authN.secretName=db-authn",
            "server.database.privAuthN.secretName=db-priv-authn",
            "server.models.openAI.secretName=openai-secret",
        ]
        for set_arg in cases:
            result = _render(
                "client.cookieSecret=cccccccccccccccccccccccccccccccc",
                set_arg,
            )
            assert result.returncode != 0, f"{set_arg} should be rejected"

    def test_other_database_mode_does_not_render_db_deployment_or_init_job(self):
        """BYO-user variant: operator supplies authn.secretName, so the chart
        must render NO db-labelled resources — explicit secretName means the
        Secret is operator-owned, and rendering one with chart-generated
        random credentials at the same name would overwrite the real
        credentials under GitOps apply."""
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "server.database.type=OTHER",
            "server.database.other.dsn=mydbhost.example.com:1521/MYSERVICE",
            "server.database.authn.secretName=byo-db-authn",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        db_owned = [
            (d.get("kind"), d.get("metadata", {}).get("name"))
            for d in docs
            if d.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "database"
        ]
        assert db_owned == [], (
            f"OTHER + explicit authn.secretName must render no db-labelled resources "
            f"(operator owns the Secret); got {db_owned}"
        )

    def test_explicit_authn_secret_name_skips_chart_rendering_offline(self):
        """Regression guard for the GitOps/Argo CD/Flux offline render path:
        an explicit authn.secretName must never produce a chart-managed
        Secret carrying that same name with random credentials, regardless
        of whether `lookup` returns a hit."""
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "server.database.type=SIDB-FREE",
            "server.database.image.repository=foo",
            "server.database.image.tag=1.0.0",
            "server.database.authn.secretName=byo-shared-auth",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        for d in _docs(result.stdout):
            if d.get("kind") == "Secret" and d.get("metadata", {}).get("name") == "byo-shared-auth":
                raise AssertionError(
                    "chart must not render a Secret named after an operator-pinned "
                    f"authn.secretName; got: {d.get('stringData') or d.get('data')}"
                )

    def test_explicit_priv_authn_secret_name_skips_chart_rendering_offline(self):
        """Same offline-render contract for the privileged Secret: explicit
        privAuthn.secretName must not produce a chart-managed privileged
        Secret with random SYSTEM/ADMIN credentials at that name."""
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "server.database.type=SIDB-FREE",
            "server.database.image.repository=foo",
            "server.database.image.tag=1.0.0",
            "server.database.privAuthn.secretName=byo-shared-priv",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        for d in _docs(result.stdout):
            if d.get("kind") == "Secret" and d.get("metadata", {}).get("name") == "byo-shared-priv":
                raise AssertionError(
                    "chart must not render a Secret named after an operator-pinned "
                    f"privAuthn.secretName; got: {d.get('stringData') or d.get('data')}"
                )

    def test_other_database_mode_without_credentials_is_rejected(self):
        """OTHER + no authn.secretName + no privAuthn.secretName must fail
        loudly, otherwise the chart generates an unusable random password
        against a user that doesn't exist on the external database."""
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "server.database.type=OTHER",
            "server.database.other.dsn=mydbhost.example.com:1521/MYSERVICE",
        )
        assert result.returncode != 0, (
            "OTHER without authn.secretName or privAuthn.secretName must fail; "
            f"rendered successfully with stdout={result.stdout[:300]}"
        )
        assert "authn.secretName" in result.stderr and "privAuthn.secretName" in result.stderr, (
            f"failure message must name both escape hatches; got: {result.stderr[:500]}"
        )

    def test_other_database_mode_with_priv_credentials_runs_init_job(self):
        """Operator opts into chart-managed user provisioning by supplying
        privAuthn.secretName — the init Job and its ConfigMap must render
        so the AI_OPTIMIZER user is created on the external database with
        the same random password the chart-generated auth Secret carries."""
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "server.database.type=OTHER",
            "server.database.other.dsn=mydbhost.example.com:1521/MYSERVICE",
            "server.database.privAuthn.secretName=byo-priv-creds",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        kinds_by_name = {d.get("metadata", {}).get("name", ""): d.get("kind") for d in docs}
        run_sql_jobs = [n for n, k in kinds_by_name.items() if k == "Job" and "run-sql" in n]
        init_cms = [n for n, k in kinds_by_name.items() if k == "ConfigMap" and n.endswith("-db-init")]
        assert run_sql_jobs, (
            f"OTHER + privAuthn.secretName must render the init Job; got names={list(kinds_by_name.keys())}"
        )
        assert init_cms, (
            f"OTHER + privAuthn.secretName must render the init ConfigMap; got names={list(kinds_by_name.keys())}"
        )

    def test_container_database_requires_pinned_image_tag(self):
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "server.database.type=SIDB-FREE",
            "server.database.image.repository=foo",
        )
        assert result.returncode != 0
        assert "server/database/image/tag" in result.stderr or "image tag" in result.stderr


class TestNotesUninstallDeletesOnlyChartManagedSecrets:
    """NOTES.txt's `kubectl delete secret` hints must target only the
    chart-managed Secrets — an explicit authn.secretName / privAuthn.secretName
    is operator-owned (possibly shared across releases), and a copy/pasted
    delete command would destroy real credentials. Mirrors the offline-render
    contract enforced in auth-secret.yaml / priv-secret.yaml.
    """

    _COMMON = (
        "global.api.apiKey=dummy-api-key",
        "client.cookieSecret=cccccccccccccccccccccccccccccccc",
    )

    def _notes(self, *extra_sets: str) -> str:
        result = _render_with_notes(*self._COMMON, *extra_sets)
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        return result.stdout

    def test_byo_both_emits_no_delete_commands(self):
        """`kubectl get secret <byo-name>` for inspection is fine (operator
        already knows the name). The destructive case is `kubectl delete
        secret <byo-name>`; that must never appear."""
        notes = self._notes(
            "server.database.type=ADB-S",
            "server.database.oci.ocid=ocid1.adb.test",
            "server.database.adb.skipCrdCheck=true",
            "server.database.adb.serviceName=mydb_high",
            "server.database.authn.secretName=shared-prod-db",
            "server.database.privAuthn.secretName=shared-prod-priv",
        )
        delete_lines = [ln for ln in notes.splitlines() if "kubectl delete secret" in ln]
        assert delete_lines == [], (
            "NOTES must not suggest deleting any Secret when both authn and "
            f"privAuthN are operator-owned; got: {delete_lines}"
        )

    def test_byo_authn_only_emits_only_priv_delete(self):
        notes = self._notes(
            "server.database.type=SIDB-FREE",
            "server.database.image.repository=foo",
            "server.database.image.tag=1.0.0",
            "server.database.authn.secretName=byo-auth",
        )
        delete_lines = [ln for ln in notes.splitlines() if "kubectl delete secret" in ln]
        assert len(delete_lines) == 1, (
            f"expected exactly one chart-managed delete hint (priv only); got: {delete_lines}"
        )
        assert "byo-auth" not in delete_lines[0], "operator-owned authn name leaked into delete hint"
        assert "-db-priv-authn" in delete_lines[0], (
            f"expected the chart-managed priv Secret suffix; got: {delete_lines[0]}"
        )

    def test_byo_priv_only_emits_only_auth_delete(self):
        notes = self._notes(
            "server.database.type=SIDB-FREE",
            "server.database.image.repository=foo",
            "server.database.image.tag=1.0.0",
            "server.database.privAuthn.secretName=byo-priv",
        )
        delete_lines = [ln for ln in notes.splitlines() if "kubectl delete secret" in ln]
        assert len(delete_lines) == 1, (
            f"expected exactly one chart-managed delete hint (auth only); got: {delete_lines}"
        )
        assert "byo-priv" not in delete_lines[0], "operator-owned priv name leaked into delete hint"
        assert "-db-authn" in delete_lines[0], f"expected the chart-managed authn Secret suffix; got: {delete_lines[0]}"

    def test_defaults_emit_both_chart_managed_deletes(self):
        notes = self._notes(
            "server.database.type=SIDB-FREE",
            "server.database.image.repository=foo",
            "server.database.image.tag=1.0.0",
        )
        delete_lines = [ln for ln in notes.splitlines() if "kubectl delete secret" in ln]
        assert len(delete_lines) == 2, f"expected both chart-managed deletes; got: {delete_lines}"
        # Sanity: both should be the chart-managed default-name pattern.
        assert any("db-authn" in ln for ln in delete_lines), delete_lines
        assert any("db-priv-authn" in ln for ln in delete_lines), delete_lines

    def test_other_mode_chart_managed_auth_emits_only_auth_delete(self):
        """OTHER mode with chart-provisioned-user path (privAuthn.secretName
        set, no authn.secretName) — auth Secret is chart-managed, priv-secret
        is not rendered by the chart at all for OTHER mode. Exactly one
        delete hint, naming the chart-managed auth Secret."""
        notes = self._notes(
            "server.database.type=OTHER",
            "server.database.other.dsn=mydbhost.example.com:1521/MYSERVICE",
            "server.database.privAuthn.secretName=byo-priv",
        )
        delete_lines = [ln for ln in notes.splitlines() if "kubectl delete secret" in ln]
        assert len(delete_lines) == 1, f"expected exactly one auth delete hint; got: {delete_lines}"
        assert "byo-priv" not in delete_lines[0], "operator-owned priv name leaked into NOTES"
        assert "-db-authn" in delete_lines[0], delete_lines

    def test_no_database_emits_no_delete_commands(self):
        notes = self._notes()
        assert "kubectl delete secret" not in notes, (
            "with no database configured, NOTES must not suggest deleting db Secrets"
        )


_SIGNOZ_OTEL_BASE = (
    "signoz.enabled=true",
    "server.otel.enabled=true",
    "server.otel.insecure=true",
    "client.cookieSecret=cccccccccccccccccccccccccccccccc",
    "server.database.type=SIDB-FREE",
    "server.database.image.repository=foo",
    "server.database.image.tag=1.0.0",
)


class TestSigNozAutoEndpointHttpProtocol:
    """Per-signal endpoint defaults must include the OTLP HTTP signal paths.

    The OTel spec requires the SDK to AUTO-APPEND `/v1/{traces,logs,metrics}`
    only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; per-signal env vars
    (`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` etc.) are used as-is. The chart's
    auto-default emits per-signal env vars, so it must include the path
    component itself or HTTP exports POST to `/` and the collector 404s.
    gRPC endpoints don't carry the path component and must NOT have it.
    """

    def test_traces_http_endpoint_includes_v1_traces(self):
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.tracesProtocol=http/protobuf",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        ep = _server_env(deployment, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        assert ep is not None, "expected OTEL_EXPORTER_OTLP_TRACES_ENDPOINT to be set"
        assert ep["value"].endswith("/v1/traces"), (
            f"HTTP/protobuf per-signal traces endpoint must include /v1/traces; got {ep['value']!r}"
        )

    def test_logs_http_endpoint_includes_v1_logs(self):
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.logsEnabled=true",
            "server.otel.logsProtocol=http/protobuf",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        ep = _server_env(deployment, "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
        assert ep is not None, "expected OTEL_EXPORTER_OTLP_LOGS_ENDPOINT to be set"
        assert ep["value"].endswith("/v1/logs"), (
            f"HTTP/protobuf per-signal logs endpoint must include /v1/logs; got {ep['value']!r}"
        )

    def test_grpc_endpoints_do_not_include_signal_path(self):
        """gRPC OTLP endpoints address services by name, not URL path; the SDK
        rejects /v1/... appended to a gRPC URL. Confirm the helper strips."""
        result = _render(*_SIGNOZ_OTEL_BASE, "server.otel.logsEnabled=true")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        for var in ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"):
            ep = _server_env(deployment, var)
            assert ep is not None, f"expected {var} to be set"
            assert "/v1/" not in ep["value"], f"gRPC endpoint {var} must not include a signal path; got {ep['value']!r}"

    def test_grpc_port_override_respected(self):
        """If the operator overrides signoz.otelCollector.ports.otlp.servicePort,
        the auto-wired gRPC endpoint must use that port — not hardcoded 4317."""
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.otelCollector.ports.otlp.servicePort=14317",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        ep = _server_env(deployment, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        assert ep is not None
        assert ep["value"].endswith(":14317"), (
            f"servicePort override must propagate to the auto endpoint; got {ep['value']!r}"
        )

    def test_http_port_override_respected(self):
        """Same for the otlp-http servicePort — must follow the override and
        keep the /v1/<signal> path."""
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.tracesProtocol=http/protobuf",
            "signoz.otelCollector.ports.otlp-http.servicePort=14318",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        ep = _server_env(deployment, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        assert ep is not None
        assert ep["value"].endswith(":14318/v1/traces"), (
            f"otlp-http servicePort override must propagate; got {ep['value']!r}"
        )

    def test_disabled_grpc_port_fails_fast(self):
        """If gRPC is the resolved protocol but the operator disabled the
        gRPC service port, helm install/template must fail rather than
        silently render an unreachable endpoint."""
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.otelCollector.ports.otlp.enabled=false",
        )
        assert result.returncode != 0, "helm template should fail when the auto endpoint would point at a disabled port"

    def test_null_grpc_enabled_fails_fast(self):
        """The SigNoz subchart treats `enabled=null` as disabled (its own
        portsConfig uses `if $port.enabled`, which is falsy for nil). Our
        helper must mirror that — otherwise the auto-endpoint points at
        a port the Service doesn't expose."""
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.otelCollector.ports.otlp.enabled=null",
        )
        assert result.returncode != 0, (
            "helm template should fail when ports.otlp.enabled is explicitly null; "
            "subchart omits the port and our chart must not auto-wire to a non-existent one"
        )

    def test_null_grpc_block_fails_fast(self):
        """Equivalent for the case where the operator nulls the entire otlp
        block (a single `--set signoz.otelCollector.ports.otlp=null`)."""
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.otelCollector.ports.otlp=null",
        )
        assert result.returncode != 0, "helm template should fail when the otlp port block itself is null"

    def test_whitespace_traces_protocol_falls_through_to_generic_protocol(self):
        """Validator and env renderer both trim signal-protocol values, so
        whitespace-only tracesProtocol behaves as unset and the app uses
        the generic protocol. The auto-endpoint helper must agree, else
        a whitespace tracesProtocol would silently flip the auto endpoint
        to gRPC port even though the app sends HTTP."""
        result = _render_raw(
            *_set_args(*_SIGNOZ_OTEL_BASE),
            "--set",
            "server.otel.protocol=http/protobuf",
            "--set-string",
            "server.otel.tracesProtocol=   ",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        ep = _server_env(deployment, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        assert ep is not None
        assert ep["value"].endswith("/v1/traces"), (
            f"whitespace tracesProtocol must fall through to generic http/protobuf; got {ep['value']!r}"
        )

    def test_console_traces_exporter_with_disabled_grpc_port_renders(self):
        """Auto-endpoint helpers must not run for signals the app isn't
        exporting via OTLP. tracesExporter=console means the app uses the
        console exporter, not OTLP — disabling the SigNoz gRPC port is
        unrelated to that signal and must not block rendering."""
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.tracesExporter=console",
            "signoz.otelCollector.ports.otlp.enabled=false",
        )
        assert result.returncode == 0, (
            f"render should succeed when traces use console exporter and the "
            f"unused gRPC port is disabled; got: {result.stderr[:600]}"
        )
        deployment = _server_deployment(_docs(result.stdout))
        ep = _server_env(deployment, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        assert ep is None, f"no OTLP traces endpoint should be wired when tracesExporter=console; got {ep!r}"

    def test_explicit_endpoint_with_disabled_grpc_port_renders(self):
        """When the operator pins server.otel.endpoint explicitly, the
        SigNoz auto-default isn't used — disabling a SigNoz collector port
        is irrelevant. Render (including NOTES) must not fail."""
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.endpoint=http://external-collector:4317",
            "signoz.otelCollector.ports.otlp.enabled=false",
        )
        assert result.returncode == 0, (
            f"render should succeed with explicit endpoint and disabled unused SigNoz port; got: {result.stderr[:600]}"
        )

    def test_notes_omits_traces_url_when_traces_endpoint_explicit(self):
        """NOTES must mirror the deployment's per-signal precedence: when the
        operator sets server.otel.tracesEndpoint, the SigNoz auto URL for
        traces must NOT appear in NOTES, otherwise it misleads the operator
        about where traces actually go."""
        result = _render_with_notes(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.tracesEndpoint=http://upstream:9999",
        )
        assert result.returncode == 0, f"helm local render with NOTES failed: {result.stderr[:500]}"
        # SigNoz observability section
        notes = result.stdout
        assert "SIGNOZ (OBSERVABILITY)" in notes
        # The SigNoz auto URL for traces must NOT appear; only the operator's value
        # is in effect for that signal.
        assert "traces: http://test-signoz-otel-collector" not in notes, (
            "NOTES claims SigNoz auto URL for traces even though "
            "server.otel.tracesEndpoint=http://upstream:9999 takes precedence in "
            "the deployment. Output:\n" + notes
        )

    def test_notes_port_forward_uses_configured_signoz_service_port(self):
        """The SigNoz frontend Service listens on `signoz.signoz.service.port`
        (default 8080). NOTES hardcodes `8080:8080`, so when the operator
        passes through an override, the printed port-forward command targets
        a non-existent Service port. NOTES must use the configured value."""
        result = _render_with_notes(
            *_SIGNOZ_OTEL_BASE,
            "signoz.signoz.service.port=18080",
        )
        assert result.returncode == 0, f"helm local render with NOTES failed: {result.stderr[:500]}"
        notes = result.stdout
        port_forward_line = next(
            (line for line in notes.splitlines() if "port-forward" in line and "signoz" in line),
            "<no signoz port-forward line>",
        )
        assert "svc/test-signoz 8080:18080" in notes, (
            f"NOTES port-forward must use the configured signoz service port; got the line:\n{port_forward_line}"
        )

    def test_notes_omits_logs_url_when_logs_endpoint_explicit(self):
        """Same per-signal contract for logs."""
        result = _render_with_notes(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.logsEnabled=true",
            "server.otel.logsEndpoint=http://upstream:9998",
        )
        assert result.returncode == 0, f"helm local render with NOTES failed: {result.stderr[:500]}"
        notes = result.stdout
        assert "logs:   http://test-signoz-otel-collector" not in notes, (
            "NOTES claims SigNoz auto URL for logs even though "
            "server.otel.logsEndpoint=http://upstream:9998 takes precedence."
        )

    def test_notes_omits_logs_url_when_logs_disabled(self):
        """Default config has logsEnabled=false, so the app does not export
        logs even with signoz.enabled+server.otel.enabled. NOTES must not
        advertise an in-cluster logs endpoint in that case — operators read
        it as a wired path but the app never opens it."""
        result = _render_with_notes(*_SIGNOZ_OTEL_BASE)
        assert result.returncode == 0, f"helm local render with NOTES failed: {result.stderr[:500]}"
        notes = result.stdout
        assert "SIGNOZ (OBSERVABILITY)" in notes
        assert "logs: " not in notes and "logs:\t" not in notes, (
            "NOTES advertises a logs endpoint while logsEnabled=false; the "
            "app's log-export path is gated on logsEnabled and the URL is "
            "misleading."
        )

    def test_notes_omits_traces_url_when_tracesexporter_console(self):
        """tracesExporter=console means the app does not OTLP-export traces
        even though signoz is deployed and server.otel is enabled. NOTES
        must not list a SigNoz traces endpoint in that case."""
        result = _render_with_notes(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.tracesExporter=console",
        )
        assert result.returncode == 0, f"helm local render with NOTES failed: {result.stderr[:500]}"
        notes = result.stdout
        assert "SIGNOZ (OBSERVABILITY)" in notes
        assert "traces: http" not in notes, (
            "NOTES advertises a SigNoz traces endpoint while "
            "tracesExporter=console; the app sends to console, not OTLP."
        )

    def test_notes_emits_logs_url_when_logsexporter_uppercase(self):
        """The validator and app both lowercase logsExporter tokens before
        the OTLP check, so logsExporter=OTLP (or Otlp) is an accepted
        config and the deployment renders OTEL_EXPORTER_OTLP_LOGS_ENDPOINT.
        NOTES must mirror that — a case-sensitive comparison would tell
        the operator nothing is wired even though logs are flowing."""
        result = _render_with_notes(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.logsEnabled=true",
            "server.otel.logsExporter=OTLP",
        )
        assert result.returncode == 0, f"helm local render with NOTES failed: {result.stderr[:500]}"
        notes = result.stdout
        assert "logs:   http://test-signoz-otel-collector" in notes, (
            "logs auto-URL should render with logsExporter=OTLP since the "
            "validator and app accept it as the OTLP exporter"
        )

    def test_notes_emits_auto_urls_when_both_signals_active(self):
        """Positive regression gate: when tracesExporter defaults to otlp
        and logsEnabled=true with no explicit endpoints, NOTES must show
        the in-cluster auto-URLs for both signals. Locks in that the
        gating logic doesn't over-fire and silently kill the URLs."""
        result = _render_with_notes(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.logsEnabled=true",
        )
        assert result.returncode == 0, f"helm local render with NOTES failed: {result.stderr[:500]}"
        notes = result.stdout
        assert "In-cluster OTLP collector endpoints wired into the server:" in notes
        assert "traces: http://test-signoz-otel-collector" in notes, (
            "traces auto-URL should render with default tracesExporter (otlp) and signoz.enabled=true"
        )
        assert "logs:   http://test-signoz-otel-collector" in notes, (
            "logs auto-URL should render with logsEnabled=true and default logsExporter"
        )

    def test_render_with_notes_does_not_require_cluster(self, tmp_path):
        """The NOTES tests must run on CI runners that have no kubeconfig.

        Helm 4 defaults server-side behavior on several install/template
        paths, which can perform API discovery before rendering NOTES and
        fail with ``Kubernetes cluster unreachable`` on a fresh runner. The
        helper must explicitly disable server-side behavior while preserving
        NOTES output. This test drives the helper with KUBECONFIG and HOME
        pointed at empty paths to simulate that CI environment.
        """
        env = {
            **{k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL")},
            "KUBECONFIG": str(tmp_path / "absent-kubeconfig"),
            "HOME": str(tmp_path),  # blocks ~/.kube/config fallback
        }
        result = _render_with_notes(*_SIGNOZ_OTEL_BASE, env=env)
        assert result.returncode == 0, (
            "the render-with-notes helper must render NOTES without contacting "
            f"the cluster; got rc={result.returncode}\nstderr={result.stderr[:500]}"
        )
        assert "SIGNOZ (OBSERVABILITY)" in result.stdout, "NOTES output should be present in the cluster-less render"

    def test_endpoint_does_not_hardcode_cluster_local(self):
        """The auto-wired endpoint must not bake in `cluster.local` — that
        suffix is the kubelet default but is configurable per cluster.
        Pods get a search domain that resolves <svc>.<ns>.svc on any
        cluster regardless of the configured DNS suffix."""
        result = _render(*_SIGNOZ_OTEL_BASE, "server.otel.logsEnabled=true")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        for var in ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"):
            ep = _server_env(deployment, var)
            assert ep is not None, f"expected {var} to be set"
            assert "cluster.local" not in ep["value"], (
                f"{var} hard-codes cluster.local; use <svc>.<ns>.svc instead. got {ep['value']!r}"
            )


def _signoz_setup_job(docs: list[dict]) -> dict | None:
    """Return the SigNoz setup Job document, or None if not rendered."""
    for d in docs:
        if d.get("kind") == "Job" and "signoz-setup" in d.get("metadata", {}).get("name", ""):
            return d
    return None


class TestSigNozSetupJobGating:
    """The setup Job logs in with credentials from the authn Secret. SigNoz
    only provisions an admin from those credentials when
    SIGNOZ_USER_ROOT_ENABLED=true. With root provisioning off, no admin
    exists at first install and the Job's login fails repeatedly until it
    exhausts backoffLimit, which makes `helm install --wait` fail."""

    def test_setup_job_renders_with_default_root_enabled(self):
        """Positive gate: with the chart-default values the Job must render."""
        result = _render(*_SIGNOZ_OTEL_BASE)
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        job = _signoz_setup_job(_docs(result.stdout))
        assert job is not None, "signoz-setup Job should render under default values (SIGNOZ_USER_ROOT_ENABLED=true)"

    def test_setup_job_omitted_when_root_provisioning_disabled(self):
        """When the operator opts out of root provisioning, the Job must not
        render — there is no auto-provisioned admin for it to authenticate
        as, so it would loop until backoffLimit and fail `helm --wait`."""
        result = _render_raw(
            *_set_args(*_SIGNOZ_OTEL_BASE),
            "--set-string",
            "signoz.signoz.env.SIGNOZ_USER_ROOT_ENABLED=false",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        job = _signoz_setup_job(_docs(result.stdout))
        assert job is None, (
            "signoz-setup Job rendered with SIGNOZ_USER_ROOT_ENABLED=false; "
            "no admin user is auto-provisioned in this mode, so the Job's "
            "login will fail until backoffLimit and break helm --wait. "
            "Job:\n" + (yaml.safe_dump(job) if job else "")
        )

    def test_setup_job_omitted_when_signoz_disabled(self):
        """Pre-existing gate: Job is tied to signoz.enabled."""
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "signoz.enabled=false",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        job = _signoz_setup_job(_docs(result.stdout))
        assert job is None, "signoz-setup Job should not render when signoz.enabled=false"

    def test_setup_job_renders_with_object_form_root_enabled(self, tmp_path):
        """SigNoz's renderEnv accepts env-map entries in scalar form
        (`KEY: "v"`) AND object form (`KEY: {value: "v"}`). The chart
        renders root-provisioning identically in both cases (the subchart
        emits `value: "true"` regardless), so the gate must accept both —
        otherwise an operator using the object form gets root provisioning
        but no setup Job, and the bundled dashboards/alerts never load."""
        values_file = tmp_path / "object-form.yaml"
        values_file.write_text('signoz:\n  signoz:\n    env:\n      SIGNOZ_USER_ROOT_ENABLED:\n        value: "true"\n')
        result = _render_raw(
            *_set_args(*_SIGNOZ_OTEL_BASE),
            "-f",
            str(values_file),
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        job = _signoz_setup_job(_docs(result.stdout))
        assert job is not None, (
            "signoz-setup Job should render when SIGNOZ_USER_ROOT_ENABLED is "
            "supplied as the object form {value: 'true'} — the subchart "
            "still provisions the admin user, so the dashboards/alerts "
            "reconciliation Job must run."
        )

    def test_setup_job_omitted_with_object_form_root_disabled(self, tmp_path):
        """Symmetric negative: object form with value:'false' must keep the
        Job suppressed (operator did opt out, just via the alternate shape)."""
        values_file = tmp_path / "object-form-off.yaml"
        values_file.write_text(
            'signoz:\n  signoz:\n    env:\n      SIGNOZ_USER_ROOT_ENABLED:\n        value: "false"\n'
        )
        result = _render_raw(
            *_set_args(*_SIGNOZ_OTEL_BASE),
            "-f",
            str(values_file),
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        job = _signoz_setup_job(_docs(result.stdout))
        assert job is None, (
            "signoz-setup Job rendered with object-form "
            "SIGNOZ_USER_ROOT_ENABLED={value: 'false'}; the gate must read "
            "the unwrapped value from object form, not just from scalar form."
        )


def _signoz_cleanup_doc(docs: list[dict], kind: str) -> dict | None:
    for d in docs:
        if d.get("kind") == kind and d.get("metadata", {}).get("name", "").endswith("-signoz-cleanup"):
            return d
    return None


def _signoz_migrator_cleanup_doc(docs: list[dict], kind: str) -> dict | None:
    for d in docs:
        if d.get("kind") == kind and d.get("metadata", {}).get("name", "").endswith("-signoz-migrator-cleanup"):
            return d
    return None


def _signoz_cleanup_script(docs: list[dict]) -> str:
    job = _signoz_cleanup_doc(docs, "Job")
    assert job is not None, "cleanup Job missing from rendered manifest"
    return "\n".join(job["spec"]["template"]["spec"]["containers"][0]["args"])


def _release_role_resources(docs: list[dict]) -> set[str]:
    role = _signoz_migrator_cleanup_doc(docs, "Role")
    assert role is not None, "missing release-ns cleanup Role"
    return {r for rule in role["rules"] for r in rule.get("resources", [])}


def _signoz_zk_cleanup_doc(docs: list[dict], kind: str) -> dict | None:
    for d in docs:
        if d.get("kind") == kind and d.get("metadata", {}).get("name", "").endswith("-signoz-zookeeper-cleanup"):
            return d
    return None


class TestSigNozClickHouseCleanupHook:
    """SigNoz ClickHouse operator children must not survive Helm uninstall."""

    def test_templates_do_not_reference_removed_images_value(self):
        offenders = []
        for path in (CHART_DIR / "templates").rglob("*.yaml"):
            text = path.read_text()
            if ".Values.images" in text:
                offenders.append(str(path.relative_to(CHART_DIR)))
        assert offenders == [], (
            "templates must use utilities.<name>.image after the values "
            f"rename; stale .Values.images references: {offenders}"
        )

    def test_cleanup_hook_renders_when_signoz_enabled(self):
        result = _render(*_SIGNOZ_OTEL_BASE)
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)

        for kind in ("ServiceAccount", "Role", "RoleBinding", "Job"):
            doc = _signoz_cleanup_doc(docs, kind)
            assert doc is not None, f"missing SigNoz cleanup {kind}"
            annotations = doc["metadata"].get("annotations", {})
            assert annotations.get("helm.sh/hook") == "pre-delete"
            assert "before-hook-creation" in annotations.get("helm.sh/hook-delete-policy", "")

        job = _signoz_cleanup_doc(docs, "Job")
        assert job is not None
        container = job["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "docker.io/alpine/k8s:1.28.13"
        script = "\n".join(container["args"])
        assert "delete clickhouseinstallation.clickhouse.altinity.com" in script
        assert "get configmap,statefulset,pod,service" in script
        assert "global.cleanupPVCs=false" in script
        assert "get pvc" not in script

        role = _signoz_cleanup_doc(docs, "Role")
        assert role is not None
        core_resources = {
            resource
            for rule in role["rules"]
            if rule.get("apiGroups") == [""]
            for resource in rule.get("resources", [])
        }
        assert {"configmaps", "pods", "services"}.issubset(core_resources)

    def test_cleanup_hook_omitted_when_signoz_disabled(self):
        result = _render(
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            "signoz.enabled=false",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _signoz_cleanup_doc(docs, "Job") is None
        assert _signoz_cleanup_doc(docs, "Role") is None

    def test_chi_cleanup_omitted_for_external_clickhouse(self):
        # External-ClickHouse configurations (signoz.clickhouse.enabled=false)
        # have no in-chart operator/CRD, so the CHI cleanup Role/RoleBinding
        # would fail and block uninstall. The migrator cleanup must still
        # run because the subchart renders the migrator hook resources
        # regardless of where ClickHouse lives.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.clickhouse.enabled=false",
            "signoz.externalClickhouse.host=clickhouse.example.com",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _signoz_cleanup_doc(docs, "Role") is None
        assert _signoz_cleanup_doc(docs, "RoleBinding") is None
        assert _signoz_cleanup_doc(docs, "Job") is not None
        assert _signoz_cleanup_doc(docs, "ServiceAccount") is not None
        assert _signoz_migrator_cleanup_doc(docs, "Role") is not None
        assert _signoz_migrator_cleanup_doc(docs, "RoleBinding") is not None

        script = _signoz_cleanup_script(docs)
        assert "signoz-telemetrystore-migrator" in script
        assert "ClickHouseInstallation" not in script, (
            "CHI deletion logic must not render when in-chart ClickHouse is off"
        )

    def test_cleanup_hook_pvc_cleanup_is_opt_in(self):
        result = _render(*_SIGNOZ_OTEL_BASE, "global.cleanupPVCs=true")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)

        role = _signoz_cleanup_doc(docs, "Role")
        assert role is not None, "missing cleanup Role"
        pvc_rules = [rule for rule in role["rules"] if "persistentvolumeclaims" in rule.get("resources", [])]
        assert pvc_rules, "PVC delete permission should render only when opted in"

        # Release-namespace Role also gets PVC delete so the new release-scoped
        # PVC sweep can run.
        assert "persistentvolumeclaims" in _release_role_resources(docs)

        script = _signoz_cleanup_script(docs)
        assert "Deleting ClickHouse PVCs" in script
        assert "get pvc" in script
        assert "app.kubernetes.io/instance=test" in script

    def test_cleanup_hook_role_omits_pvc_delete_by_default(self):
        result = _render(*_SIGNOZ_OTEL_BASE)
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        role = _signoz_cleanup_doc(docs, "Role")
        assert role is not None, "missing cleanup Role"
        assert all("persistentvolumeclaims" not in rule.get("resources", []) for rule in role["rules"])
        assert "persistentvolumeclaims" not in _release_role_resources(docs)
        assert 'kubectl -n "$release_ns" get pvc' not in _signoz_cleanup_script(docs)

    def test_migrator_cleanup_role_and_script_render(self):
        # The SigNoz subchart converts the telemetrystore-migrator SA + Job
        # into pre-upgrade hooks; helm uninstall leaves them orphaned and
        # blocks reinstall with "invalid ownership metadata". The pre-delete
        # hook must delete those leftovers from the release namespace.
        result = _render(*_SIGNOZ_OTEL_BASE)
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)

        role = _signoz_migrator_cleanup_doc(docs, "Role")
        assert role is not None, "missing migrator-cleanup Role"
        verbs_by_resource: dict[str, set[str]] = {}
        for rule in role["rules"]:
            for resource in rule.get("resources", []):
                verbs_by_resource.setdefault(resource, set()).update(rule.get("verbs", []))
        assert "delete" in verbs_by_resource.get("serviceaccounts", set())
        assert "delete" in verbs_by_resource.get("jobs", set())

        binding = _signoz_migrator_cleanup_doc(docs, "RoleBinding")
        assert binding is not None, "missing migrator-cleanup RoleBinding"
        assert binding["roleRef"]["name"].endswith("signoz-migrator-cleanup")
        assert binding["subjects"][0]["name"].endswith("signoz-cleanup")

        script = _signoz_cleanup_script(docs)
        assert "signoz-telemetrystore-migrator" in script
        assert 'delete job.batch "$migrator_job"' in script
        assert 'delete serviceaccount "$migrator_sa"' in script

    def test_migrator_cleanup_honors_custom_sa_name(self):
        # The upstream chart uses `telemetryStoreMigrator.serviceAccount.name`
        # for the SA but `telemetryStoreMigrator.name` for the Job. The
        # cleanup script must resolve them independently or it will leave
        # the customized hook SA orphaned.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.telemetryStoreMigrator.serviceAccount.name=my-custom-sa",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        script = _signoz_cleanup_script(docs)
        assert 'migrator_job="signoz-telemetrystore-migrator"' in script
        assert 'migrator_sa="my-custom-sa"' in script

    def test_migrator_cleanup_skips_sa_when_create_disabled(self):
        # When `telemetryStoreMigrator.serviceAccount.create=false` the
        # subchart does not render an SA, so the cleanup should not attempt
        # to delete one.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.telemetryStoreMigrator.serviceAccount.create=false",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        script = _signoz_cleanup_script(docs)
        assert 'delete job.batch "$migrator_job"' in script
        assert "delete serviceaccount" not in script
        assert "migrator_sa" not in script

    def test_migrator_cleanup_omitted_when_migrator_disabled(self):
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.telemetryStoreMigrator.enabled=false",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _signoz_migrator_cleanup_doc(docs, "Role") is None
        assert _signoz_migrator_cleanup_doc(docs, "RoleBinding") is None
        script = _signoz_cleanup_script(docs)
        assert "telemetrystore-migrator" not in script

    def test_cleanup_hook_names_stay_distinct_under_long_fullname(self):
        # With a 56-char fullnameOverride, appending the two cleanup
        # suffixes and then truncating to 63 chars used to collapse both
        # names to the same string, producing duplicate Role/RoleBinding
        # resources and breaking the hook. Reserve room for the longer
        # suffix before truncating.
        long_name = "a" * 56
        result = _render(*_SIGNOZ_OTEL_BASE, f"fullnameOverride={long_name}")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        chi_role = _signoz_cleanup_doc(docs, "Role")
        mig_role = _signoz_migrator_cleanup_doc(docs, "Role")
        assert chi_role is not None
        assert mig_role is not None
        chi_name = chi_role["metadata"]["name"]
        mig_name = mig_role["metadata"]["name"]
        assert chi_name != mig_name, f"cleanup names collided under long fullname: {chi_name!r} == {mig_name!r}"
        assert len(chi_name) <= 63
        assert len(mig_name) <= 63
        assert chi_name.endswith("-signoz-cleanup")
        assert mig_name.endswith("-signoz-migrator-cleanup")

    def test_migrator_cleanup_defaults_empty_name(self):
        # An operator explicitly setting `telemetryStoreMigrator.name=""`
        # gets the subchart default ("signoz-telemetrystore-migrator");
        # the cleanup script must mirror that fallback or it renders
        # `kubectl delete job.batch ""` and fails under `set -e`.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.telemetryStoreMigrator.name=",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        script = _signoz_cleanup_script(docs)
        assert 'migrator_job="signoz-telemetrystore-migrator"' in script
        assert 'migrator_sa="signoz-telemetrystore-migrator"' in script
        assert 'migrator_job=""' not in script
        assert 'migrator_sa=""' not in script

    def test_release_pvc_sweep_renders_for_external_clickhouse(self):
        # External ClickHouse + cleanupPVCs=true: no CHI cleanup runs, but
        # the SigNoz subchart's signoz-db / zookeeper PVCs still need
        # sweeping in the release namespace.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.clickhouse.enabled=false",
            "signoz.externalClickhouse.host=clickhouse.example.com",
            "global.cleanupPVCs=true",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _signoz_cleanup_doc(docs, "Role") is None, "CHI Role must not render under external ClickHouse"
        assert "persistentvolumeclaims" in _release_role_resources(docs)
        script = _signoz_cleanup_script(docs)
        assert 'kubectl -n "$release_ns" get pvc' in script
        assert "ClickHouseInstallation" not in script

    def test_zookeeper_pvc_sweep_targets_override_namespace(self):
        # signoz.clickhouse.zookeeper.namespaceOverride places the ZK
        # StatefulSet outside the release namespace. With cleanupPVCs=true,
        # the hook must sweep that namespace too — a dedicated Role +
        # RoleBinding render there, and the script runs an extra
        # kubectl delete pvc targeted at it.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.clickhouse.zookeeper.namespaceOverride=zk-only",
            "global.cleanupPVCs=true",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)

        zk_role = _signoz_zk_cleanup_doc(docs, "Role")
        assert zk_role is not None, "missing zookeeper-cleanup Role"
        assert zk_role["metadata"]["namespace"] == "zk-only"
        zk_resources = {r for rule in zk_role["rules"] for r in rule.get("resources", [])}
        assert zk_resources == {"persistentvolumeclaims"}

        zk_binding = _signoz_zk_cleanup_doc(docs, "RoleBinding")
        assert zk_binding is not None
        assert zk_binding["metadata"]["namespace"] == "zk-only"
        assert zk_binding["subjects"][0]["name"].endswith("signoz-cleanup")

        script = _signoz_cleanup_script(docs)
        assert 'zk_ns="zk-only"' in script
        assert 'kubectl -n "$zk_ns" get pvc' in script

    def test_zookeeper_pvc_sweep_omitted_when_zk_in_release_namespace(self):
        # No override → ZK lives in release ns → the release sweep already
        # catches its PVCs; no dedicated ZK Role or sweep block should render.
        result = _render(*_SIGNOZ_OTEL_BASE, "global.cleanupPVCs=true")
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _signoz_zk_cleanup_doc(docs, "Role") is None
        script = _signoz_cleanup_script(docs)
        assert "zk_ns=" not in script
        assert "zookeeper namespace" not in script

    def test_zookeeper_pvc_sweep_reuses_chi_role_when_namespaces_match(self):
        # ZK override matches an explicit CHI namespace override: the
        # existing CHI Role already has PVC delete in that namespace, so no
        # second dedicated Role should render. The sweep block must still
        # run and target the shared namespace.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.clickhouse.namespace=ch-shared",
            "signoz.clickhouse.zookeeper.namespaceOverride=ch-shared",
            "global.cleanupPVCs=true",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _signoz_zk_cleanup_doc(docs, "Role") is None, (
            "dedicated ZK Role must not render when ZK shares CHI namespace"
        )
        script = _signoz_cleanup_script(docs)
        assert 'zk_ns="ch-shared"' in script
        assert 'kubectl -n "$zk_ns" get pvc' in script

    def test_zookeeper_pvc_sweep_omitted_without_cleanupPVCs(self):
        # cleanupPVCs=false: even with an override namespace, no sweep.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.clickhouse.zookeeper.namespaceOverride=zk-only",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _signoz_zk_cleanup_doc(docs, "Role") is None
        assert "zk_ns=" not in _signoz_cleanup_script(docs)

    def test_release_pvc_sweep_renders_when_migrator_disabled(self):
        # cleanupPVCs=true with migrator disabled: release-ns Role still
        # renders but only with PVC perms — no SA/Job verbs.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.telemetryStoreMigrator.enabled=false",
            "global.cleanupPVCs=true",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _release_role_resources(docs) == {"persistentvolumeclaims"}

    def test_cleanup_hook_omitted_when_chi_and_migrator_both_disabled(self):
        # No CHI to delete and no migrator orphans means no cleanup needed.
        result = _render(
            *_SIGNOZ_OTEL_BASE,
            "signoz.clickhouse.enabled=false",
            "signoz.externalClickhouse.host=clickhouse.example.com",
            "signoz.telemetryStoreMigrator.enabled=false",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = _docs(result.stdout)
        assert _signoz_cleanup_doc(docs, "Job") is None
        assert _signoz_cleanup_doc(docs, "ServiceAccount") is None
        assert _signoz_migrator_cleanup_doc(docs, "Role") is None


_ADB_S_BASE = (
    "client.cookieSecret=cccccccccccccccccccccccccccccccc",
    "server.database.type=ADB-S",
    "server.database.oci.ocid=ocid1.autonomousdatabase.oc1..test",
    "server.database.adb.serviceName=mydb_low",
    "server.database.adb.skipCrdCheck=true",
    "server.database.username=admin",
    "server.database.password=foo",
)


def _autonomousdatabase_doc(docs: list[dict]) -> dict | None:
    for d in docs:
        if d.get("kind") == "AutonomousDatabase":
            return d
    return None


class TestAutonomousDatabaseAction:
    """`spec.action` is owned by the OraOperator after the initial bind.
    Re-templating it on every upgrade fights server-side-apply field
    ownership and fails with `conflict with "manager"`. The chart gates
    the field on whether the CR already exists in the cluster (via
    `lookup`) so it renders on initial creation — whether that is a fresh
    install OR an upgrade that migrates the release to ADB-S — and is
    omitted on subsequent upgrades."""

    def test_action_renders_when_cr_not_yet_in_cluster(self):
        # `lookup` returns empty under `helm template`, so this also
        # covers the "upgrade adds ADB-S for the first time" path —
        # which is exactly when the operator still needs the Sync bind.
        result = _render(*_ADB_S_BASE)
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        adb = _autonomousdatabase_doc(_docs(result.stdout))
        assert adb is not None, "AutonomousDatabase CR did not render"
        assert adb["spec"].get("action") == "Sync"

    def test_action_gate_uses_lookup(self):
        # Static check: the gate must consult cluster state via `lookup`
        # so the field renders on first creation regardless of whether
        # that creation happens via `helm install` or a migration during
        # `helm upgrade` (non-ADB-S → ADB-S). A `.Release.IsInstall` gate
        # would miss the migration path.
        text = (CHART_DIR / "templates" / "server" / "database" / "adb-operator.yaml").read_text()
        assert 'lookup "database.oracle.com/v4" "AutonomousDatabase"' in text, (
            "adb-operator.yaml must `lookup` the AutonomousDatabase to gate "
            "spec.action on cluster state, not on the release-level install flag"
        )
        # The gate condition itself (not the explanatory comment) must not
        # use .Release.IsInstall. Strip Helm comment blocks before checking.
        stripped = re.sub(r"{{-? */\*.*?\*/ *-?}}", "", text, flags=re.DOTALL)
        assert ".Release.IsInstall" not in stripped, (
            "spec.action gate must not use .Release.IsInstall — it misses the upgrade-to-ADB-S migration path"
        )


class TestSigNozCleanupHookRbacContract:
    """`signoz.cleanup.{rbac,serviceAccount}.create=false` must actually
    suppress chart-managed resources. Sprig's `default true X` returns true
    when X is explicitly false (false is the zero value), so the original
    `default true $cleanupRbac.create` idiom silently ignored operator
    overrides. The chart uses `dig "create" true …` instead — these tests
    lock in that contract.
    """

    _BASE = (
        "global.api.apiKey=dummy-api-key",
        "client.cookieSecret=cccccccccccccccccccccccccccccccc",
        "signoz.enabled=true",
    )

    @staticmethod
    def _cleanup_docs(stdout: str) -> list[dict]:
        """Return rendered docs whose Source path is the cleanup-hook template."""
        out: list[dict] = []
        current_source = ""
        for chunk in stdout.split("\n---\n"):
            for line in chunk.splitlines():
                if line.startswith("# Source:"):
                    current_source = line.split(":", 1)[1].strip()
                    break
            if current_source.endswith("observability/signoz/cleanup-hook.yaml"):
                for d in yaml.safe_load_all(chunk):
                    if isinstance(d, dict):
                        out.append(d)
        return out

    def test_rbac_create_false_suppresses_chart_roles(self):
        result = _render_raw(
            *_set_args(*self._BASE),
            "--set",
            "signoz.cleanup.rbac.create=false",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        kinds = {d["kind"] for d in self._cleanup_docs(result.stdout)}
        assert "Role" not in kinds and "RoleBinding" not in kinds, (
            f"signoz.cleanup.rbac.create=false must suppress chart Role/RoleBindings; got {sorted(kinds)}"
        )

    def test_service_account_create_false_with_name_suppresses_chart_sa(self):
        result = _render_raw(
            *_set_args(*self._BASE),
            "--set",
            "signoz.cleanup.serviceAccount.create=false",
            "--set",
            "signoz.cleanup.serviceAccount.name=my-byo-sa",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        docs = self._cleanup_docs(result.stdout)
        sa_docs = [d for d in docs if d["kind"] == "ServiceAccount"]
        assert sa_docs == [], f"""
            serviceAccount.create=false must suppress chart ServiceAccount;
            got {[d["metadata"]["name"] for d in sa_docs]}
            """
        # RoleBindings should still reference the operator-supplied name.
        rb_subject_names = {
            subj["name"]
            for d in docs
            if d["kind"] == "RoleBinding"
            for subj in d.get("subjects", [])
            if subj.get("kind") == "ServiceAccount"
        }
        assert rb_subject_names == {"my-byo-sa"}, (
            f"RoleBindings must reference the operator-supplied SA name; got {rb_subject_names}"
        )

    def test_service_account_create_false_without_name_fails(self):
        result = _render_raw(
            *_set_args(*self._BASE),
            "--set",
            "signoz.cleanup.serviceAccount.create=false",
        )
        assert result.returncode != 0, "create=false without a name must fail validation; render succeeded"
        assert "serviceAccount.name is required" in result.stderr, (
            f"expected the explicit missing-name error; got: {result.stderr[:500]}"
        )

    def test_default_creates_chart_managed_sa_and_rbac(self):
        result = _render_raw(*_set_args(*self._BASE))
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        kinds = [d["kind"] for d in self._cleanup_docs(result.stdout)]
        assert kinds.count("ServiceAccount") >= 1
        assert kinds.count("Role") >= 1
        assert kinds.count("RoleBinding") >= 1


class TestClientOciSourceBucketEnv:
    """client.oci.sourceBucket* values map faithfully to pod env entries.

    The chart layer does NOT enforce the compartment-as-anchor rule — it
    injects whatever the operator supplies. The client honours or ignores
    each env var at render time. These tests cover the chart's mapping.
    """

    _COOKIE = "client.cookieSecret=ccccccccccccccccccccccccccccccccc"
    _COMPARTMENT_OCID = "ocid1.compartment.oc1..testbucketcompartment"
    _BUCKET_NAME = "test-corpus-bucket"

    def _deployment(self, result) -> dict:
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        return _client_deployment(_docs(result.stdout))

    def test_neither_set_omits_both_env_entries(self):
        deployment = self._deployment(_render(self._COOKIE))
        assert _client_env(deployment, "AIO_OCI_SOURCE_BUCKET_COMPARTMENT_ID") is None
        assert _client_env(deployment, "AIO_OCI_SOURCE_BUCKET_NAME") is None

    def test_compartment_only_renders_compartment_env(self):
        deployment = self._deployment(
            _render(self._COOKIE, f"client.oci.sourceBucketCompartmentId={self._COMPARTMENT_OCID}")
        )
        entry = _client_env(deployment, "AIO_OCI_SOURCE_BUCKET_COMPARTMENT_ID")
        assert entry is not None and entry["value"] == self._COMPARTMENT_OCID
        assert _client_env(deployment, "AIO_OCI_SOURCE_BUCKET_NAME") is None

    def test_bucket_only_renders_bucket_env_faithfully(self):
        """The chart does not enforce compartment-as-anchor; an orphan
        bucketName still gets injected. The client ignores it at runtime."""
        deployment = self._deployment(_render(self._COOKIE, f"client.oci.sourceBucketName={self._BUCKET_NAME}"))
        entry = _client_env(deployment, "AIO_OCI_SOURCE_BUCKET_NAME")
        assert entry is not None and entry["value"] == self._BUCKET_NAME
        assert _client_env(deployment, "AIO_OCI_SOURCE_BUCKET_COMPARTMENT_ID") is None

    def test_both_set_renders_both_env_entries(self):
        deployment = self._deployment(
            _render(
                self._COOKIE,
                f"client.oci.sourceBucketCompartmentId={self._COMPARTMENT_OCID}",
                f"client.oci.sourceBucketName={self._BUCKET_NAME}",
            )
        )
        compartment_entry = _client_env(deployment, "AIO_OCI_SOURCE_BUCKET_COMPARTMENT_ID")
        bucket_entry = _client_env(deployment, "AIO_OCI_SOURCE_BUCKET_NAME")
        assert compartment_entry is not None and compartment_entry["value"] == self._COMPARTMENT_OCID
        assert bucket_entry is not None and bucket_entry["value"] == self._BUCKET_NAME
