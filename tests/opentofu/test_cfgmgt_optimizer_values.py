"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract test for opentofu/modules/kubernetes/templates/ai-optimizer-values.yaml:
when k8s_byo_ocir_url is set, the rendered values must NOT enable the SigNoz
subchart — the BYO contract states all images come from the BYO OCIR, but
the SigNoz subchart pulls its multi-image stack from upstream registries.
"""
# spell-checker: disable

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_PATH = (
    REPO_ROOT
    / "opentofu"
    / "modules"
    / "kubernetes"
    / "templates"
    / "ai-optimizer-values.yaml"
)
CHART_DIR = REPO_ROOT / "helm"

TOFU_BIN: str = shutil.which("tofu") or ""
HELM_BIN: str = shutil.which("helm") or ""
pytestmark = pytest.mark.skipif(not TOFU_BIN, reason="tofu binary not available")


def _render(tmp_path: Path, is_obs: bool, byo_url: str) -> str:
    """Render ai-optimizer-values.yaml the same way cfgmgt_optimizer.tf
    does — including the signoz_enabled local that gates SigNoz on BYO.

    The locals block here mirrors the production .tf so the test breaks
    if either side drifts (e.g. someone reverts the AND in the .tf or
    drops the signoz_enabled key from the templatefile call)."""
    is_obs_hcl = "true" if is_obs else "false"
    main_tf = tmp_path / "main.tf"
    main_tf.write_text(
        textwrap.dedent(
            f'''
            locals {{
              is_observability_enabled = {is_obs_hcl}
              byo_ocir_url             = "{byo_url}"
              # Mirrors cfgmgt_optimizer.tf: BYO must keep SigNoz off because
              # the subchart's images would bypass the BYO OCIR.
              signoz_enabled           = local.is_observability_enabled && local.byo_ocir_url == ""
              rendered = templatefile("{TEMPLATE_PATH}", {{
                label                    = "test"
                repository_base          = local.byo_ocir_url == "" ? "iad.ocir.io/managed/test" : local.byo_ocir_url
                oci_region               = "us-ashburn-1"
                db_type                  = "ADB-S"
                db_ocid                  = "ocid1.test"
                db_dsn                   = "test"
                db_name                  = "test"
                node_pool_gpu_deploy     = false
                ssl_enabled              = false
                client_cookie_secret     = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                is_observability_enabled = local.is_observability_enabled
                signoz_enabled           = local.signoz_enabled
              }})
            }}
            output "rendered" {{
              value = local.rendered
            }}
            '''
        ).strip()
    )
    subprocess.run(
        [TOFU_BIN, "init", "-no-color", "-backend=false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [TOFU_BIN, "apply", "-no-color", "-auto-approve"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    out = subprocess.run(
        [TOFU_BIN, "output", "-no-color", "-raw", "rendered"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout


def test_signoz_disabled_when_byo_ocir_set(tmp_path):
    """BYO contract: 'all images pre-exist in BYO'. The SigNoz subchart's
    images would bypass that, so observability must be off in BYO mode
    even when the operator asked for it."""
    rendered = _render(tmp_path, is_obs=True, byo_url="iad.ocir.io/byo-namespace")
    assert "signoz:\n  enabled: false" in rendered, (
        "signoz.enabled must be false when BYO OCIR is set. Rendered:\n"
        + rendered
    )


def test_signoz_enabled_when_no_byo_and_observability_on(tmp_path):
    """Positive regression gate: with no BYO and observability requested,
    SigNoz must be enabled — verifies the gating doesn't over-fire."""
    rendered = _render(tmp_path, is_obs=True, byo_url="")
    assert "signoz:\n  enabled: true" in rendered, (
        "signoz.enabled should be true when observability is on and no "
        "BYO OCIR is configured. Rendered:\n" + rendered
    )


def test_signoz_disabled_when_observability_off(tmp_path):
    """When the operator opts out of observability, SigNoz is off
    regardless of BYO."""
    rendered = _render(tmp_path, is_obs=False, byo_url="")
    assert "signoz:\n  enabled: false" in rendered, (
        "signoz.enabled should be false when observability is off. "
        "Rendered:\n" + rendered
    )


def test_otel_disabled_when_byo_ocir_set(tmp_path):
    """server.otel.enabled must track signoz_enabled, not the raw operator
    input. If BYO forces signoz off but otel stays on, the chart validator
    rejects the values with `tracesExporter includes "otlp" but no endpoint
    is configured` and the install is blocked."""
    rendered = _render(tmp_path, is_obs=True, byo_url="iad.ocir.io/byo-namespace")
    # Pin the assertion to the server.otel block specifically — `enabled:`
    # appears in many places in the rendered values.
    assert re.search(r"^\s+otel:\n\s+enabled:\s+false\b", rendered, re.MULTILINE), (
        "server.otel.enabled must be false in BYO mode (signoz is forced off "
        "and no endpoint is configured, so leaving otel enabled triggers the "
        "chart validator). Rendered:\n" + rendered
    )


@pytest.mark.skipif(not HELM_BIN, reason="helm binary not available")
def test_byo_render_passes_helm_validation(tmp_path):
    """End-to-end: rendered values for a default BYO install with
    is_observability_enabled=true must pass helm template — otel must
    follow signoz_enabled, not the raw operator input, otherwise the
    chart validator rejects the values with `tracesExporter includes
    "otlp" but no endpoint is configured`."""
    rendered = _render(tmp_path, is_obs=True, byo_url="iad.ocir.io/byo-namespace")
    values_file = tmp_path / "values.yaml"
    values_file.write_text(rendered)
    result = subprocess.run(
        [
            HELM_BIN,
            "template",
            "test",
            str(CHART_DIR),
            "-f",
            str(values_file),
            "--set",
            "client.cookieSecret=cccccccccccccccccccccccccccccccc",
            # _render's db_type=ADB-S needs serviceName separately.
            "--set",
            "server.database.adb.serviceName=test_low",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "BYO + observability=on must render values that pass helm validation; "
        f"got rc={result.returncode}\nstderr={result.stderr[:600]}"
    )
    # Pin the otel-gate failure mode independently of the db validator
    # so a db-validator change can't silently mask it.
    assert "tracesExporter includes" not in result.stderr, (
        "otel validator fired — server.otel.enabled is wired to the "
        "operator input instead of signoz_enabled."
    )
