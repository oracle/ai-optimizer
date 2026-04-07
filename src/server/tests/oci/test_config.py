"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.oci.config.
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

from server.app.oci.config import _check_usable, _get_config_file_path, _profile_from_section, parse_oci_config_file
from server.app.oci.schemas import OciProfileConfig

MODULE = "server.app.oci.config"


# ---------------------------------------------------------------------------
# _get_config_file_path
# ---------------------------------------------------------------------------


class TestGetConfigFilePath:
    """Test _get_config_file_path env-var handling."""

    def test_returns_env_var_when_set(self, monkeypatch):
        """Returns OCI_CLI_CONFIG_FILE when set."""
        monkeypatch.setenv("OCI_CLI_CONFIG_FILE", "/custom/oci/config")
        assert _get_config_file_path() == "/custom/oci/config"

    def test_returns_sdk_default_when_env_unset(self, monkeypatch):
        """Returns SDK default when env var not set."""
        monkeypatch.delenv("OCI_CLI_CONFIG_FILE", raising=False)
        import oci.config

        assert _get_config_file_path() == oci.config.DEFAULT_LOCATION


# ---------------------------------------------------------------------------
# _profile_from_section
# ---------------------------------------------------------------------------


class TestProfileFromSection:
    """Test _profile_from_section builds OciProfileConfig from raw section."""

    def test_builds_profile_from_complete_section(self):
        """Complete section dict produces a valid OciProfileConfig."""
        section = {
            "user": "ocid1.user.oc1..test",
            "authentication": "api_key",
            "fingerprint": "aa:bb:cc",
            "tenancy": "ocid1.tenancy.oc1..test",
            "key_file": "/home/user/.oci/key.pem",
            "region": "us-phoenix-1",
            "security_token_file": None,
            "pass_phrase": None,
            "genai_compartment_id": "ocid1.compartment.oc1..genai",
            "genai_region": "us-chicago-1",
        }
        profile = _profile_from_section("TEST", section)
        assert profile.auth_profile == "TEST"
        assert profile.user == "ocid1.user.oc1..test"
        assert profile.tenancy == "ocid1.tenancy.oc1..test"
        assert profile.region == "us-phoenix-1"

    def test_expands_key_file_path(self):
        """key_file with ~ is expanded."""
        section = {"key_file": "~/.oci/key.pem"}
        profile = _profile_from_section("TEST", section)
        assert profile.key_file is not None
        assert not profile.key_file.startswith("~")

    def test_key_content_is_none_when_key_file_present(self):
        """key_content is set to None when key_file is present."""
        section = {"key_file": "/path/to/key", "key_content": "raw-key-data"}
        profile = _profile_from_section("TEST", section)
        assert profile.key_content is None
        assert profile.key_file == "/path/to/key"


# ---------------------------------------------------------------------------
# _check_usable
# ---------------------------------------------------------------------------


class TestCheckUsable:
    """Test _check_usable connectivity check."""

    def test_success_sets_usable_true_and_namespace(self):
        """Successful connectivity sets usable=True and namespace."""
        profile = OciProfileConfig(auth_profile="TEST")
        mock_client = MagicMock()
        mock_client.get_namespace.return_value.data = "test-namespace"

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = _check_usable(profile)

        assert result is None
        assert profile.usable is True
        assert profile.namespace == "test-namespace"

    def test_failure_sets_usable_false_and_returns_error(self):
        """Failed connectivity sets usable=False and returns error string."""
        profile = OciProfileConfig(auth_profile="TEST")

        with patch(f"{MODULE}.init_client", side_effect=Exception("auth failed")):
            result = _check_usable(profile)

        assert result == "auth failed"
        assert profile.usable is False


# ---------------------------------------------------------------------------
# parse_oci_config_file
# ---------------------------------------------------------------------------


class TestParseOciConfigFile:
    """Test parse_oci_config_file parsing."""

    def test_returns_empty_list_when_file_not_found(self):
        """Returns empty list when config file does not exist."""
        with patch(f"{MODULE}.os.path.isfile", return_value=False):
            result = parse_oci_config_file("/nonexistent/config")

        assert not result

    def test_parses_default_section(self, tmp_path):
        """Parses DEFAULT section from config file."""
        config_file = tmp_path / "config"
        config_file.write_text(
            "[DEFAULT]\n"
            "user=ocid1.user.oc1..default\n"
            "fingerprint=aa:bb:cc\n"
            "tenancy=ocid1.tenancy.oc1..default\n"
            "region=us-phoenix-1\n"
            "key_file=/path/to/key.pem\n"
        )

        result = parse_oci_config_file(str(config_file))
        assert len(result) >= 1
        default_profile = result[0]
        assert default_profile.auth_profile == "DEFAULT"
        assert default_profile.tenancy == "ocid1.tenancy.oc1..default"

    def test_parses_named_sections(self, tmp_path):
        """Parses named sections from config file."""
        config_file = tmp_path / "config"
        config_file.write_text(
            "[DEFAULT]\n"
            "tenancy=ocid1.tenancy.oc1..default\n"
            "\n"
            "[PROD]\n"
            "user=ocid1.user.oc1..prod\n"
            "fingerprint=dd:ee:ff\n"
            "region=us-ashburn-1\n"
            "key_file=/path/to/prod-key.pem\n"
        )

        result = parse_oci_config_file(str(config_file))
        assert len(result) == 2
        prod_profile = next(p for p in result if p.auth_profile == "PROD")
        assert prod_profile.region == "us-ashburn-1"

    def test_skips_malformed_profiles_with_warning(self, tmp_path):
        """Malformed profiles are skipped with a warning log."""
        config_file = tmp_path / "config"
        config_file.write_text("[DEFAULT]\ntenancy=t\n\n[BAD]\n")

        with patch(f"{MODULE}._profile_from_section") as mock_pfs:
            # DEFAULT succeeds, BAD raises
            mock_pfs.side_effect = [
                OciProfileConfig(auth_profile="DEFAULT", tenancy="t"),
                Exception("parse error"),
            ]
            result = parse_oci_config_file(str(config_file))

        assert len(result) == 1
        assert result[0].auth_profile == "DEFAULT"
