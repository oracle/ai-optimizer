"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/oci.py
Tests for OCI configuration and resource endpoints.
"""

# pylint: disable=too-few-public-methods

from unittest.mock import patch
import pytest
from fastapi import HTTPException

from server.api.v1 import oci
from server.api.utils.oci import OciException


class TestOciList:
    """Tests for the oci_list endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.utils_oci.get")
    async def test_oci_list_returns_all_configs(self, mock_get, make_oci_config):
        """oci_list should return all OCI configurations."""
        configs = [make_oci_config(auth_profile="DEFAULT"), make_oci_config(auth_profile="PROD")]
        mock_get.return_value = configs

        result = await oci.oci_list()

        assert result == configs
        mock_get.assert_called_once_with()

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.utils_oci.get")
    async def test_oci_list_raises_404_on_value_error(self, mock_get):
        """oci_list should raise 404 when ValueError occurs."""
        mock_get.side_effect = ValueError("No configs found")

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_list()

        assert exc_info.value.status_code == 404
        assert "OCI:" in str(exc_info.value.detail)


class TestOciGet:
    """Tests for the oci_get endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.utils_oci.get")
    async def test_oci_get_returns_single_config(self, mock_get, make_oci_config):
        """oci_get should return a single OCI config by profile."""
        config = make_oci_config(auth_profile="DEFAULT")
        mock_get.return_value = config

        result = await oci.oci_get(auth_profile="DEFAULT")

        assert result == config
        mock_get.assert_called_once_with(auth_profile="DEFAULT")

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.utils_oci.get")
    async def test_oci_get_raises_404_when_not_found(self, mock_get):
        """oci_get should raise 404 when profile not found."""
        mock_get.side_effect = ValueError("Profile not found")

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_get(auth_profile="NONEXISTENT")

        assert exc_info.value.status_code == 404


class TestOciListRegions:
    """Tests for the oci_list_regions endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_regions")
    async def test_oci_list_regions_success(self, mock_get_regions, mock_oci_get, make_oci_config):
        """oci_list_regions should return list of regions."""
        config = make_oci_config()
        mock_oci_get.return_value = config
        mock_get_regions.return_value = ["us-ashburn-1", "us-phoenix-1"]

        result = await oci.oci_list_regions(auth_profile="DEFAULT")

        assert result == ["us-ashburn-1", "us-phoenix-1"]
        mock_get_regions.assert_called_once_with(config)

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_regions")
    async def test_oci_list_regions_raises_on_oci_exception(self, mock_get_regions, mock_oci_get, make_oci_config):
        """oci_list_regions should raise HTTPException on OciException."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_regions.side_effect = OciException(status_code=401, detail="Unauthorized")

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_list_regions(auth_profile="DEFAULT")

        assert exc_info.value.status_code == 401


class TestOciListGenai:
    """Tests for the oci_list_genai endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_genai_models")
    async def test_oci_list_genai_success(self, mock_get_genai, mock_oci_get, make_oci_config):
        """oci_list_genai should return list of GenAI models."""
        config = make_oci_config()
        mock_oci_get.return_value = config
        mock_get_genai.return_value = [{"name": "cohere.command"}, {"name": "meta.llama"}]

        result = await oci.oci_list_genai(auth_profile="DEFAULT")

        assert len(result) == 2
        mock_get_genai.assert_called_once_with(config, regional=False)

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_genai_models")
    async def test_oci_list_genai_raises_on_oci_exception(self, mock_get_genai, mock_oci_get, make_oci_config):
        """oci_list_genai should raise HTTPException on OciException."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_genai.side_effect = OciException(status_code=403, detail="Forbidden")

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_list_genai(auth_profile="DEFAULT")

        assert exc_info.value.status_code == 403


class TestOciListCompartments:
    """Tests for the oci_list_compartments endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_compartments")
    async def test_oci_list_compartments_success(self, mock_get_compartments, mock_oci_get, make_oci_config):
        """oci_list_compartments should return compartment hierarchy."""
        config = make_oci_config()
        mock_oci_get.return_value = config
        compartments = {"root": {"name": "root", "children": []}}
        mock_get_compartments.return_value = compartments

        result = await oci.oci_list_compartments(auth_profile="DEFAULT")

        assert result == compartments
        mock_get_compartments.assert_called_once_with(config)

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_compartments")
    async def test_oci_list_compartments_raises_on_oci_exception(
        self, mock_get_compartments, mock_oci_get, make_oci_config
    ):
        """oci_list_compartments should raise HTTPException on OciException."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_compartments.side_effect = OciException(status_code=500, detail="Internal error")

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_list_compartments(auth_profile="DEFAULT")

        assert exc_info.value.status_code == 500


class TestOciListBuckets:
    """Tests for the oci_list_buckets endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_buckets")
    async def test_oci_list_buckets_success(self, mock_get_buckets, mock_oci_get, make_oci_config):
        """oci_list_buckets should return list of buckets."""
        config = make_oci_config()
        mock_oci_get.return_value = config
        mock_get_buckets.return_value = ["bucket1", "bucket2"]
        compartment_ocid = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        result = await oci.oci_list_buckets(auth_profile="DEFAULT", compartment_ocid=compartment_ocid)

        assert result == ["bucket1", "bucket2"]
        mock_get_buckets.assert_called_once_with(compartment_ocid, config)

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_buckets")
    async def test_oci_list_buckets_raises_on_oci_exception(self, mock_get_buckets, mock_oci_get, make_oci_config):
        """oci_list_buckets should raise HTTPException on OciException."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_buckets.side_effect = OciException(status_code=404, detail="Bucket not found")
        compartment_ocid = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_list_buckets(auth_profile="DEFAULT", compartment_ocid=compartment_ocid)

        assert exc_info.value.status_code == 404


class TestOciListBucketObjects:
    """Tests for the oci_list_bucket_objects endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_bucket_objects")
    async def test_oci_list_bucket_objects_success(self, mock_get_objects, mock_oci_get, make_oci_config):
        """oci_list_bucket_objects should return list of objects."""
        config = make_oci_config()
        mock_oci_get.return_value = config
        mock_get_objects.return_value = ["file1.pdf", "file2.txt"]

        result = await oci.oci_list_bucket_objects(auth_profile="DEFAULT", bucket_name="my-bucket")

        assert result == ["file1.pdf", "file2.txt"]
        mock_get_objects.assert_called_once_with("my-bucket", config)

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_bucket_objects")
    async def test_oci_list_bucket_objects_raises_on_oci_exception(
        self, mock_get_objects, mock_oci_get, make_oci_config
    ):
        """oci_list_bucket_objects should raise HTTPException on OciException."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_objects.side_effect = OciException(status_code=403, detail="Access denied")

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_list_bucket_objects(auth_profile="DEFAULT", bucket_name="my-bucket")

        assert exc_info.value.status_code == 403


class TestOciProfileUpdate:
    """Tests for the oci_profile_update endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_namespace")
    async def test_oci_profile_update_success(self, mock_get_namespace, mock_oci_get, make_oci_config):
        """oci_profile_update should update and return config."""
        config = make_oci_config(auth_profile="DEFAULT")
        mock_oci_get.return_value = config
        mock_get_namespace.return_value = "test-namespace"

        payload = make_oci_config(auth_profile="DEFAULT", genai_region="us-phoenix-1")

        result = await oci.oci_profile_update(auth_profile="DEFAULT", payload=payload)

        assert result.namespace == "test-namespace"
        assert result.genai_region == "us-phoenix-1"

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_oci.get_namespace")
    async def test_oci_profile_update_raises_on_oci_exception(self, mock_get_namespace, mock_oci_get, make_oci_config):
        """oci_profile_update should raise HTTPException on OciException."""
        config = make_oci_config()
        mock_oci_get.return_value = config
        mock_get_namespace.side_effect = OciException(status_code=401, detail="Invalid credentials")

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_profile_update(auth_profile="DEFAULT", payload=make_oci_config())

        assert exc_info.value.status_code == 401
        assert config.namespace is None


class TestOciDownloadObjects:
    """Tests for the oci_download_objects endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_embed.get_temp_directory")
    @patch("server.api.v1.oci.utils_oci.get_object")
    async def test_oci_download_objects_success(
        self, mock_get_object, mock_get_temp_dir, mock_oci_get, make_oci_config, tmp_path
    ):
        """oci_download_objects should download files and return list."""
        config = make_oci_config()
        mock_oci_get.return_value = config
        mock_get_temp_dir.return_value = tmp_path

        # Create test files
        (tmp_path / "file1.pdf").touch()
        (tmp_path / "file2.txt").touch()

        result = await oci.oci_download_objects(
            bucket_name="my-bucket",
            auth_profile="DEFAULT",
            request=["file1.pdf", "file2.txt"],
            client="test_client",
        )

        assert result.status_code == 200
        assert mock_get_object.call_count == 2


class TestOciCreateGenaiModels:
    """Tests for the oci_create_genai_models endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_models.create_genai")
    async def test_oci_create_genai_models_success(self, mock_create_genai, mock_oci_get, make_oci_config, make_model):
        """oci_create_genai_models should create and return models."""
        config = make_oci_config()
        mock_oci_get.return_value = config
        models_list = [make_model(model_id="cohere.command", provider="oci")]
        mock_create_genai.return_value = models_list

        result = await oci.oci_create_genai_models(auth_profile="DEFAULT")

        assert result == models_list
        mock_create_genai.assert_called_once_with(config)

    @pytest.mark.asyncio
    @patch("server.api.v1.oci.oci_get")
    @patch("server.api.v1.oci.utils_models.create_genai")
    async def test_oci_create_genai_models_raises_on_oci_exception(
        self, mock_create_genai, mock_oci_get, make_oci_config
    ):
        """oci_create_genai_models should raise HTTPException on OciException."""
        mock_oci_get.return_value = make_oci_config()
        mock_create_genai.side_effect = OciException(status_code=500, detail="GenAI service error")

        with pytest.raises(HTTPException) as exc_info:
            await oci.oci_create_genai_models(auth_profile="DEFAULT")

        assert exc_info.value.status_code == 500
