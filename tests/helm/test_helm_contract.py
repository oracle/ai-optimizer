"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract tests for the Helm chart: enforce explicit operator configuration of
the client cookie-signing secret, mirroring the existing apiKey pattern.
"""
# spell-checker: disable

import os
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


def _install_dry_run(
    *extra_sets: str, env: dict | None = None
) -> subprocess.CompletedProcess:
    """Run helm install --dry-run=client to render NOTES.txt
    (`helm template` does not emit NOTES output)."""
    cmd = [
        "helm",
        "install",
        "--dry-run=client",
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
    return [
        d for d in docs
        if d.get("kind") == "Secret" and d.get("data", {}).get("cookieSecret") is not None
    ]


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


_SIGNOZ_OTEL_BASE = (
    "signoz.enabled=true",
    "server.otel.enabled=true",
    "server.otel.insecure=true",
    "client.cookieSecret=cccccccccccccccccccccccccccccccc",
    "server.database.type=SIDB-FREE",
    "server.database.image.repository=foo",
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
            assert "/v1/" not in ep["value"], (
                f"gRPC endpoint {var} must not include a signal path; got {ep['value']!r}"
            )

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
        assert result.returncode != 0, (
            "helm template should fail when the auto endpoint would point at a disabled port"
        )

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
        assert result.returncode != 0, (
            "helm template should fail when the otlp port block itself is null"
        )

    def test_whitespace_traces_protocol_falls_through_to_generic_protocol(self):
        """Validator and env renderer both trim signal-protocol values, so
        whitespace-only tracesProtocol behaves as unset and the app uses
        the generic protocol. The auto-endpoint helper must agree, else
        a whitespace tracesProtocol would silently flip the auto endpoint
        to gRPC port even though the app sends HTTP."""
        result = _render_raw(
            *_set_args(*_SIGNOZ_OTEL_BASE),
            "--set", "server.otel.protocol=http/protobuf",
            "--set-string", "server.otel.tracesProtocol=   ",
        )
        assert result.returncode == 0, f"render failed: {result.stderr[:500]}"
        deployment = _server_deployment(_docs(result.stdout))
        ep = _server_env(deployment, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        assert ep is not None
        assert ep["value"].endswith("/v1/traces"), (
            f"whitespace tracesProtocol must fall through to generic http/protobuf; "
            f"got {ep['value']!r}"
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
        assert ep is None, (
            f"no OTLP traces endpoint should be wired when tracesExporter=console; "
            f"got {ep!r}"
        )

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
            f"render should succeed with explicit endpoint and disabled "
            f"unused SigNoz port; got: {result.stderr[:600]}"
        )

    def test_notes_omits_traces_url_when_traces_endpoint_explicit(self):
        """NOTES must mirror the deployment's per-signal precedence: when the
        operator sets server.otel.tracesEndpoint, the SigNoz auto URL for
        traces must NOT appear in NOTES, otherwise it misleads the operator
        about where traces actually go."""
        result = _install_dry_run(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.tracesEndpoint=http://upstream:9999",
        )
        assert result.returncode == 0, f"install --dry-run failed: {result.stderr[:500]}"
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
        result = _install_dry_run(
            *_SIGNOZ_OTEL_BASE,
            "signoz.signoz.service.port=18080",
        )
        assert result.returncode == 0, f"install --dry-run failed: {result.stderr[:500]}"
        notes = result.stdout
        port_forward_line = next(
            (line for line in notes.splitlines() if "port-forward" in line and "signoz" in line),
            "<no signoz port-forward line>",
        )
        assert "svc/test-signoz 8080:18080" in notes, (
            "NOTES port-forward must use the configured signoz service port; "
            f"got the line:\n{port_forward_line}"
        )

    def test_notes_omits_logs_url_when_logs_endpoint_explicit(self):
        """Same per-signal contract for logs."""
        result = _install_dry_run(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.logsEnabled=true",
            "server.otel.logsEndpoint=http://upstream:9998",
        )
        assert result.returncode == 0, f"install --dry-run failed: {result.stderr[:500]}"
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
        result = _install_dry_run(*_SIGNOZ_OTEL_BASE)
        assert result.returncode == 0, f"install --dry-run failed: {result.stderr[:500]}"
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
        result = _install_dry_run(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.tracesExporter=console",
        )
        assert result.returncode == 0, f"install --dry-run failed: {result.stderr[:500]}"
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
        result = _install_dry_run(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.logsEnabled=true",
            "server.otel.logsExporter=OTLP",
        )
        assert result.returncode == 0, f"install --dry-run failed: {result.stderr[:500]}"
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
        result = _install_dry_run(
            *_SIGNOZ_OTEL_BASE,
            "server.otel.logsEnabled=true",
        )
        assert result.returncode == 0, f"install --dry-run failed: {result.stderr[:500]}"
        notes = result.stdout
        assert "In-cluster OTLP collector endpoints wired into the server:" in notes
        assert "traces: http://test-signoz-otel-collector" in notes, (
            "traces auto-URL should render with default tracesExporter (otlp) "
            "and signoz.enabled=true"
        )
        assert "logs:   http://test-signoz-otel-collector" in notes, (
            "logs auto-URL should render with logsEnabled=true and "
            "default logsExporter"
        )

    def test_install_dry_run_does_not_require_cluster(self, tmp_path):
        """The NOTES tests must run on CI runners that have no kubeconfig.

        Helm 3.13+ treats bare ``helm install --dry-run`` as server-side
        and contacts the API server before rendering NOTES — failing with
        ``Kubernetes cluster unreachable`` on a fresh runner. The helper
        must use the explicitly-client-side form so rendering is fully
        local. This test drives the helper with KUBECONFIG and HOME
        pointed at empty paths to simulate that CI environment.
        """
        env = {
            **{k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL")},
            "KUBECONFIG": str(tmp_path / "absent-kubeconfig"),
            "HOME": str(tmp_path),  # blocks ~/.kube/config fallback
        }
        result = _install_dry_run(*_SIGNOZ_OTEL_BASE, env=env)
        assert result.returncode == 0, (
            "the install-dry-run helper must render NOTES without contacting "
            f"the cluster; got rc={result.returncode}\nstderr={result.stderr[:500]}"
        )
        assert "SIGNOZ (OBSERVABILITY)" in result.stdout, (
            "NOTES output should be present in the cluster-less render"
        )

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
                f"{var} hard-codes cluster.local; use <svc>.<ns>.svc instead. "
                f"got {ep['value']!r}"
            )
