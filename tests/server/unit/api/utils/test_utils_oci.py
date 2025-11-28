"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access import-error import-outside-toplevel

from unittest.mock import patch, MagicMock

import pytest
import oci

from conftest import get_sample_oci_config
from server.api.utils import oci as oci_utils
from server.api.utils.oci import OciException
from common.schema import OracleCloudSettings, Settings, OciSettings


class TestOciException:
    """Test custom OCI exception class"""

    # test_oci_exception_initialization: See test/unit/server/api/utils/test_utils_oci.py::TestOciException::test_oci_exception_init


class TestOciGet:
    """Test OCI get() function"""

    @pytest.fixture
    def sample_oci_default(self):
        """Sample OCI config with DEFAULT profile"""
        return OracleCloudSettings(
            auth_profile="DEFAULT", compartment_id="ocid1.compartment.oc1..default"
        )

    @pytest.fixture
    def sample_oci_custom(self):
        """Sample OCI config with CUSTOM profile"""
        return OracleCloudSettings(
            auth_profile="CUSTOM", compartment_id="ocid1.compartment.oc1..custom"
        )

    @pytest.fixture
    def sample_client_settings(self):
        """Sample client settings fixture"""
        return Settings(client="test_client", oci=OciSettings(auth_profile="CUSTOM"))

    # test_get_no_objects_configured: See test/unit/server/api/utils/test_utils_oci.py::TestGet::test_get_raises_value_error_when_not_configured
    # test_get_all: See test/unit/server/api/utils/test_utils_oci.py::TestGet::test_get_returns_all_oci_objects
    # test_get_by_auth_profile_found: See test/unit/server/api/utils/test_utils_oci.py::TestGet::test_get_by_auth_profile
    # test_get_by_auth_profile_not_found: See test/unit/server/api/utils/test_utils_oci.py::TestGet::test_get_raises_value_error_profile_not_found

    def test_get_by_client_with_oci_settings(self, sample_client_settings, sample_oci_default, sample_oci_custom):
        """Test getting OCI settings by client when client has OCI settings"""
        from server.bootstrap import bootstrap

        # Save originals
        orig_settings = bootstrap.SETTINGS_OBJECTS
        orig_oci = bootstrap.OCI_OBJECTS

        try:
            # Replace with test data
            bootstrap.SETTINGS_OBJECTS = [sample_client_settings]
            bootstrap.OCI_OBJECTS = [sample_oci_default, sample_oci_custom]

            result = oci_utils.get(client="test_client")

            assert result == sample_oci_custom
        finally:
            # Restore originals
            bootstrap.SETTINGS_OBJECTS = orig_settings
            bootstrap.OCI_OBJECTS = orig_oci

    def test_get_by_client_without_oci_settings(self, sample_oci_default):
        """Test getting OCI settings by client when client has no OCI settings"""
        from server.bootstrap import bootstrap

        client_settings_no_oci = Settings(client="test_client", oci=None)

        # Save originals
        orig_settings = bootstrap.SETTINGS_OBJECTS
        orig_oci = bootstrap.OCI_OBJECTS

        try:
            # Replace with test data
            bootstrap.SETTINGS_OBJECTS = [client_settings_no_oci]
            bootstrap.OCI_OBJECTS = [sample_oci_default]

            result = oci_utils.get(client="test_client")

            assert result == sample_oci_default
        finally:
            # Restore originals
            bootstrap.SETTINGS_OBJECTS = orig_settings
            bootstrap.OCI_OBJECTS = orig_oci

    # test_get_by_client_not_found: See test/unit/server/api/utils/test_utils_oci.py::TestGet::test_get_raises_value_error_client_not_found

    def test_get_by_client_no_matching_profile(self, sample_client_settings, sample_oci_default):
        """Test getting OCI settings by client when no matching profile exists"""
        from server.bootstrap import bootstrap

        # Save originals
        orig_settings = bootstrap.SETTINGS_OBJECTS
        orig_oci = bootstrap.OCI_OBJECTS

        try:
            # Replace with test data
            bootstrap.SETTINGS_OBJECTS = [sample_client_settings]
            bootstrap.OCI_OBJECTS = [sample_oci_default]  # Only DEFAULT profile

            expected_error = "No settings found for client 'test_client' with auth_profile 'CUSTOM'"
            with pytest.raises(ValueError, match=expected_error):
                oci_utils.get(client="test_client")
        finally:
            # Restore originals
            bootstrap.SETTINGS_OBJECTS = orig_settings
            bootstrap.OCI_OBJECTS = orig_oci

    # test_get_both_client_and_auth_profile: See test/unit/server/api/utils/test_utils_oci.py::TestGet::test_get_raises_value_error_both_params


class TestGetSigner:
    """Test get_signer() function"""

    # test_get_signer_instance_principal: See test/unit/server/api/utils/test_utils_oci.py::TestGetSigner::test_get_signer_instance_principal
    # test_get_signer_oke_workload_identity: See test/unit/server/api/utils/test_utils_oci.py::TestGetSigner::test_get_signer_oke_workload_identity
    # test_get_signer_api_key: See test/unit/server/api/utils/test_utils_oci.py::TestGetSigner::test_get_signer_api_key_returns_none

    def test_get_signer_security_token(self):
        """Test get_signer with security_token authentication (returns None)"""
        config = OracleCloudSettings(auth_profile="DEFAULT", authentication="security_token")

        result = oci_utils.get_signer(config)

        assert result is None


class TestInitClient:
    """Test init_client() function"""

    @pytest.fixture
    def api_key_config(self):
        """API key configuration fixture"""
        return OracleCloudSettings(
            auth_profile="DEFAULT",
            authentication="api_key",
            region="us-ashburn-1",
            user="ocid1.user.oc1..testuser",
            fingerprint="test-fingerprint",
            tenancy="ocid1.tenancy.oc1..testtenant",
            key_file="/path/to/key.pem",
        )

    # test_init_client_api_key: See test/unit/server/api/utils/test_utils_oci.py::TestInitClient::test_init_client_standard_auth

    @patch("oci.generative_ai_inference.GenerativeAiInferenceClient")
    @patch.object(oci_utils, "get_signer", return_value=None)
    def test_init_client_genai_with_endpoint(self, _mock_get_signer, mock_client_class, api_key_config):
        """Test init_client for GenAI sets correct service endpoint"""
        genai_config = api_key_config.model_copy()
        genai_config.genai_compartment_id = "ocid1.compartment.oc1..test"
        genai_config.genai_region = "us-chicago-1"

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = oci_utils.init_client(oci.generative_ai_inference.GenerativeAiInferenceClient, genai_config)

        assert result == mock_client
        # Verify service_endpoint was set in kwargs
        call_kwargs = mock_client_class.call_args[1]
        assert "service_endpoint" in call_kwargs
        assert "us-chicago-1" in call_kwargs["service_endpoint"]

    @patch("oci.identity.IdentityClient")
    @patch.object(oci_utils, "get_signer")
    def test_init_client_with_instance_principal_signer(self, mock_get_signer, mock_client_class):
        """Test init_client with instance principal signer"""
        instance_config = OracleCloudSettings(
            auth_profile="DEFAULT",
            authentication="instance_principal",
            region="us-ashburn-1",
            tenancy=None,  # Will be set from signer
        )

        mock_signer = MagicMock()
        mock_signer.tenancy_id = "ocid1.tenancy.oc1..test"
        mock_get_signer.return_value = mock_signer

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = oci_utils.init_client(oci.identity.IdentityClient, instance_config)

        assert result == mock_client
        # Verify signer was used
        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs["signer"] == mock_signer
        # Verify tenancy was set from signer
        assert instance_config.tenancy == "ocid1.tenancy.oc1..test"

    @patch("oci.identity.IdentityClient")
    @patch.object(oci_utils, "get_signer")
    def test_init_client_with_workload_identity_signer(self, mock_get_signer, mock_client_class):
        """Test init_client with OKE workload identity signer"""
        workload_config = OracleCloudSettings(
            auth_profile="DEFAULT",
            authentication="oke_workload_identity",
            region="us-ashburn-1",
            tenancy=None,  # Will be extracted from token
        )

        # Mock JWT token with tenant claim
        import base64
        import json

        payload = {"tenant": "ocid1.tenancy.oc1..workload"}
        payload_json = json.dumps(payload)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        mock_token = f"header.{payload_b64}.signature"

        mock_signer = MagicMock()
        mock_signer.get_security_token.return_value = mock_token
        mock_get_signer.return_value = mock_signer

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = oci_utils.init_client(oci.identity.IdentityClient, workload_config)

        assert result == mock_client
        # Verify tenancy was extracted from token
        assert workload_config.tenancy == "ocid1.tenancy.oc1..workload"

    @patch("oci.identity.IdentityClient")
    @patch.object(oci_utils, "get_signer", return_value=None)
    @patch("builtins.open", new_callable=MagicMock)
    @patch("oci.signer.load_private_key_from_file")
    @patch("oci.auth.signers.SecurityTokenSigner")
    def test_init_client_with_security_token(
        self, mock_sec_token_signer, mock_load_key, mock_open, _mock_get_signer, mock_client_class
    ):
        """Test init_client with security token authentication"""
        token_config = OracleCloudSettings(
            auth_profile="DEFAULT",
            authentication="security_token",
            region="us-ashburn-1",
            security_token_file="/path/to/token",
            key_file="/path/to/key.pem",
        )

        # Mock file reading
        mock_open.return_value.__enter__.return_value.read.return_value = "mock_token_content"
        mock_private_key = MagicMock()
        mock_load_key.return_value = mock_private_key
        mock_signer_instance = MagicMock()
        mock_sec_token_signer.return_value = mock_signer_instance

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = oci_utils.init_client(oci.identity.IdentityClient, token_config)

        assert result == mock_client
        mock_load_key.assert_called_once_with("/path/to/key.pem")
        mock_sec_token_signer.assert_called_once_with("mock_token_content", mock_private_key)

    # test_init_client_invalid_config: See test/unit/server/api/utils/test_utils_oci.py::TestInitClient::test_init_client_raises_oci_exception_on_invalid_config


class TestOciUtils:
    """Test OCI utility functions"""

    @pytest.fixture
    def sample_oci_config(self):
        """Sample OCI config fixture"""
        return get_sample_oci_config()

    # test_init_genai_client: See test/unit/server/api/utils/test_utils_oci.py::TestInitGenaiClient::test_init_genai_client_calls_init_client
    # test_get_namespace_success: See test/unit/server/api/utils/test_utils_oci.py::TestGetNamespace::test_get_namespace_success

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_invalid_config(self, mock_init_client, sample_oci_config):
        """Test namespace retrieval with invalid config"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = oci.exceptions.InvalidConfig("Invalid config")
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(sample_oci_config)

        assert exc_info.value.status_code == 400
        assert "Invalid Config" in str(exc_info.value)

    # test_get_namespace_file_not_found: See test/unit/server/api/utils/test_utils_oci.py::TestGetNamespace::test_get_namespace_raises_on_file_not_found
    # test_get_namespace_service_error: See test/unit/server/api/utils/test_utils_oci.py::TestGetNamespace::test_get_namespace_raises_on_service_error

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_unbound_local_error(self, mock_init_client, sample_oci_config):
        """Test namespace retrieval with unbound local error"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = UnboundLocalError("local variable referenced before assignment")
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(sample_oci_config)

        assert exc_info.value.status_code == 500
        assert "No Configuration" in str(exc_info.value)

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_request_exception(self, mock_init_client, sample_oci_config):
        """Test namespace retrieval with request exception"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = oci.exceptions.RequestException("Connection timeout")
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(sample_oci_config)

        assert exc_info.value.status_code == 503

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_generic_exception(self, mock_init_client, sample_oci_config):
        """Test namespace retrieval with generic exception"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = Exception("Unexpected error")
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(sample_oci_config)

        assert exc_info.value.status_code == 500
        assert "Unexpected error" in str(exc_info.value)

    # test_get_regions_success: See test/unit/server/api/utils/test_utils_oci.py::TestGetRegions::test_get_regions_returns_list
    # test_logger_exists: See test/unit/server/api/utils/test_utils_oci.py::TestLoggerConfiguration::test_logger_exists
