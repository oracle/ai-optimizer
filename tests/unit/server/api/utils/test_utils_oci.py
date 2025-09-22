"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock

import pytest
import oci

from server.api.utils import oci as oci_utils
from server.api.utils.oci import OciException
from common.schema import OracleCloudSettings


class TestOciException:
    """Test custom OCI exception class"""

    def test_oci_exception_initialization(self):
        """Test OciException initialization"""
        exc = OciException(status_code=400, detail="Invalid configuration")
        assert exc.status_code == 400
        assert exc.detail == "Invalid configuration"
        assert str(exc) == "Invalid configuration"


class TestOciUtils:
    """Test OCI utility functions"""

    def setup_method(self):
        """Setup test data"""
        self.sample_oci_config = OracleCloudSettings(
            auth_profile="DEFAULT",
            compartment_id="ocid1.compartment.oc1..test",
            genai_region="us-ashburn-1",
            user="ocid1.user.oc1..testuser",
            fingerprint="test-fingerprint",
            tenancy="ocid1.tenancy.oc1..testtenant",
            key_file="/path/to/key.pem",
        )

    def test_init_genai_client(self):
        """Test GenAI client initialization"""
        with patch.object(oci_utils, "init_client") as mock_init_client:
            mock_client = MagicMock()
            mock_init_client.return_value = mock_client

            result = oci_utils.init_genai_client(self.sample_oci_config)

            assert result == mock_client
            mock_init_client.assert_called_once_with(
                oci.generative_ai_inference.GenerativeAiInferenceClient, self.sample_oci_config
            )

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_success(self, mock_init_client):
        """Test successful namespace retrieval"""
        mock_client = MagicMock()
        mock_client.get_namespace.return_value.data = "test-namespace"
        mock_init_client.return_value = mock_client

        result = oci_utils.get_namespace(self.sample_oci_config)

        assert result == "test-namespace"
        assert self.sample_oci_config.namespace == "test-namespace"

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_invalid_config(self, mock_init_client):
        """Test namespace retrieval with invalid config"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = oci.exceptions.InvalidConfig("Invalid config")
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(self.sample_oci_config)

        assert exc_info.value.status_code == 400
        assert "Invalid Config" in str(exc_info.value)

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_file_not_found(self, mock_init_client):
        """Test namespace retrieval with file not found error"""
        mock_init_client.side_effect = FileNotFoundError("Key file not found")

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(self.sample_oci_config)

        assert exc_info.value.status_code == 400
        assert "Invalid Key Path" in str(exc_info.value)

    @patch.object(oci_utils, "init_client")
    def test_get_regions_success(self, mock_init_client):
        """Test successful regions retrieval"""
        mock_client = MagicMock()
        mock_region = MagicMock()
        mock_region.is_home_region = True
        mock_region.region_key = "IAD"
        mock_region.region_name = "us-ashburn-1"
        mock_region.status = "READY"
        mock_client.list_region_subscriptions.return_value.data = [mock_region]
        mock_init_client.return_value = mock_client

        result = oci_utils.get_regions(self.sample_oci_config)

        assert len(result) == 1
        assert result[0]["is_home_region"] is True
        assert result[0]["region_key"] == "IAD"
        assert result[0]["region_name"] == "us-ashburn-1"
        assert result[0]["status"] == "READY"

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(oci_utils, "logger")
        assert oci_utils.logger.name == "api.utils.oci"
