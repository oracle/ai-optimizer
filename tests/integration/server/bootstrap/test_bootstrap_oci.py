"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/bootstrap/oci.py

Tests the OCI bootstrap process with real configuration files
and environment variables.
"""

# pylint: disable=redefined-outer-name

import os

import oci
import pytest

from server.bootstrap import oci as oci_module
from common.schema import OracleCloudSettings


@pytest.mark.usefixtures("reset_config_store", "clean_bootstrap_env")
class TestOciBootstrapWithEnvVars:
    """Integration tests for OCI bootstrap with environment variables."""

    def test_bootstrap_returns_oci_settings_objects(self):
        """oci.main() should return list of OracleCloudSettings objects."""
        # Point to nonexistent OCI config to test env var path
        os.environ["OCI_CLI_CONFIG_FILE"] = "/nonexistent/oci/config"

        try:
            result = oci_module.main()

            assert isinstance(result, list)
            assert all(isinstance(s, OracleCloudSettings) for s in result)
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]

    def test_bootstrap_creates_default_profile(self):
        """oci.main() should always create DEFAULT profile."""
        os.environ["OCI_CLI_CONFIG_FILE"] = "/nonexistent/oci/config"

        try:
            result = oci_module.main()

            profile_names = [s.auth_profile for s in result]
            assert oci.config.DEFAULT_PROFILE in profile_names
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]

    def test_bootstrap_applies_tenancy_env_var(self):
        """oci.main() should apply OCI_CLI_TENANCY to DEFAULT profile."""
        os.environ["OCI_CLI_CONFIG_FILE"] = "/nonexistent/oci/config"
        os.environ["OCI_CLI_TENANCY"] = "ocid1.tenancy.oc1..envtenancy"

        try:
            result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.tenancy == "ocid1.tenancy.oc1..envtenancy"
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]
            del os.environ["OCI_CLI_TENANCY"]

    def test_bootstrap_applies_region_env_var(self):
        """oci.main() should apply OCI_CLI_REGION to DEFAULT profile."""
        os.environ["OCI_CLI_CONFIG_FILE"] = "/nonexistent/oci/config"
        os.environ["OCI_CLI_REGION"] = "us-chicago-1"

        try:
            result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.region == "us-chicago-1"
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]
            del os.environ["OCI_CLI_REGION"]

    def test_bootstrap_applies_genai_env_vars(self):
        """oci.main() should apply GenAI environment variables."""
        os.environ["OCI_CLI_CONFIG_FILE"] = "/nonexistent/oci/config"
        os.environ["OCI_GENAI_COMPARTMENT_ID"] = "ocid1.compartment.oc1..genaicomp"
        os.environ["OCI_GENAI_REGION"] = "us-chicago-1"

        try:
            result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.genai_compartment_id == "ocid1.compartment.oc1..genaicomp"
            assert default_profile.genai_region == "us-chicago-1"
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]
            del os.environ["OCI_GENAI_COMPARTMENT_ID"]
            del os.environ["OCI_GENAI_REGION"]

    def test_bootstrap_explicit_auth_method(self):
        """oci.main() should use OCI_CLI_AUTH when specified."""
        os.environ["OCI_CLI_CONFIG_FILE"] = "/nonexistent/oci/config"
        os.environ["OCI_CLI_AUTH"] = "instance_principal"

        try:
            result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.authentication == "instance_principal"
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]
            del os.environ["OCI_CLI_AUTH"]

    def test_bootstrap_default_auth_is_api_key(self):
        """oci.main() should default to api_key authentication."""
        os.environ["OCI_CLI_CONFIG_FILE"] = "/nonexistent/oci/config"

        try:
            result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            assert default_profile.authentication == "api_key"
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]


@pytest.mark.usefixtures("reset_config_store", "clean_bootstrap_env")
class TestOciBootstrapWithConfigFile:
    """Integration tests for OCI bootstrap with real OCI config files."""

    def test_bootstrap_reads_oci_config_file(self, make_oci_config_file):
        """oci.main() should read profiles from OCI config file."""
        config_path = make_oci_config_file(
            profiles={
                "DEFAULT": {
                    "tenancy": "ocid1.tenancy.oc1..filetenancy",
                    "region": "us-ashburn-1",
                    "fingerprint": "file:fingerprint",
                },
            }
        )

        os.environ["OCI_CLI_CONFIG_FILE"] = str(config_path)

        try:
            result = oci_module.main()

            # Should have loaded the profile from file
            profile_names = [s.auth_profile for s in result]
            assert "DEFAULT" in profile_names
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]

    def test_bootstrap_loads_multiple_profiles(self, make_oci_config_file):
        """oci.main() should load multiple profiles from OCI config file."""
        config_path = make_oci_config_file(
            profiles={
                "DEFAULT": {
                    "tenancy": "ocid1.tenancy.oc1..default",
                    "region": "us-ashburn-1",
                    "fingerprint": "default:fp",
                },
                "PRODUCTION": {
                    "tenancy": "ocid1.tenancy.oc1..production",
                    "region": "us-phoenix-1",
                    "fingerprint": "prod:fp",
                },
            }
        )

        os.environ["OCI_CLI_CONFIG_FILE"] = str(config_path)

        try:
            result = oci_module.main()

            profile_names = [s.auth_profile for s in result]
            assert "DEFAULT" in profile_names
            assert "PRODUCTION" in profile_names
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]


@pytest.mark.usefixtures("clean_bootstrap_env")
class TestOciBootstrapWithConfigStore:
    """Integration tests for OCI bootstrap with ConfigStore configuration."""

    def test_bootstrap_merges_config_store_profiles(self, reset_config_store, make_config_file):
        """oci.main() should merge profiles from ConfigStore."""
        os.environ["OCI_CLI_CONFIG_FILE"] = "/nonexistent/oci/config"

        config_path = make_config_file(
            oci_configs=[
                {
                    "auth_profile": "CONFIGSTORE_PROFILE",
                    "tenancy": "ocid1.tenancy.oc1..configstore",
                    "region": "us-sanjose-1",
                    "fingerprint": "cs:fingerprint",
                },
            ],
        )

        try:
            reset_config_store.load_from_file(config_path)
            result = oci_module.main()

            profile_names = [s.auth_profile for s in result]
            assert "CONFIGSTORE_PROFILE" in profile_names

            cs_profile = next(p for p in result if p.auth_profile == "CONFIGSTORE_PROFILE")
            assert cs_profile.tenancy == "ocid1.tenancy.oc1..configstore"
            assert cs_profile.region == "us-sanjose-1"
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]

    def test_bootstrap_config_store_overrides_file_profile(
        self, reset_config_store, make_config_file, make_oci_config_file
    ):
        """oci.main() should let ConfigStore override file profiles."""
        oci_config_path = make_oci_config_file(
            profiles={
                "DEFAULT": {
                    "tenancy": "ocid1.tenancy.oc1..fromfile",
                    "region": "us-ashburn-1",
                    "fingerprint": "file:fp",
                },
            }
        )

        config_path = make_config_file(
            oci_configs=[
                {
                    "auth_profile": "DEFAULT",
                    "tenancy": "ocid1.tenancy.oc1..fromconfigstore",
                    "region": "us-phoenix-1",
                    "fingerprint": "cs:fp",
                },
            ],
        )

        os.environ["OCI_CLI_CONFIG_FILE"] = str(oci_config_path)

        try:
            reset_config_store.load_from_file(config_path)
            result = oci_module.main()

            default_profile = next(p for p in result if p.auth_profile == oci.config.DEFAULT_PROFILE)
            # ConfigStore should override file values
            assert default_profile.tenancy == "ocid1.tenancy.oc1..fromconfigstore"
        finally:
            del os.environ["OCI_CLI_CONFIG_FILE"]
