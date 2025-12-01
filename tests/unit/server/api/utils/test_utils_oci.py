"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/oci.py
Tests for OCI utility functions.
"""

# pylint: disable=too-few-public-methods

import base64
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import oci
import pytest
from urllib3.exceptions import MaxRetryError

from server.api.utils import oci as utils_oci
from server.api.utils.oci import OciException


class TestOciException:
    """Tests for OciException class."""

    def test_oci_exception_init(self):
        """OciException should store status_code and detail."""
        exc = OciException(status_code=404, detail="Not found")
        assert exc.status_code == 404
        assert exc.detail == "Not found"

    def test_oci_exception_message(self):
        """OciException should use detail as message."""
        exc = OciException(status_code=500, detail="Server error")
        assert str(exc) == "Server error"


class TestGet:
    """Tests for the get function."""

    @patch("server.api.utils.oci.bootstrap.OCI_OBJECTS", [])
    def test_get_raises_value_error_when_not_configured(self):
        """get should raise ValueError when no OCI objects configured."""
        with pytest.raises(ValueError) as exc_info:
            utils_oci.get()
        assert "not configured" in str(exc_info.value)

    @patch("server.api.utils.oci.bootstrap.OCI_OBJECTS")
    def test_get_returns_all_oci_objects(self, mock_objects, make_oci_config):
        """get should return all OCI objects when no filters."""
        oci1 = make_oci_config(auth_profile="PROFILE1")
        oci2 = make_oci_config(auth_profile="PROFILE2")
        mock_objects.__iter__ = lambda _: iter([oci1, oci2])
        mock_objects.__len__ = lambda _: 2
        mock_objects.__bool__ = lambda _: True

        result = utils_oci.get()

        assert len(result) == 2

    @patch("server.api.utils.oci.bootstrap.OCI_OBJECTS")
    def test_get_by_auth_profile(self, mock_objects, make_oci_config):
        """get should return matching OCI object by auth_profile."""
        oci1 = make_oci_config(auth_profile="PROFILE1")
        oci2 = make_oci_config(auth_profile="PROFILE2")
        mock_objects.__iter__ = lambda _: iter([oci1, oci2])

        result = utils_oci.get(auth_profile="PROFILE1")

        assert result.auth_profile == "PROFILE1"

    @patch("server.api.utils.oci.bootstrap.OCI_OBJECTS")
    def test_get_raises_value_error_profile_not_found(self, mock_objects, make_oci_config):
        """get should raise ValueError when profile not found."""
        mock_objects.__iter__ = lambda _: iter([make_oci_config(auth_profile="DEFAULT")])

        with pytest.raises(ValueError) as exc_info:
            utils_oci.get(auth_profile="NONEXISTENT")

        assert "not found" in str(exc_info.value)

    def test_get_raises_value_error_both_params(self):
        """get should raise ValueError when both client and auth_profile provided."""
        with pytest.raises(ValueError) as exc_info:
            utils_oci.get(client="test", auth_profile="DEFAULT")

        assert "not both" in str(exc_info.value)

    @patch("server.api.utils.oci.bootstrap.SETTINGS_OBJECTS")
    @patch("server.api.utils.oci.bootstrap.OCI_OBJECTS")
    def test_get_by_client(self, mock_oci, mock_settings, make_oci_config, make_settings):
        """get should return OCI object based on client settings."""
        settings = make_settings(client="test_client")
        settings.oci.auth_profile = "CLIENT_PROFILE"
        mock_settings.__iter__ = lambda _: iter([settings])
        mock_settings.__len__ = lambda _: 1

        oci_config = make_oci_config(auth_profile="CLIENT_PROFILE")
        mock_oci.__iter__ = lambda _: iter([oci_config])

        result = utils_oci.get(client="test_client")

        assert result.auth_profile == "CLIENT_PROFILE"

    @patch("server.api.utils.oci.bootstrap.SETTINGS_OBJECTS", [])
    def test_get_raises_value_error_client_not_found(self):
        """get should raise ValueError when client not found."""
        with pytest.raises(ValueError) as exc_info:
            utils_oci.get(client="nonexistent")

        assert "not found" in str(exc_info.value)


class TestGetSigner:
    """Tests for the get_signer function."""

    @patch("server.api.utils.oci.oci.auth.signers.InstancePrincipalsSecurityTokenSigner")
    def test_get_signer_instance_principal(self, mock_signer_class, make_oci_config):
        """get_signer should return instance principal signer."""
        mock_signer = MagicMock()
        mock_signer_class.return_value = mock_signer
        config = make_oci_config()
        config.authentication = "instance_principal"

        result = utils_oci.get_signer(config)

        assert result == mock_signer
        mock_signer_class.assert_called_once()

    @patch("server.api.utils.oci.oci.auth.signers.get_oke_workload_identity_resource_principal_signer")
    def test_get_signer_oke_workload_identity(self, mock_signer_func, make_oci_config):
        """get_signer should return OKE workload identity signer."""
        mock_signer = MagicMock()
        mock_signer_func.return_value = mock_signer
        config = make_oci_config()
        config.authentication = "oke_workload_identity"

        result = utils_oci.get_signer(config)

        assert result == mock_signer

    def test_get_signer_api_key_returns_none(self, make_oci_config):
        """get_signer should return None for API key authentication."""
        config = make_oci_config()
        config.authentication = "api_key"

        result = utils_oci.get_signer(config)

        assert result is None


class TestInitClient:
    """Tests for the init_client function."""

    @patch("server.api.utils.oci.get_signer")
    @patch("server.api.utils.oci.oci.object_storage.ObjectStorageClient")
    def test_init_client_standard_auth(self, mock_client_class, mock_get_signer, make_oci_config):
        """init_client should initialize with standard authentication."""
        mock_get_signer.return_value = None
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        config = make_oci_config()

        result = utils_oci.init_client(oci.object_storage.ObjectStorageClient, config)

        assert result == mock_client

    @patch("server.api.utils.oci.get_signer")
    @patch("server.api.utils.oci.oci.object_storage.ObjectStorageClient")
    def test_init_client_with_signer(self, mock_client_class, mock_get_signer, make_oci_config):
        """init_client should use signer when provided."""
        mock_signer = MagicMock()
        mock_signer.tenancy_id = "test-tenancy-id"
        mock_get_signer.return_value = mock_signer
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        config = make_oci_config()
        config.authentication = "instance_principal"
        config.region = "us-ashburn-1"  # Required for signer-based auth
        config.tenancy = "existing-tenancy"  # Set tenancy so code doesn't try to derive from signer

        result = utils_oci.init_client(oci.object_storage.ObjectStorageClient, config)

        assert result == mock_client
        # Check signer was passed to client
        call_kwargs = mock_client_class.call_args.kwargs
        assert call_kwargs["signer"] == mock_signer

    @patch("server.api.utils.oci.get_signer")
    def test_init_client_raises_oci_exception_on_invalid_config(self, mock_get_signer, make_oci_config):
        """init_client should raise OciException on invalid config."""
        mock_get_signer.return_value = None
        config = make_oci_config()

        with patch("server.api.utils.oci.oci.object_storage.ObjectStorageClient") as mock_client:
            mock_client.side_effect = oci.exceptions.InvalidConfig("Invalid configuration")

            with pytest.raises(OciException) as exc_info:
                utils_oci.init_client(oci.object_storage.ObjectStorageClient, config)

            assert exc_info.value.status_code == 400

    @patch("server.api.utils.oci.get_signer")
    @patch("server.api.utils.oci.oci.generative_ai_inference.GenerativeAiInferenceClient")
    def test_init_client_genai_sets_service_endpoint(self, mock_client_class, mock_get_signer, make_oci_config):
        """init_client should set service endpoint for GenAI client."""
        mock_get_signer.return_value = None
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        config = make_oci_config(genai_region="us-chicago-1")
        config.genai_compartment_id = "ocid1.compartment.oc1..test"

        utils_oci.init_client(oci.generative_ai_inference.GenerativeAiInferenceClient, config)

        call_kwargs = mock_client_class.call_args.kwargs
        assert "inference.generativeai.us-chicago-1.oci.oraclecloud.com" in call_kwargs["service_endpoint"]


class TestGetNamespace:
    """Tests for the get_namespace function."""

    @patch("server.api.utils.oci.init_client")
    def test_get_namespace_success(self, mock_init_client, make_oci_config):
        """get_namespace should return namespace on success."""
        mock_client = MagicMock()
        mock_client.get_namespace.return_value.data = "test-namespace"
        mock_init_client.return_value = mock_client
        config = make_oci_config()

        result = utils_oci.get_namespace(config)

        assert result == "test-namespace"
        assert config.namespace == "test-namespace"

    @patch("server.api.utils.oci.init_client")
    def test_get_namespace_raises_on_service_error(self, mock_init_client, make_oci_config):
        """get_namespace should raise OciException on service error."""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = oci.exceptions.ServiceError(
            status=401, code="NotAuthenticated", headers={}, message="Not authenticated"
        )
        mock_init_client.return_value = mock_client
        config = make_oci_config()

        with pytest.raises(OciException) as exc_info:
            utils_oci.get_namespace(config)

        assert exc_info.value.status_code == 401

    @patch("server.api.utils.oci.init_client")
    def test_get_namespace_raises_on_file_not_found(self, mock_init_client, make_oci_config):
        """get_namespace should raise OciException on file not found."""
        mock_init_client.side_effect = FileNotFoundError("Key file not found")
        config = make_oci_config()

        with pytest.raises(OciException) as exc_info:
            utils_oci.get_namespace(config)

        assert exc_info.value.status_code == 400


class TestGetRegions:
    """Tests for the get_regions function."""

    @patch("server.api.utils.oci.init_client")
    def test_get_regions_returns_list(self, mock_init_client, make_oci_config):
        """get_regions should return list of region subscriptions."""
        mock_region = MagicMock()
        mock_region.is_home_region = True
        mock_region.region_key = "IAD"
        mock_region.region_name = "us-ashburn-1"
        mock_region.status = "READY"

        mock_client = MagicMock()
        mock_client.list_region_subscriptions.return_value.data = [mock_region]
        mock_init_client.return_value = mock_client
        config = make_oci_config()
        config.tenancy = "test-tenancy"

        result = utils_oci.get_regions(config)

        assert len(result) == 1
        assert result[0]["region_name"] == "us-ashburn-1"
        assert result[0]["is_home_region"] is True


class TestGetGenaiModels:
    """Tests for the get_genai_models function."""

    def test_get_genai_models_raises_without_compartment(self, make_oci_config):
        """get_genai_models should raise OciException without compartment_id."""
        config = make_oci_config()
        config.genai_compartment_id = None

        with pytest.raises(OciException) as exc_info:
            utils_oci.get_genai_models(config)

        assert exc_info.value.status_code == 400
        assert "genai_compartment_id" in exc_info.value.detail

    def test_get_genai_models_regional_raises_without_region(self, make_oci_config):
        """get_genai_models should raise OciException without region when regional=True."""
        config = make_oci_config()
        config.genai_compartment_id = "ocid1.compartment.oc1..test"
        config.genai_region = None

        with pytest.raises(OciException) as exc_info:
            utils_oci.get_genai_models(config, regional=True)

        assert exc_info.value.status_code == 400
        assert "genai_region" in exc_info.value.detail

    @patch("server.api.utils.oci.init_client")
    def test_get_genai_models_returns_models(self, mock_init_client, make_oci_config):
        """get_genai_models should return list of GenAI models."""
        mock_model = MagicMock()
        mock_model.display_name = "cohere.command-r-plus"
        mock_model.capabilities = ["TEXT_GENERATION"]
        mock_model.vendor = "cohere"
        mock_model.id = "ocid1.model.oc1..test"
        mock_model.time_deprecated = None
        mock_model.time_dedicated_retired = None
        mock_model.time_on_demand_retired = None

        mock_response = MagicMock()
        mock_response.data.items = [mock_model]

        mock_client = MagicMock()
        mock_client.list_models.return_value = mock_response
        mock_init_client.return_value = mock_client

        config = make_oci_config(genai_region="us-chicago-1")
        config.genai_compartment_id = "ocid1.compartment.oc1..test"

        result = utils_oci.get_genai_models(config, regional=True)

        assert len(result) == 1
        assert result[0]["model_name"] == "cohere.command-r-plus"


class TestGetCompartments:
    """Tests for the get_compartments function."""

    @patch("server.api.utils.oci.init_client")
    def test_get_compartments_returns_dict(self, mock_init_client, make_oci_config):
        """get_compartments should return dict of compartment paths."""
        mock_compartment = MagicMock()
        mock_compartment.id = "ocid1.compartment.oc1..test"
        mock_compartment.name = "TestCompartment"
        mock_compartment.compartment_id = None  # Root level

        mock_client = MagicMock()
        mock_client.list_compartments.return_value.data = [mock_compartment]
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.tenancy = "test-tenancy"

        result = utils_oci.get_compartments(config)

        assert "TestCompartment" in result
        assert result["TestCompartment"] == "ocid1.compartment.oc1..test"


class TestGetBuckets:
    """Tests for the get_buckets function."""

    @patch("server.api.utils.oci.init_client")
    def test_get_buckets_returns_list(self, mock_init_client, make_oci_config):
        """get_buckets should return list of bucket names."""
        mock_bucket = MagicMock()
        mock_bucket.name = "test-bucket"
        mock_bucket.freeform_tags = {}

        mock_client = MagicMock()
        mock_client.list_buckets.return_value.data = [mock_bucket]
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.namespace = "test-namespace"

        result = utils_oci.get_buckets("compartment-id", config)

        assert result == ["test-bucket"]

    @patch("server.api.utils.oci.init_client")
    def test_get_buckets_excludes_genai_chunk_buckets(self, mock_init_client, make_oci_config):
        """get_buckets should exclude buckets with genai_chunk=true tag."""
        mock_bucket1 = MagicMock()
        mock_bucket1.name = "normal-bucket"
        mock_bucket1.freeform_tags = {}

        mock_bucket2 = MagicMock()
        mock_bucket2.name = "chunk-bucket"
        mock_bucket2.freeform_tags = {"genai_chunk": "true"}

        mock_client = MagicMock()
        mock_client.list_buckets.return_value.data = [mock_bucket1, mock_bucket2]
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.namespace = "test-namespace"

        result = utils_oci.get_buckets("compartment-id", config)

        assert result == ["normal-bucket"]

    @patch("server.api.utils.oci.init_client")
    def test_get_buckets_raises_on_service_error(self, mock_init_client, make_oci_config):
        """get_buckets should raise OciException on service error."""
        mock_client = MagicMock()
        mock_client.list_buckets.side_effect = oci.exceptions.ServiceError(
            status=401, code="NotAuthenticated", headers={}, message="Not authenticated"
        )
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.namespace = "test-namespace"

        with pytest.raises(OciException) as exc_info:
            utils_oci.get_buckets("compartment-id", config)

        assert exc_info.value.status_code == 401


class TestGetBucketObjects:
    """Tests for the get_bucket_objects function."""

    @patch("server.api.utils.oci.init_client")
    def test_get_bucket_objects_returns_names(self, mock_init_client, make_oci_config):
        """get_bucket_objects should return list of object names."""
        mock_obj = MagicMock()
        mock_obj.name = "document.pdf"

        mock_response = MagicMock()
        mock_response.data.objects = [mock_obj]

        mock_client = MagicMock()
        mock_client.list_objects.return_value = mock_response
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.namespace = "test-namespace"

        result = utils_oci.get_bucket_objects("test-bucket", config)

        assert result == ["document.pdf"]

    @patch("server.api.utils.oci.init_client")
    def test_get_bucket_objects_returns_empty_on_not_found(self, mock_init_client, make_oci_config):
        """get_bucket_objects should return empty list on service error."""
        mock_client = MagicMock()
        mock_client.list_objects.side_effect = oci.exceptions.ServiceError(
            status=404, code="BucketNotFound", headers={}, message="Bucket not found"
        )
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.namespace = "test-namespace"

        result = utils_oci.get_bucket_objects("nonexistent-bucket", config)

        assert result == []


class TestGetBucketObjectsWithMetadata:
    """Tests for the get_bucket_objects_with_metadata function."""

    @patch("server.api.utils.oci.init_client")
    def test_get_bucket_objects_with_metadata_returns_supported_files(self, mock_init_client, make_oci_config):
        """get_bucket_objects_with_metadata should return only supported file types."""
        mock_pdf = MagicMock()
        mock_pdf.name = "document.pdf"
        mock_pdf.size = 1000
        mock_pdf.etag = "abc123"
        mock_pdf.time_modified = datetime(2024, 1, 1, 12, 0, 0)
        mock_pdf.md5 = "md5hash"

        mock_exe = MagicMock()
        mock_exe.name = "program.exe"
        mock_exe.size = 2000
        mock_exe.etag = "def456"
        mock_exe.time_modified = datetime(2024, 1, 1, 12, 0, 0)
        mock_exe.md5 = "md5hash2"

        mock_response = MagicMock()
        mock_response.data.objects = [mock_pdf, mock_exe]

        mock_client = MagicMock()
        mock_client.list_objects.return_value = mock_response
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.namespace = "test-namespace"

        result = utils_oci.get_bucket_objects_with_metadata("test-bucket", config)

        assert len(result) == 1
        assert result[0]["name"] == "document.pdf"
        assert result[0]["extension"] == "pdf"


class TestDetectChangedObjects:
    """Tests for the detect_changed_objects function."""

    def test_detect_new_objects(self):
        """detect_changed_objects should identify new objects."""
        current_objects = [{"name": "new_file.pdf", "etag": "abc123", "time_modified": "2024-01-01T12:00:00"}]
        processed_objects = {}

        new, modified = utils_oci.detect_changed_objects(current_objects, processed_objects)

        assert len(new) == 1
        assert len(modified) == 0
        assert new[0]["name"] == "new_file.pdf"

    def test_detect_modified_objects(self):
        """detect_changed_objects should identify modified objects."""
        current_objects = [{"name": "existing.pdf", "etag": "new_etag", "time_modified": "2024-01-02T12:00:00"}]
        processed_objects = {"existing.pdf": {"etag": "old_etag", "time_modified": "2024-01-01T12:00:00"}}

        new, modified = utils_oci.detect_changed_objects(current_objects, processed_objects)

        assert len(new) == 0
        assert len(modified) == 1
        assert modified[0]["name"] == "existing.pdf"

    def test_detect_unchanged_objects(self):
        """detect_changed_objects should not flag unchanged objects."""
        current_objects = [{"name": "existing.pdf", "etag": "same_etag", "time_modified": "2024-01-01T12:00:00"}]
        processed_objects = {"existing.pdf": {"etag": "same_etag", "time_modified": "2024-01-01T12:00:00"}}

        new, modified = utils_oci.detect_changed_objects(current_objects, processed_objects)

        assert len(new) == 0
        assert len(modified) == 0

    def test_detect_skips_old_format_metadata(self):
        """detect_changed_objects should skip objects with old format metadata."""
        current_objects = [{"name": "old_format.pdf", "etag": "new_etag", "time_modified": "2024-01-02T12:00:00"}]
        processed_objects = {"old_format.pdf": {"etag": None, "time_modified": None}}

        new, modified = utils_oci.detect_changed_objects(current_objects, processed_objects)

        assert len(new) == 0
        assert len(modified) == 0


class TestGetObject:
    """Tests for the get_object function."""

    @patch("server.api.utils.oci.init_client")
    def test_get_object_downloads_file(self, mock_init_client, make_oci_config, tmp_path):
        """get_object should download file to directory."""
        mock_response = MagicMock()
        mock_response.data.raw.stream.return_value = [b"file content"]

        mock_client = MagicMock()
        mock_client.get_object.return_value = mock_response
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.namespace = "test-namespace"

        result = utils_oci.get_object(str(tmp_path), "folder/document.pdf", "test-bucket", config)

        assert result == str(tmp_path / "document.pdf")
        assert (tmp_path / "document.pdf").exists()
        assert (tmp_path / "document.pdf").read_bytes() == b"file content"


class TestInitGenaiClient:
    """Tests for the init_genai_client function."""

    @patch("server.api.utils.oci.init_client")
    def test_init_genai_client_calls_init_client(self, mock_init_client, make_oci_config):
        """init_genai_client should call init_client with correct type."""
        mock_client = MagicMock()
        mock_init_client.return_value = mock_client
        config = make_oci_config()

        result = utils_oci.init_genai_client(config)

        mock_init_client.assert_called_once_with(oci.generative_ai_inference.GenerativeAiInferenceClient, config)
        assert result == mock_client


class TestInitClientSecurityToken:
    """Tests for init_client with security token authentication."""

    @patch("server.api.utils.oci.get_signer")
    @patch("server.api.utils.oci.oci.signer.load_private_key_from_file")
    @patch("server.api.utils.oci.oci.auth.signers.SecurityTokenSigner")
    @patch("server.api.utils.oci.oci.object_storage.ObjectStorageClient")
    @patch("builtins.open", create=True)
    def test_init_client_security_token_auth(
        self, mock_open, mock_client_class, mock_sec_token_signer, mock_load_key, mock_get_signer, make_oci_config
    ):
        """init_client should use security token authentication when configured."""
        mock_get_signer.return_value = None
        mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value="token_data")))
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_private_key = MagicMock()
        mock_load_key.return_value = mock_private_key
        mock_signer = MagicMock()
        mock_sec_token_signer.return_value = mock_signer
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        config = make_oci_config()
        config.authentication = "security_token"
        config.security_token_file = "/path/to/token"
        config.key_file = "/path/to/key"
        config.region = "us-ashburn-1"

        result = utils_oci.init_client(oci.object_storage.ObjectStorageClient, config)

        assert result == mock_client
        mock_sec_token_signer.assert_called_once()


class TestInitClientOkeWorkloadIdentityTenancy:
    """Tests for init_client OKE workload identity tenancy extraction."""

    @patch("server.api.utils.oci.get_signer")
    @patch("server.api.utils.oci.oci.object_storage.ObjectStorageClient")
    def test_init_client_oke_workload_extracts_tenancy(self, mock_client_class, mock_get_signer, make_oci_config):
        """init_client should extract tenancy from OKE workload identity token."""
        # Create a mock JWT token with tenant claim
        payload = {"tenant": "ocid1.tenancy.oc1..test"}
        payload_json = json.dumps(payload)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        mock_token = f"header.{payload_b64}.signature"

        mock_signer = MagicMock()
        mock_signer.get_security_token.return_value = mock_token
        mock_get_signer.return_value = mock_signer
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        config = make_oci_config()
        config.authentication = "oke_workload_identity"
        config.region = "us-ashburn-1"
        config.tenancy = None  # Not set, should be extracted from token

        utils_oci.init_client(oci.object_storage.ObjectStorageClient, config)

        assert config.tenancy == "ocid1.tenancy.oc1..test"


class TestGetNamespaceExceptionHandling:
    """Tests for get_namespace exception handling."""

    @patch("server.api.utils.oci.init_client")
    def test_get_namespace_raises_on_unbound_local_error(self, mock_init_client, make_oci_config):
        """get_namespace should raise OciException on UnboundLocalError."""
        mock_init_client.side_effect = UnboundLocalError("Client not initialized")
        config = make_oci_config()

        with pytest.raises(OciException) as exc_info:
            utils_oci.get_namespace(config)

        assert exc_info.value.status_code == 500
        assert "No Configuration" in exc_info.value.detail

    @patch("server.api.utils.oci.init_client")
    def test_get_namespace_raises_on_request_exception(self, mock_init_client, make_oci_config):
        """get_namespace should raise OciException on RequestException."""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = oci.exceptions.RequestException("Connection timeout")
        mock_init_client.return_value = mock_client
        config = make_oci_config()

        with pytest.raises(OciException) as exc_info:
            utils_oci.get_namespace(config)

        assert exc_info.value.status_code == 503

    @patch("server.api.utils.oci.init_client")
    def test_get_namespace_raises_on_generic_exception(self, mock_init_client, make_oci_config):
        """get_namespace should raise OciException on generic Exception."""
        mock_client = MagicMock()
        mock_client.get_namespace.side_effect = RuntimeError("Unexpected error")
        mock_init_client.return_value = mock_client
        config = make_oci_config()

        with pytest.raises(OciException) as exc_info:
            utils_oci.get_namespace(config)

        assert exc_info.value.status_code == 500
        assert "Unexpected error" in exc_info.value.detail


class TestGetGenaiModelsExceptionHandling:
    """Tests for get_genai_models exception handling."""

    @patch("server.api.utils.oci.init_client")
    def test_get_genai_models_handles_service_error(self, mock_init_client, make_oci_config):
        """get_genai_models should handle ServiceError gracefully."""
        mock_client = MagicMock()
        mock_client.list_models.side_effect = oci.exceptions.ServiceError(
            status=403, code="NotAuthorized", headers={}, message="Not authorized"
        )
        mock_init_client.return_value = mock_client

        config = make_oci_config(genai_region="us-chicago-1")
        config.genai_compartment_id = "ocid1.compartment.oc1..test"

        result = utils_oci.get_genai_models(config, regional=True)

        # Should return empty list instead of raising
        assert not result

    @patch("server.api.utils.oci.init_client")
    def test_get_genai_models_handles_request_exception(self, mock_init_client, make_oci_config):
        """get_genai_models should handle RequestException gracefully."""
        mock_client = MagicMock()
        mock_client.list_models.side_effect = MaxRetryError(None, "url")
        mock_init_client.return_value = mock_client

        config = make_oci_config(genai_region="us-chicago-1")
        config.genai_compartment_id = "ocid1.compartment.oc1..test"

        result = utils_oci.get_genai_models(config, regional=True)

        # Should return empty list instead of raising
        assert not result

    @patch("server.api.utils.oci.init_client")
    def test_get_genai_models_excludes_deprecated(self, mock_init_client, make_oci_config):
        """get_genai_models should exclude deprecated models."""
        mock_active_model = MagicMock()
        mock_active_model.display_name = "active-model"
        mock_active_model.capabilities = ["TEXT_GENERATION"]
        mock_active_model.vendor = "cohere"
        mock_active_model.id = "ocid1.model.active"
        mock_active_model.time_deprecated = None
        mock_active_model.time_dedicated_retired = None
        mock_active_model.time_on_demand_retired = None

        mock_deprecated_model = MagicMock()
        mock_deprecated_model.display_name = "deprecated-model"
        mock_deprecated_model.capabilities = ["TEXT_GENERATION"]
        mock_deprecated_model.vendor = "cohere"
        mock_deprecated_model.id = "ocid1.model.deprecated"
        mock_deprecated_model.time_deprecated = datetime(2024, 1, 1)
        mock_deprecated_model.time_dedicated_retired = None
        mock_deprecated_model.time_on_demand_retired = None

        mock_response = MagicMock()
        mock_response.data.items = [mock_active_model, mock_deprecated_model]

        mock_client = MagicMock()
        mock_client.list_models.return_value = mock_response
        mock_init_client.return_value = mock_client

        config = make_oci_config(genai_region="us-chicago-1")
        config.genai_compartment_id = "ocid1.compartment.oc1..test"

        result = utils_oci.get_genai_models(config, regional=True)

        assert len(result) == 1
        assert result[0]["model_name"] == "active-model"


class TestGetBucketObjectsWithMetadataServiceError:
    """Tests for get_bucket_objects_with_metadata service error handling."""

    @patch("server.api.utils.oci.init_client")
    def test_get_bucket_objects_with_metadata_returns_empty_on_service_error(self, mock_init_client, make_oci_config):
        """get_bucket_objects_with_metadata should return empty list on ServiceError."""
        mock_client = MagicMock()
        mock_client.list_objects.side_effect = oci.exceptions.ServiceError(
            status=404, code="BucketNotFound", headers={}, message="Bucket not found"
        )
        mock_init_client.return_value = mock_client

        config = make_oci_config()
        config.namespace = "test-namespace"

        result = utils_oci.get_bucket_objects_with_metadata("nonexistent-bucket", config)

        assert not result


class TestGetClientDerivedAuthProfileNoMatch:
    """Tests for get function when derived auth profile has no matching OCI config."""

    @patch("server.api.utils.oci.bootstrap.SETTINGS_OBJECTS")
    @patch("server.api.utils.oci.bootstrap.OCI_OBJECTS")
    def test_get_raises_when_derived_profile_not_found(self, mock_oci, mock_settings, make_oci_config, make_settings):
        """get should raise ValueError when client's derived auth_profile has no matching OCI config."""
        settings = make_settings(client="test_client")
        settings.oci.auth_profile = "MISSING_PROFILE"
        mock_settings.__iter__ = lambda _: iter([settings])
        mock_settings.__len__ = lambda _: 1

        # OCI config with different profile
        oci_config = make_oci_config(auth_profile="OTHER_PROFILE")
        mock_oci.__iter__ = lambda _: iter([oci_config])

        with pytest.raises(ValueError) as exc_info:
            utils_oci.get(client="test_client")

        assert "No settings found for client" in str(exc_info.value)
