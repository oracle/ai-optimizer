"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract tests for opentofu/cfgmgt/apply.py: subchart dependency resolution
must not surface scary stderr to operators on fresh hosts.
"""
# spell-checker: disable

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
APPLY_PY = REPO_ROOT / "opentofu" / "cfgmgt" / "apply.py"
CHART_DIR = REPO_ROOT / "helm"

helm_bin = shutil.which("helm")
pytestmark = pytest.mark.skipif(
    helm_bin is None or not APPLY_PY.exists() or not CHART_DIR.exists(),
    reason="helm binary or repo paths not available",
)


def _load_apply():
    """Import apply.py as a module without executing its CLI entry point."""
    spec = importlib.util.spec_from_file_location("cfgmgt_apply", APPLY_PY)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {APPLY_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _isolated_helm_env(tmp_path: Path) -> dict[str, str]:
    """Return an env dict with helm pointed at empty config/data/cache dirs.
    Mirrors a fresh CI runner / fresh operator host where no helm repos
    have been registered yet."""
    env = os.environ.copy()
    for sub, var in (
        ("config", "HELM_CONFIG_HOME"),
        ("data", "HELM_DATA_HOME"),
        ("cache", "HELM_CACHE_HOME"),
    ):
        d = tmp_path / sub
        d.mkdir()
        env[var] = str(d)
    return env


def test_helm_resolve_dependencies_clean_config_quiet(tmp_path, monkeypatch, capsys):
    """On a fresh helm config (no SigNoz repo registered), apply.py's
    helm_resolve_dependencies must not surface a `helm dependency build
    failed, retrying with update` warning. Operators reading install
    logs would interpret it as something being wrong."""
    apply = _load_apply()

    # Stage a minimal chart with only the files dep resolution touches.
    # Chart.lock IS copied — that's what makes `helm dependency build` strict
    # about looking up the repo by URL in `helm repo list`. Without the lock,
    # build auto-resolves "unmanaged" repositories from Chart.yaml directly,
    # so the pre-registration concern would not fire.
    staging = tmp_path / "chart"
    staging.mkdir()
    for f in ("Chart.yaml", "Chart.lock"):
        shutil.copy2(CHART_DIR / f, staging / f)

    env = _isolated_helm_env(tmp_path)

    def env_run_cmd(cmd, capture_output=True):
        result = subprocess.run(
            cmd, env=env, capture_output=capture_output, text=True, check=False
        )
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""
        return stdout, stderr, result.returncode

    monkeypatch.setattr(apply, "run_cmd", env_run_cmd)

    ok = apply.helm_resolve_dependencies(str(staging))
    out = capsys.readouterr().out

    assert ok, f"helper should succeed on clean config; printed: {out}"
    assert "helm dependency build failed" not in out, (
        "helper hit the 'build then fall back to update' path on a clean helm "
        "config. Operators see this scary warning every install on fresh hosts. "
        f"Captured output:\n{out}"
    )
