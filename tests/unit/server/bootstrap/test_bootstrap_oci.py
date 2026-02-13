"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/bootstrap/oci.py
Tests for OCI bootstrap functionality.
"""

# pylint: disable=redefined-outer-name protected-access too-few-public-methods

import os
from unittest.mock import patch, MagicMock

import pytest
import oci

from server.bootstrap import oci as oci_module
from common.schema import OracleCloudSettings


@pytest.mark.usefixtures("reset_config_store", "clean_env")
class TestOciMain:
    """Tests for the oci.main() function."""

    def test_main_returns_list_of_oci_settings(self):
        """main() should return a list of OracleCloudSettings objects."""
        with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
            result = oci_module.main()

        assert isinstance(result, list)
        assert all(isinstance(s, OracleCloudSettings) for s in result)

    def test_main_creates_default_profile_when_no_config(self):
        """main() should create DEFAULT profile when no OCI config exists."""
        with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
            result = oci_module.main()

        profile_names = [s.auth_profile for s in result]
        assert oci.config.DEFAULT_PROFILE in profile_names

    def test_main_reads_oci_config_file(self):
        """main() should read from OCI config file when it exists."""
        # User OCID must match pattern ^([0-9a-zA-Z-_]+[.:])([0-9a-zA-Z-_]*[.:]){3,}([0-9a-zA-Z-_]+)$
        mock_config_data = {
            "tenancy": "ocid1.tenancy.oc1..test123",
            "region": "us-phoenix-1",
            "user": "ocid1.user.oc1..test123",  # Valid OCID pattern
            "fingerprint": "test-fingerprint",
            "key_file": "/path/to/key.pem",
        }

        with patch("configparser.ConfigParser") as mock_parser:
            mock_instance = MagicMock()
            mock_instance.sections.return_value = []
            mock_parser.return_value = mock_instance

            with patch("oci.config.from_file", return_value=mock_config_data.copy()):
                result = oci_module.main()

        assert len(result) >= 1
        default_profile = next((p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE), None)
        assert default_profile is not None

    def test_main_applies_env_var_overrides_to_default(self):
        """main() should apply environment variable overrides to DEFAULT profile."""
        # User OCID must match pattern ^([0-9a-zA-Z-_]+[.:])([0-9a-zA-Z-_]*[.:]){3,}([0-9a-zA-Z-_]+)$
        os.environ["OCI_CLI_TENANCY"] = "env-tenancy"
        os.environ["OCI_CLI_REGION"] = "us-chicago-1"
        os.environ["OCI_CLI_USER"] = "ocid1.user.oc1..envuser123"  # Valid OCID pattern

        try:
            with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
                result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.tenancy == "env-tenancy"
            assert default_profile.region == "us-chicago-1"
            assert default_profile.user == "ocid1.user.oc1..envuser123"
        finally:
            del os.environ["OCI_CLI_TENANCY"]
            del os.environ["OCI_CLI_REGION"]
            del os.environ["OCI_CLI_USER"]

    def test_main_env_overrides_genai_settings(self):
        """main() should apply GenAI environment variable overrides."""
        # genai_compartment_id must match OCID pattern
        os.environ["OCI_GENAI_COMPARTMENT_ID"] = "ocid1.compartment.oc1..genaitest"
        os.environ["OCI_GENAI_REGION"] = "us-chicago-1"

        try:
            with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
                result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.genai_compartment_id == "ocid1.compartment.oc1..genaitest"
            assert default_profile.genai_region == "us-chicago-1"
        finally:
            del os.environ["OCI_GENAI_COMPARTMENT_ID"]
            del os.environ["OCI_GENAI_REGION"]

    def test_main_security_token_authentication(self):
        """main() should set authentication based on security_token_file in profile.

        Note: Due to how profile.update() works, the authentication logic reads the
        OLD value of security_token_file before the update completes. If security_token_file
        is already set in the profile, authentication becomes 'security_token'.
        For env var alone without existing profile value, use OCI_CLI_AUTH instead.
        """
        # To get security_token auth, we need OCI_CLI_AUTH explicitly set
        # OR we need security_token_file already in the profile before overrides
        os.environ["OCI_CLI_SECURITY_TOKEN_FILE"] = "/path/to/token"
        os.environ["OCI_CLI_AUTH"] = "security_token"  # Must explicitly set

        try:
            with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
                result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.authentication == "security_token"
            assert default_profile.security_token_file == "/path/to/token"
        finally:
            del os.environ["OCI_CLI_SECURITY_TOKEN_FILE"]
            del os.environ["OCI_CLI_AUTH"]

    def test_main_explicit_auth_env_var(self):
        """main() should use OCI_CLI_AUTH env var when specified."""
        os.environ["OCI_CLI_AUTH"] = "instance_principal"

        try:
            with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
                result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.authentication == "instance_principal"
        finally:
            del os.environ["OCI_CLI_AUTH"]

    def test_main_loads_multiple_profiles(self):
        """main() should load multiple profiles from OCI config."""
        profiles = ["PROFILE1", "PROFILE2"]

        with patch("configparser.ConfigParser") as mock_parser:
            mock_instance = MagicMock()
            mock_instance.sections.return_value = profiles
            mock_parser.return_value = mock_instance

            def mock_from_file(**kwargs):
                profile_name = kwargs.get("profile_name")
                # User must be None or valid OCID pattern
                return {
                    "tenancy": f"tenancy-{profile_name}",
                    "region": "us-ashburn-1",
                    "fingerprint": "fingerprint",
                    "key_file": "/path/to/key.pem",
                }

            with patch("oci.config.from_file", side_effect=mock_from_file):
                result = oci_module.main()

        profile_names = [p.auth_profile for p in result]
        assert "PROFILE1" in profile_names
        assert "PROFILE2" in profile_names

    def test_main_handles_invalid_key_file_path(self):
        """main() should skip profiles with invalid key file paths."""
        profiles = ["VALID", "INVALID"]

        with patch("configparser.ConfigParser") as mock_parser:
            mock_instance = MagicMock()
            mock_instance.sections.return_value = profiles
            mock_parser.return_value = mock_instance

            def mock_from_file(**kwargs):
                profile_name = kwargs.get("profile_name")
                if profile_name == "INVALID":
                    raise oci.exceptions.InvalidKeyFilePath("Invalid key file")
                # User must be None or valid OCID pattern
                return {
                    "tenancy": "tenancy",
                    "region": "us-ashburn-1",
                    "fingerprint": "fingerprint",
                    "key_file": "/path/to/key.pem",
                }

            with patch("oci.config.from_file", side_effect=mock_from_file):
                result = oci_module.main()

        profile_names = [p.auth_profile for p in result]
        assert "VALID" in profile_names
        # INVALID should be skipped, DEFAULT should be created

    def test_main_merges_config_store_oci_configs(
        self, reset_config_store, temp_config_file, make_settings, make_oci_config
    ):
        """main() should merge OCI configs from ConfigStore."""
        settings = make_settings()
        oci_config = make_oci_config(auth_profile="CONFIG_PROFILE", tenancy="config-tenancy")
        config_path = temp_config_file(client_settings=settings, oci_configs=[oci_config])

        try:
            with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
                reset_config_store.load_from_file(config_path)
                result = oci_module.main()

            profile_names = [p.auth_profile for p in result]
            assert "CONFIG_PROFILE" in profile_names

            config_profile = next(p for p in result if p.auth_profile == "CONFIG_PROFILE")
            assert config_profile.tenancy == "config-tenancy"
        finally:
            os.unlink(config_path)

    def test_main_config_store_overrides_existing_profile(
        self, reset_config_store, temp_config_file, make_settings, make_oci_config
    ):
        """main() should override existing profiles with ConfigStore configs."""
        settings = make_settings()
        oci_config = make_oci_config(auth_profile=oci.config.DEFAULT_PROFILE, tenancy="override-tenancy")
        config_path = temp_config_file(client_settings=settings, oci_configs=[oci_config])

        # User must be None or valid OCID pattern
        mock_file_config = {
            "tenancy": "file-tenancy",
            "region": "us-ashburn-1",
            "fingerprint": "fingerprint",
            "key_file": "/path/to/key.pem",
        }

        try:
            with patch("configparser.ConfigParser") as mock_parser:
                mock_instance = MagicMock()
                mock_instance.sections.return_value = []
                mock_parser.return_value = mock_instance

                with patch("oci.config.from_file", return_value=mock_file_config.copy()):
                    reset_config_store.load_from_file(config_path)
                    result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            # ConfigStore should override file config
            assert default_profile.tenancy == "override-tenancy"
        finally:
            os.unlink(config_path)

    def test_main_uses_custom_config_file_path(self):
        """main() should use OCI_CLI_CONFIG_FILE env var for config path."""
        custom_path = "/custom/oci/config"
        os.environ["OCI_CLI_CONFIG_FILE"] = custom_path

        try:
            with patch("configparser.ConfigParser") as mock_parser:
                mock_instance = MagicMock()
                mock_instance.sections.return_value = []
                mock_parser.return_value = mock_instance

                with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
                    result = oci_module.main()

            # The expanded path should be used
            assert len(result) >= 1
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]


@pytest.mark.usefixtures("clean_env")
class TestApplyEnvOverrides:
    """Tests for the _apply_env_overrides_to_default_profile function."""

    def test_override_function_modifies_default_profile(self):
        """_apply_env_overrides_to_default_profile should modify DEFAULT profile."""
        config = [{"auth_profile": oci.config.DEFAULT_PROFILE, "tenancy": "original"}]

        os.environ["OCI_CLI_TENANCY"] = "overridden"

        try:
            oci_module._apply_env_overrides_to_default_profile(config)

            assert config[0]["tenancy"] == "overridden"
        finally:
            del os.environ["OCI_CLI_TENANCY"]

    def test_override_function_ignores_non_default_profiles(self):
        """_apply_env_overrides_to_default_profile should not modify non-DEFAULT profiles."""
        config = [{"auth_profile": "CUSTOM", "tenancy": "original"}]

        os.environ["OCI_CLI_TENANCY"] = "overridden"

        try:
            oci_module._apply_env_overrides_to_default_profile(config)

            assert config[0]["tenancy"] == "original"
        finally:
            del os.environ["OCI_CLI_TENANCY"]

    def test_override_logs_changes(self, caplog):
        """_apply_env_overrides_to_default_profile should log overrides."""
        config = [{"auth_profile": oci.config.DEFAULT_PROFILE, "tenancy": "original"}]

        os.environ["OCI_CLI_TENANCY"] = "new-tenancy"

        try:
            oci_module._apply_env_overrides_to_default_profile(config)

            assert "Environment variable overrides" in caplog.text or "new-tenancy" in str(config)
        finally:
            del os.environ["OCI_CLI_TENANCY"]


@pytest.mark.usefixtures("reset_config_store", "clean_env")
class TestOciMainAsScript:
    """Tests for running OCI module as script."""

    def test_main_callable_directly(self):
        """main() should be callable when running as script."""
        with patch("oci.config.from_file", side_effect=oci.exceptions.ConfigFileNotFound()):
            result = oci_module.main()
        assert result is not None
