"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract tests for opentofu/modules/kubernetes/templates/ai-optimizer-values.yaml:
under k8s_byo_ocir_url every chart-managed AND SigNoz subchart image must
resolve through global.imageRegistry (Helm propagates the parent
`global.*` namespace into subcharts), and the rendered chart must not
require external network downloads in BYO registry mode.
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
BYO_URL = "iad.ocir.io/byo-namespace"
COOKIE_SECRET = "cccccccccccccccccccccccccccccccc"

TOFU_BIN: str = shutil.which("tofu") or ""
HELM_BIN: str = shutil.which("helm") or ""
pytestmark = pytest.mark.skipif(not TOFU_BIN, reason="tofu binary not available")

# Compiled once: external-download detector splits a `wget`/`curl <url>` line
# into the scheme-stripped host and lets internal_host_re decide whether
# it's cluster-local. ${VAR} is treated as internal because in-cluster
# probes resolve those at runtime from Service env, never public DNS.
_FETCH_RE = re.compile(
    r"(?:^|[\s'\"`])(?:wget|curl)\b[^\n;&|]*?\bhttps?://([^\s'\"`>]+)",
    re.IGNORECASE,
)
_INTERNAL_HOST_RE = re.compile(
    r"^(?:127\.|localhost|signoz-|\$\{?\w+\}?|"
    r"[\w.-]+\.svc(?:\.cluster\.local)?)(?:[:/]|$)",
    re.IGNORECASE,
)


def _render(tmp_path: Path, is_obs: bool, byo_url: str) -> str:
    """Render ai-optimizer-values.yaml the way cfgmgt_optimizer.tf does:
    is_observability_enabled forwards directly; byo_ocir_url is
    forwarded as ocir_url."""
    is_obs_hcl = "true" if is_obs else "false"
    main_tf = tmp_path / "main.tf"
    main_tf.write_text(
        textwrap.dedent(
            f'''
            locals {{
              is_observability_enabled = {is_obs_hcl}
              byo_ocir_url             = "{byo_url}"
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
                ocir_url                 = local.byo_ocir_url
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


def _helm_template(values_path: Path) -> str:
    """helm template against the chart with the BYO values file."""
    return subprocess.run(
        [
            HELM_BIN,
            "template",
            "test",
            str(CHART_DIR),
            "-f",
            str(values_path),
            "--set",
            f"client.cookieSecret={COOKIE_SECRET}",
            # _render's db_type=ADB-S needs serviceName separately.
            "--set",
            "server.database.adb.serviceName=test_low",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture(scope="module")
def byo_helm_render(tmp_path_factory) -> tuple[str, str]:
    """Render the BYO values once per module and run helm template once.
    The three end-to-end BYO tests assert different invariants on the
    same output, so sharing the render avoids 3× tofu/helm work."""
    if not HELM_BIN:
        pytest.skip("helm binary not available")
    tmp_path = tmp_path_factory.mktemp("byo_helm_render")
    rendered = _render(tmp_path, is_obs=True, byo_url=BYO_URL)
    values_file = tmp_path / "values.yaml"
    values_file.write_text(rendered)
    return rendered, _helm_template(values_file)


def test_ocir_url_set_when_byo_ocir_set(tmp_path):
    """BYO sets the chart-wide global.imageRegistry; Helm propagates this
    into the SigNoz subchart's global block, so every subchart image
    resolves through the BYO registry alongside the chart's own images."""
    rendered = _render(tmp_path, is_obs=True, byo_url=BYO_URL)
    # Extract the top-level `global:` block (its child lines are indented;
    # the block ends at the first non-indented line).
    block_match = re.search(
        r"^global:\n((?:[ \t][^\n]*\n)+)", rendered, re.MULTILINE
    )
    assert block_match, "no top-level `global:` block found:\n" + rendered
    global_block = block_match.group(1)
    assert f'imageRegistry: "{BYO_URL}"' in global_block, (
        "global.imageRegistry must be set to byo_ocir_url so every image "
        "(chart-managed and SigNoz subchart) resolves under the BYO "
        "registry. Rendered:\n" + rendered
    )


def test_ocir_url_omitted_when_no_byo(tmp_path):
    """Without BYO the key must be absent (an empty string would force
    `/<owner>/<image>` paths instead of using upstream defaults)."""
    rendered = _render(tmp_path, is_obs=True, byo_url="")
    assert "signoz:\n  enabled: true" in rendered, (
        "signoz.enabled should be true when observability is on and no "
        "BYO OCIR is configured. Rendered:\n" + rendered
    )
    # Strip comment lines so an explanatory comment that mentions
    # imageRegistry doesn't accidentally pass for a real value.
    payload = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith("#")
    )
    assert "imageRegistry" not in payload, (
        "global.imageRegistry must be omitted when byo_ocir_url is empty so "
        "the chart's per-image registry defaults apply. Rendered:\n" + rendered
    )


def test_signoz_block_omitted_when_observability_off(tmp_path):
    """When observability is off the entire signoz: block is omitted from
    the values file. The umbrella chart's default (signoz.enabled=false)
    then applies, leaving the subchart disabled."""
    rendered = _render(tmp_path, is_obs=False, byo_url="")
    payload = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith("#")
    )
    assert re.search(r"^signoz:", payload, re.MULTILINE) is None, (
        "signoz: block should be absent when observability is off so the "
        "chart-default (enabled: false) governs. Rendered:\n" + rendered
    )


def test_otel_enabled_when_byo_ocir_set(tmp_path):
    """server.otel.enabled tracks is_observability_enabled."""
    rendered = _render(tmp_path, is_obs=True, byo_url=BYO_URL)
    # Pin to the server.otel block specifically — `enabled:` appears in
    # many places in the rendered values.
    assert re.search(r"^\s+otel:\n\s+enabled:\s+true\b", rendered, re.MULTILINE), (
        "server.otel.enabled must be true when observability is on. "
        "Rendered:\n" + rendered
    )


def test_byo_render_passes_helm_validation(byo_helm_render):
    """A BYO render must pass helm template — catches the otel/signoz
    coupling regression where the chart validator rejects otel-on with
    no endpoint configured."""
    _, helm_stdout = byo_helm_render
    # If we got here, helm template succeeded (fixture used check=True).
    # The signoz collector services prove the otel endpoint is reachable.
    assert "kind: Service" in helm_stdout and "otel-collector" in helm_stdout


def test_byo_render_routes_signoz_images_through_registry(byo_helm_render):
    """Every signoz subchart image must resolve under the BYO registry."""
    _, helm_stdout = byo_helm_render
    image_lines = [
        line.strip()
        for line in helm_stdout.splitlines()
        if re.match(r"^\s*image:\s*['\"]?\S", line)
    ]
    assert image_lines, "helm template produced no image lines: " + helm_stdout[:600]
    # The sqlcl image used by the database init job is intentionally pulled
    # from the Oracle Container Registry and is outside the BYO surface.
    out_of_scope = ("container-registry.oracle.com/database/sqlcl",)
    offenders = [
        line for line in image_lines
        if not any(skip in line for skip in out_of_scope)
        and ("docker.io" in line or (BYO_URL not in line and "localhost/" not in line))
    ]
    assert not offenders, (
        "Some images are not routed through the BYO registry:\n  "
        + "\n  ".join(offenders)
    )


def test_byo_render_makes_no_outbound_internet_calls(byo_helm_render):
    """Private-registry contract: no `wget`/`curl` to public hosts in
    container commands. The clickhouse `udf` initContainer downloads
    histogram-quantile from github.com at pod start; the BYO branch must
    keep it disabled.
    Comment lines (XML <!--, YAML #, // ) are skipped because rendered
    ConfigMap data legitimately contains inert source-doc URLs (e.g.
    github.com/pocoproject/poco)."""
    _, helm_stdout = byo_helm_render
    offenders: list[str] = []
    for i, line in enumerate(helm_stdout.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("<!--", "#", "//")):
            continue
        if any(
            not _INTERNAL_HOST_RE.match(host) for host in _FETCH_RE.findall(line)
        ):
            offenders.append(f"line {i}: {stripped}")
    assert not offenders, (
        "BYO render still includes external runtime downloads. Disable or "
        "override the responsible subchart values:\n  "
        + "\n  ".join(offenders[:10])
    )
    assert "histogram-quantile" not in helm_stdout, (
        "clickhouse.initContainers.udf is still rendering under BYO; the "
        "optimizer template should set signoz.clickhouse.initContainers.udf"
        ".enabled=false so the install does not depend on runtime downloads."
    )
