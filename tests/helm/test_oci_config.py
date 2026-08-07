"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract tests for the release-packaged OCI config Secret helper.
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent.parent / "helm" / "scripts" / "oci_config.py"


def _run_helper(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the helper without loading any installed site packages."""
    return subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_emits_self_contained_secret_manifest(tmp_path: Path):
    key_path = tmp_path / "oci_api_key.pem"
    key_path.write_text("private-key-data", encoding="utf-8")
    config_path = tmp_path / "config"
    config_path.write_text(
        f"[DEFAULT]\ntenancy=ocid1.tenancy.test\nkey_file={key_path}\n",
        encoding="utf-8",
    )

    result = _run_helper(
        "--config",
        str(config_path),
        "--namespace",
        "ai-optimizer",
        "--secret-name",
        "custom-oci-config",
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["metadata"] == {"name": "custom-oci-config", "namespace": "ai-optimizer"}
    assert manifest["type"] == "Opaque"
    config = base64.b64decode(manifest["data"]["config"]).decode()
    assert "key_file=/app/.oci/oci_api_key.pem" in config
    assert base64.b64decode(manifest["data"]["oci_api_key.pem"]) == b"private-key-data"
    assert result.stderr == ""


def test_missing_config_fails_without_manifest(tmp_path: Path):
    result = _run_helper("--config", str(tmp_path / "missing-config"))

    assert result.returncode != 0
    assert "Config file not found" in result.stderr
    assert result.stdout == ""


def test_missing_key_file_fails_without_manifest(tmp_path: Path):
    missing_key = tmp_path / "missing-key.pem"
    config_path = tmp_path / "config"
    config_path.write_text(f"[DEFAULT]\nkey_file={missing_key}\n", encoding="utf-8")

    result = _run_helper("--config", str(config_path))

    assert result.returncode != 0
    assert str(missing_key) in result.stderr
    assert result.stdout == ""


def test_duplicate_key_basenames_fail_without_manifest(tmp_path: Path):
    first_key = tmp_path / "first" / "api_key.pem"
    second_key = tmp_path / "second" / "api_key.pem"
    first_key.parent.mkdir()
    second_key.parent.mkdir()
    first_key.write_text("first-key", encoding="utf-8")
    second_key.write_text("second-key", encoding="utf-8")
    config_path = tmp_path / "config"
    config_path.write_text(
        f"[FIRST]\nkey_file={first_key}\n[SECOND]\nkey_file={second_key}\n",
        encoding="utf-8",
    )

    result = _run_helper("--config", str(config_path))

    assert result.returncode != 0
    assert "same filename" in result.stderr
    assert "api_key.pem" in result.stderr
    assert result.stdout == ""


def test_key_named_config_fails_without_overwriting_config(tmp_path: Path):
    key_path = tmp_path / "config"
    key_path.write_text("private-key", encoding="utf-8")
    oci_config_path = tmp_path / "oci-config"
    oci_config_path.write_text(f"[DEFAULT]\nkey_file={key_path}\n", encoding="utf-8")

    result = _run_helper("--config", str(oci_config_path))

    assert result.returncode != 0
    assert "reserved Secret data key" in result.stderr
    assert "config" in result.stderr
    assert result.stdout == ""
