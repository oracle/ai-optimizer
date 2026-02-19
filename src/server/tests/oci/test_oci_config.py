"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for OCI config file parsing.
"""
# spell-checker: disable
# pylint: disable=import-outside-toplevel

from unittest.mock import patch


from server.app.oci.config import (
    _get_config_file_path,
    _read_key_file,
    parse_oci_config_file,
)


class TestGetConfigFilePath:
    """_get_config_file_path uses env var or SDK default."""

    def test_uses_env_var(self, monkeypatch):
        """OCI_CLI_CONFIG_FILE env var overrides the default."""
        monkeypatch.setenv("OCI_CLI_CONFIG_FILE", "/custom/path")
        assert _get_config_file_path() == "/custom/path"

    def test_uses_default_when_no_env(self, monkeypatch):
        """Falls back to oci.config.DEFAULT_LOCATION."""
        monkeypatch.delenv("OCI_CLI_CONFIG_FILE", raising=False)
        import oci.config

        assert _get_config_file_path() == oci.config.DEFAULT_LOCATION


class TestReadKeyFile:
    """_read_key_file reads PEM contents or returns None."""

    def test_reads_file_contents(self, tmp_path):
        """Reads and returns PEM file contents."""
        key_file = tmp_path / "key.pem"
        key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n")
        result = _read_key_file(str(key_file))
        assert "BEGIN RSA PRIVATE KEY" in result

    def test_returns_none_for_missing_file(self):
        """Returns None when the file does not exist."""
        result = _read_key_file("/nonexistent/key.pem")
        assert result is None

    def test_returns_none_for_none(self):
        """Returns None when path is None."""
        result = _read_key_file(None)
        assert result is None

    def test_expands_home_dir(self, tmp_path, monkeypatch):
        """Tilde in path is expanded to HOME."""
        key_file = tmp_path / "key.pem"
        key_file.write_text("key-contents")
        monkeypatch.setenv("HOME", str(tmp_path))
        result = _read_key_file("~/key.pem")
        assert result == "key-contents"


class TestParseOCIConfigFile:
    """parse_oci_config_file parses all profiles from an OCI config file."""

    def test_returns_empty_for_missing_file(self):
        """Returns empty list when config file does not exist."""
        result = parse_oci_config_file("/nonexistent/config")
        assert not result

    def test_parses_default_and_named_profiles(self, tmp_path):
        """DEFAULT and named sections are both parsed with key_file read."""
        config_file = tmp_path / "config"
        key_file = tmp_path / "key.pem"
        key_file.write_text("pem-contents")

        config_file.write_text(
            f"[DEFAULT]\n"
            f"user=ocid1.user.oc1..default\n"
            f"fingerprint=aa:bb:cc\n"
            f"tenancy=ocid1.tenancy.oc1..default\n"
            f"region=us-ashburn-1\n"
            f"key_file={key_file}\n"
            f"\n"
            f"[PHOENIX]\n"
            f"region=us-phoenix-1\n"
        )

        with patch("oci.config.from_file") as mock_from_file:
            mock_from_file.side_effect = [
                {
                    "user": "ocid1.user.oc1..default",
                    "fingerprint": "aa:bb:cc",
                    "tenancy": "ocid1.tenancy.oc1..default",
                    "region": "us-ashburn-1",
                    "key_file": str(key_file),
                },
                {
                    "user": "ocid1.user.oc1..default",
                    "fingerprint": "aa:bb:cc",
                    "tenancy": "ocid1.tenancy.oc1..default",
                    "region": "us-phoenix-1",
                    "key_file": str(key_file),
                },
            ]

            results = parse_oci_config_file(str(config_file))

        assert len(results) == 2
        assert results[0].auth_profile == "DEFAULT"
        assert results[0].region == "us-ashburn-1"
        assert results[0].auth.key == "pem-contents"
        assert results[1].auth_profile == "PHOENIX"
        assert results[1].region == "us-phoenix-1"

    def test_skips_failing_profiles(self, tmp_path):
        """Profiles that raise during parsing are skipped."""
        config_file = tmp_path / "config"
        config_file.write_text("[DEFAULT]\nuser=test\n\n[BAD]\nuser=bad\n")

        with patch("oci.config.from_file") as mock_from_file:
            mock_from_file.side_effect = [
                {"user": "test", "region": "us-ashburn-1"},
                ValueError("parse error"),
            ]

            results = parse_oci_config_file(str(config_file))

        assert len(results) == 1
        assert results[0].auth_profile == "DEFAULT"

    def test_security_token_authentication(self, tmp_path):
        """security_token authentication type is captured."""
        config_file = tmp_path / "config"
        config_file.write_text("[DEFAULT]\nauthentication=security_token\n")

        with patch("oci.config.from_file") as mock_from_file:
            mock_from_file.return_value = {
                "authentication": "security_token",
                "security_token_file": "/path/to/token",
                "region": "us-ashburn-1",
            }

            results = parse_oci_config_file(str(config_file))

        assert len(results) == 1
        assert results[0].auth.authentication == "security_token"
        assert results[0].auth.security_token_file == "/path/to/token"
