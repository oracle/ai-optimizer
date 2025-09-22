"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock

import pytest

from server.api.core import oci
from common.schema import OracleCloudSettings, Settings, OciSettings


class TestOci:
    """Test OCI module functionality"""

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_oci_default = OracleCloudSettings(
            auth_profile="DEFAULT", compartment_id="ocid1.compartment.oc1..default"
        )
        self.sample_oci_custom = OracleCloudSettings(
            auth_profile="CUSTOM", compartment_id="ocid1.compartment.oc1..custom"
        )
        self.sample_client_settings = Settings(client="test_client", oci=OciSettings(auth_profile="CUSTOM"))

    @patch("server.api.core.oci.bootstrap")
    def test_get_oci_all(self, mock_bootstrap):
        """Test getting all OCI settings when no filters are provided"""
        all_oci = [self.sample_oci_default, self.sample_oci_custom]
        mock_bootstrap.OCI_OBJECTS = all_oci

        result = oci.get_oci()

        assert result == all_oci

    @patch("server.api.core.oci.bootstrap.OCI_OBJECTS")
    def test_get_oci_no_objects_configured(self, mock_oci_objects):
        """Test getting OCI settings when none are configured"""
        mock_oci_objects.__bool__ = MagicMock(return_value=False)

        with pytest.raises(ValueError, match="not configured"):
            oci.get_oci()

    @patch("server.api.core.oci.bootstrap.OCI_OBJECTS")
    def test_get_oci_by_auth_profile_found(self, mock_oci_objects):
        """Test getting OCI settings by auth_profile when it exists"""
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default, self.sample_oci_custom]))

        result = oci.get_oci(auth_profile="CUSTOM")

        assert result == self.sample_oci_custom

    @patch("server.api.core.oci.bootstrap.OCI_OBJECTS")
    def test_get_oci_by_auth_profile_not_found(self, mock_oci_objects):
        """Test getting OCI settings by auth_profile when it doesn't exist"""
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default]))

        with pytest.raises(ValueError, match="profile 'NONEXISTENT' not found"):
            oci.get_oci(auth_profile="NONEXISTENT")

    @patch("server.api.core.oci.bootstrap.OCI_OBJECTS")
    @patch("server.api.core.oci.settings.get_client_settings")
    def test_get_oci_by_client_with_oci_settings(self, mock_get_client_settings, mock_oci_objects):
        """Test getting OCI settings by client when client has OCI settings"""
        mock_get_client_settings.return_value = self.sample_client_settings
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default, self.sample_oci_custom]))

        result = oci.get_oci(client="test_client")

        assert result == self.sample_oci_custom

    @patch("server.api.core.oci.bootstrap.OCI_OBJECTS")
    @patch("server.api.core.oci.settings.get_client_settings")
    def test_get_oci_by_client_without_oci_settings(self, mock_get_client_settings, mock_oci_objects):
        """Test getting OCI settings by client when client has no OCI settings"""
        client_settings_no_oci = Settings(client="test_client", oci=None)
        mock_get_client_settings.return_value = client_settings_no_oci
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default]))

        result = oci.get_oci(client="test_client")

        assert result == self.sample_oci_default

    @patch("server.api.core.oci.bootstrap.OCI_OBJECTS")
    @patch("server.api.core.oci.settings.get_client_settings")
    def test_get_oci_by_client_no_matching_profile(self, mock_get_client_settings, mock_oci_objects):
        """Test getting OCI settings by client when no matching profile exists"""
        mock_get_client_settings.return_value = self.sample_client_settings
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default]))  # Only DEFAULT profile

        with pytest.raises(ValueError, match="No settings found for client 'test_client' with auth_profile 'CUSTOM'"):
            oci.get_oci(client="test_client")

    def test_get_oci_both_client_and_auth_profile(self):
        """Test that providing both client and auth_profile raises an error"""
        with pytest.raises(ValueError, match="provide either 'client' or 'auth_profile', not both"):
            oci.get_oci(client="test_client", auth_profile="CUSTOM")

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(oci, "logger")
        assert oci.logger.name == "api.core.oci"
