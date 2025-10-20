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
from common.schema import OracleCloudSettings, Settings, OciSettings


class TestOciException:
    """Test custom OCI exception class"""

    def test_oci_exception_initialization(self):
        """Test OciException initialization"""
        exc = OciException(status_code=400, detail="Invalid configuration")
        assert exc.status_code == 400
        assert exc.detail == "Invalid configuration"
        assert str(exc) == "Invalid configuration"


class TestOciGet:
    """Test OCI get() function"""

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_oci_default = OracleCloudSettings(
            auth_profile="DEFAULT", compartment_id="ocid1.compartment.oc1..default"
        )
        self.sample_oci_custom = OracleCloudSettings(
            auth_profile="CUSTOM", compartment_id="ocid1.compartment.oc1..custom"
        )
        self.sample_client_settings = Settings(client="test_client", oci=OciSettings(auth_profile="CUSTOM"))

    @patch("server.api.utils.oci.OCI_OBJECTS", [])
    def test_get_no_objects_configured(self):
        """Test getting OCI settings when none are configured"""
        with pytest.raises(ValueError, match="not configured"):
            oci_utils.get()

    @patch("server.api.utils.oci.OCI_OBJECTS", new_callable=list)
    def test_get_all(self, mock_oci_objects):
        """Test getting all OCI settings when no filters are provided"""
        all_oci = [self.sample_oci_default, self.sample_oci_custom]
        mock_oci_objects.extend(all_oci)

        result = oci_utils.get()

        assert result == all_oci

    @patch("server.api.utils.oci.OCI_OBJECTS")
    def test_get_by_auth_profile_found(self, mock_oci_objects):
        """Test getting OCI settings by auth_profile when it exists"""
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default, self.sample_oci_custom]))

        result = oci_utils.get(auth_profile="CUSTOM")

        assert result == self.sample_oci_custom

    @patch("server.api.utils.oci.OCI_OBJECTS")
    def test_get_by_auth_profile_not_found(self, mock_oci_objects):
        """Test getting OCI settings by auth_profile when it doesn't exist"""
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default]))

        with pytest.raises(ValueError, match="profile 'NONEXISTENT' not found"):
            oci_utils.get(auth_profile="NONEXISTENT")

    @patch("server.api.utils.oci.OCI_OBJECTS")
    @patch("server.api.utils.oci.SETTINGS_OBJECTS")
    def test_get_by_client_with_oci_settings(self, mock_settings_objects, mock_oci_objects):
        """Test getting OCI settings by client when client has OCI settings"""
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([self.sample_client_settings]))
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default, self.sample_oci_custom]))

        result = oci_utils.get(client="test_client")

        assert result == self.sample_oci_custom

    @patch("server.api.utils.oci.OCI_OBJECTS")
    @patch("server.api.utils.oci.SETTINGS_OBJECTS")
    def test_get_by_client_without_oci_settings(self, mock_settings_objects, mock_oci_objects):
        """Test getting OCI settings by client when client has no OCI settings"""
        client_settings_no_oci = Settings(client="test_client", oci=None)
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([client_settings_no_oci]))
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default]))

        result = oci_utils.get(client="test_client")

        assert result == self.sample_oci_default

    @patch("server.api.utils.oci.OCI_OBJECTS")
    @patch("server.api.utils.oci.SETTINGS_OBJECTS")
    def test_get_by_client_not_found(self, mock_settings_objects, mock_oci_objects):
        """Test getting OCI settings when client doesn't exist"""
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([]))

        with pytest.raises(ValueError, match="client test_client not found"):
            oci_utils.get(client="test_client")

    @patch("server.api.utils.oci.OCI_OBJECTS")
    @patch("server.api.utils.oci.SETTINGS_OBJECTS")
    def test_get_by_client_no_matching_profile(self, mock_settings_objects, mock_oci_objects):
        """Test getting OCI settings by client when no matching profile exists"""
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([self.sample_client_settings]))
        mock_oci_objects.__iter__ = MagicMock(return_value=iter([self.sample_oci_default]))  # Only DEFAULT profile

        with pytest.raises(ValueError, match="No settings found for client 'test_client' with auth_profile 'CUSTOM'"):
            oci_utils.get(client="test_client")

    def test_get_both_client_and_auth_profile(self):
        """Test that providing both client and auth_profile raises an error"""
        with pytest.raises(ValueError, match="provide either 'client' or 'auth_profile', not both"):
            oci_utils.get(client="test_client", auth_profile="CUSTOM")


class TestGetSigner:
    """Test get_signer() function"""

    def test_get_signer_instance_principal(self):
        """Test get_signer with instance_principal authentication"""
        config = OracleCloudSettings(auth_profile="DEFAULT", authentication="instance_principal")

        with patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner") as mock_signer:
            mock_instance = MagicMock()
            mock_signer.return_value = mock_instance

            result = oci_utils.get_signer(config)

            assert result == mock_instance
            mock_signer.assert_called_once()

    def test_get_signer_oke_workload_identity(self):
        """Test get_signer with oke_workload_identity authentication"""
        config = OracleCloudSettings(auth_profile="DEFAULT", authentication="oke_workload_identity")

        with patch("oci.auth.signers.get_oke_workload_identity_resource_principal_signer") as mock_signer:
            mock_instance = MagicMock()
            mock_signer.return_value = mock_instance

            result = oci_utils.get_signer(config)

            assert result == mock_instance
            mock_signer.assert_called_once()

    def test_get_signer_api_key(self):
        """Test get_signer with api_key authentication (returns None)"""
        config = OracleCloudSettings(auth_profile="DEFAULT", authentication="api_key")

        result = oci_utils.get_signer(config)

        assert result is None

    def test_get_signer_security_token(self):
        """Test get_signer with security_token authentication (returns None)"""
        config = OracleCloudSettings(auth_profile="DEFAULT", authentication="security_token")

        result = oci_utils.get_signer(config)

        assert result is None


class TestInitClient:
    """Test init_client() function"""

    def setup_method(self):
        """Setup test data"""
        self.api_key_config = OracleCloudSettings(
            auth_profile="DEFAULT",
            authentication="api_key",
            region="us-ashburn-1",
            user="ocid1.user.oc1..testuser",
            fingerprint="test-fingerprint",
            tenancy="ocid1.tenancy.oc1..testtenant",
            key_file="/path/to/key.pem",
        )

    @patch("oci.object_storage.ObjectStorageClient")
    @patch.object(oci_utils, "get_signer", return_value=None)
    def test_init_client_api_key(self, mock_get_signer, mock_client_class):
        """Test init_client with API key authentication"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = oci_utils.init_client(oci.object_storage.ObjectStorageClient, self.api_key_config)

        assert result == mock_client
        mock_get_signer.assert_called_once_with(self.api_key_config)
        mock_client_class.assert_called_once()

    @patch("oci.generative_ai_inference.GenerativeAiInferenceClient")
    @patch.object(oci_utils, "get_signer", return_value=None)
    def test_init_client_genai_with_endpoint(self, mock_get_signer, mock_client_class):
        """Test init_client for GenAI sets correct service endpoint"""
        genai_config = self.api_key_config.model_copy()
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
            tenancy=None  # Will be set from signer
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
            tenancy=None  # Will be extracted from token
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
        self, mock_sec_token_signer, mock_load_key, mock_open, mock_get_signer, mock_client_class
    ):
        """Test init_client with security token authentication"""
        token_config = OracleCloudSettings(
            auth_profile="DEFAULT",
            authentication="security_token",
            region="us-ashburn-1",
            security_token_file="/path/to/token",
            key_file="/path/to/key.pem"
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

    @patch("oci.object_storage.ObjectStorageClient")
    @patch.object(oci_utils, "get_signer", return_value=None)
    def test_init_client_invalid_config(self, mock_get_signer, mock_client_class):
        """Test init_client with invalid config raises OciException"""
        mock_client_class.side_effect = oci.exceptions.InvalidConfig("Bad config")

        with pytest.raises(OciException) as exc_info:
            oci_utils.init_client(oci.object_storage.ObjectStorageClient, self.api_key_config)

        assert exc_info.value.status_code == 400
        assert "Invalid Config" in str(exc_info.value)


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
    def test_get_namespace_service_error(self, mock_init_client):
        """Test namespace retrieval with service error"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = oci.exceptions.ServiceError(
            status=401, code="NotAuthenticated", headers={}, message="Auth failed"
        )
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(self.sample_oci_config)

        assert exc_info.value.status_code == 401
        assert "AuthN Error" in str(exc_info.value)

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_unbound_local_error(self, mock_init_client):
        """Test namespace retrieval with unbound local error"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = UnboundLocalError("local variable referenced before assignment")
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(self.sample_oci_config)

        assert exc_info.value.status_code == 500
        assert "No Configuration" in str(exc_info.value)

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_request_exception(self, mock_init_client):
        """Test namespace retrieval with request exception"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = oci.exceptions.RequestException("Connection timeout")
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(self.sample_oci_config)

        assert exc_info.value.status_code == 503

    @patch.object(oci_utils, "init_client")
    def test_get_namespace_generic_exception(self, mock_init_client):
        """Test namespace retrieval with generic exception"""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = Exception("Unexpected error")
        mock_init_client.return_value = mock_client

        with pytest.raises(OciException) as exc_info:
            oci_utils.get_namespace(self.sample_oci_config)

        assert exc_info.value.status_code == 500
        assert "Unexpected error" in str(exc_info.value)

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
