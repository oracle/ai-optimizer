"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

from unittest.mock import patch, MagicMock

import pytest

from server.api.utils import models
from server.api.utils.models import URLUnreachableError, InvalidModelError, ExistsModelError, UnknownModelError
from common.schema import Model, OracleCloudSettings


#####################################################
# Exceptions
#####################################################
class TestModelsExceptions:
    """Test custom exception classes"""

    def test_url_unreachable_error(self):
        """Test URLUnreachableError exception"""
        error = URLUnreachableError("URL is unreachable")
        assert str(error) == "URL is unreachable"
        assert isinstance(error, ValueError)

    def test_invalid_model_error(self):
        """Test InvalidModelError exception"""
        error = InvalidModelError("Invalid model data")
        assert str(error) == "Invalid model data"
        assert isinstance(error, ValueError)

    def test_exists_model_error(self):
        """Test ExistsModelError exception"""
        error = ExistsModelError("Model already exists")
        assert str(error) == "Model already exists"
        assert isinstance(error, ValueError)

    def test_unknown_model_error(self):
        """Test UnknownModelError exception"""
        error = UnknownModelError("Model not found")
        assert str(error) == "Model not found"
        assert isinstance(error, ValueError)


#####################################################
# CRUD Functions
#####################################################
class TestModelsCRUD:
    """Test models module functionality"""

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_model = Model(
            id="test-model", provider="openai", type="ll", enabled=True, api_base="https://api.openai.com"
        )
        self.disabled_model = Model(id="disabled-model", provider="anthropic", type="ll", enabled=False)

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_model_all_models(self, mock_model_objects):
        """Test getting all models without filters"""
        mock_model_objects.__iter__ = MagicMock(return_value=iter([self.sample_model, self.disabled_model]))
        mock_model_objects.__len__ = MagicMock(return_value=2)

        result = models.get()

        assert result == [self.sample_model, self.disabled_model]

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_model_by_id_found(self, mock_model_objects):
        """Test getting model by ID when it exists"""
        mock_model_objects.__iter__ = MagicMock(return_value=iter([self.sample_model]))
        mock_model_objects.__len__ = MagicMock(return_value=1)

        (result,) = models.get(model_id="test-model")

        assert result == self.sample_model

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_model_by_id_not_found(self, mock_model_objects):
        """Test getting model by ID when it doesn't exist"""
        mock_model_objects.__iter__ = MagicMock(return_value=iter([self.sample_model]))
        mock_model_objects.__len__ = MagicMock(return_value=1)

        with pytest.raises(UnknownModelError, match="nonexistent not found"):
            models.get(model_id="nonexistent")

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_model_by_provider(self, mock_model_objects):
        """Test filtering models by provider"""
        all_models = [self.sample_model, self.disabled_model]
        mock_model_objects.__iter__ = MagicMock(return_value=iter(all_models))
        mock_model_objects.__len__ = MagicMock(return_value=len(all_models))

        (result,) = models.get(model_provider="openai")

        # Since only one model matches provider="openai", it will return a list of single model
        assert result == self.sample_model

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_model_by_type(self, mock_model_objects):
        """Test filtering models by type"""
        all_models = [self.sample_model, self.disabled_model]
        mock_model_objects.__iter__ = MagicMock(return_value=iter(all_models))
        mock_model_objects.__len__ = MagicMock(return_value=len(all_models))

        result = models.get(model_type="ll")

        assert result == all_models

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_model_exclude_disabled(self, mock_model_objects):
        """Test excluding disabled models"""
        all_models = [self.sample_model, self.disabled_model]
        mock_model_objects.__iter__ = MagicMock(return_value=iter(all_models))
        mock_model_objects.__len__ = MagicMock(return_value=len(all_models))

        (result,) = models.get(include_disabled=False)
        assert result == self.sample_model

    @patch("server.api.utils.models.MODEL_OBJECTS", [])
    @patch("server.api.utils.models.is_url_accessible")
    def test_create_model_success(self, mock_url_check):
        """Test successful model creation"""
        mock_url_check.return_value = (True, None)

        result = models.create(self.sample_model)

        assert result == self.sample_model
        assert result in models.MODEL_OBJECTS

    @patch("server.api.utils.models.MODEL_OBJECTS")
    @patch("server.api.utils.models.get")
    def test_create_model_already_exists(self, mock_get_model, _mock_model_objects):
        """Test creating model that already exists"""
        mock_get_model.return_value = self.sample_model  # Model already exists

        with pytest.raises(ExistsModelError, match="Model: openai/test-model already exists"):
            models.create(self.sample_model)

    @patch("server.api.utils.models.MODEL_OBJECTS", [])
    @patch("server.api.utils.models.is_url_accessible")
    def test_create_model_unreachable_url(self, mock_url_check):
        """Test creating model with unreachable URL"""
        # Create a model that starts as enabled
        test_model = Model(
            id="test-model",
            provider="openai",
            type="ll",
            enabled=True,  # Start as enabled
            api_base="https://api.openai.com",
        )

        mock_url_check.return_value = (False, "Connection failed")

        result = models.create(test_model)

        assert result.enabled is False

    @patch("server.api.utils.models.MODEL_OBJECTS", [])
    def test_create_model_skip_url_check(self):
        """Test creating model without URL check"""
        result = models.create(self.sample_model, check_url=False)

        assert result == self.sample_model
        assert result in models.MODEL_OBJECTS

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_delete_model(self, mock_model_objects):
        """Test model deletion"""
        test_models = [
            Model(id="test-model", provider="openai", type="ll"),
            Model(id="other-model", provider="anthropic", type="ll"),
        ]
        mock_model_objects.__setitem__ = MagicMock()
        mock_model_objects.__iter__ = MagicMock(return_value=iter(test_models))

        models.delete("openai", "test-model")

        # Verify the slice assignment was called
        mock_model_objects.__setitem__.assert_called_once()

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(models, "logger")
        assert models.logger.name == "api.utils.models"


#####################################################
# Utility Functions
#####################################################
class TestModelsUtils:
    """Test models utility functions"""

    def setup_method(self):
        """Setup test data"""
        self.sample_model = Model(
            id="test-model", provider="openai", type="ll", enabled=True, api_base="https://api.openai.com"
        )
        self.sample_oci_config = OracleCloudSettings(
            auth_profile="DEFAULT",
            compartment_id="ocid1.compartment.oc1..test",
            genai_region="us-ashburn-1",
            user="ocid1.user.oc1..testuser",
            fingerprint="test-fingerprint",
            tenancy="ocid1.tenancy.oc1..testtenant",
            key_file="/path/to/key.pem",
        )

    @patch("server.api.utils.models.MODEL_OBJECTS", [])
    @patch("server.api.utils.models.is_url_accessible")
    def test_update_success(self, mock_url_check):
        """Test successful model update"""
        # First create the model
        models.MODEL_OBJECTS.append(self.sample_model)
        mock_url_check.return_value = (True, None)

        update_payload = Model(
            id="test-model",
            provider="openai",
            type="ll",
            enabled=True,
            api_base="https://api.openai.com",
            temperature=0.8,
        )

        result = models.update(update_payload)

        assert result.temperature == 0.8

    @patch("server.api.utils.models.MODEL_OBJECTS", [])
    @patch("server.api.utils.models.is_url_accessible")
    def test_update_embedding_model_max_chunk_size(self, mock_url_check):
        """Test updating max_chunk_size for embedding model (regression test for bug)"""
        # Create an embedding model with default max_chunk_size
        embed_model = Model(
            id="test-embed-model",
            provider="ollama",
            type="embed",
            enabled=True,
            api_base="http://127.0.0.1:11434",
            max_chunk_size=8192,
        )
        models.MODEL_OBJECTS.append(embed_model)
        mock_url_check.return_value = (True, None)

        # Update the max_chunk_size to 512
        update_payload = Model(
            id="test-embed-model",
            provider="ollama",
            type="embed",
            enabled=True,
            api_base="http://127.0.0.1:11434",
            max_chunk_size=512,
        )

        result = models.update(update_payload)

        # Verify the update was successful
        assert result.max_chunk_size == 512
        assert result.id == "test-embed-model"
        assert result.provider == "ollama"

        # Verify the model in MODEL_OBJECTS was updated
        (updated_model,) = models.get(model_provider="ollama", model_id="test-embed-model")
        assert updated_model.max_chunk_size == 512

    @patch("server.api.utils.models.MODEL_OBJECTS", [])
    @patch("server.api.utils.models.is_url_accessible")
    def test_update_multiple_fields(self, mock_url_check):
        """Test updating multiple fields at once"""
        # Create a model
        models.MODEL_OBJECTS.append(self.sample_model)
        mock_url_check.return_value = (True, None)

        # Update multiple fields
        update_payload = Model(
            id="test-model",
            provider="openai",
            type="ll",
            enabled=False,  # Changed from True
            api_base="https://api.openai.com/v2",  # Changed
            temperature=0.5,  # Changed
            max_tokens=2048,  # Changed
        )

        result = models.update(update_payload)

        assert result.enabled is False
        assert result.api_base == "https://api.openai.com/v2"
        assert result.temperature == 0.5
        assert result.max_tokens == 2048

    @patch("server.api.utils.models.get")
    def test_get_full_config_success(self, mock_get_model):
        """Test successful full config retrieval"""
        mock_get_model.return_value = [self.sample_model]
        model_config = {"model": "openai/gpt-4", "temperature": 0.8}

        full_config, provider = models._get_full_config(model_config, self.sample_oci_config)

        assert provider == "openai"
        assert full_config["temperature"] == 0.8
        assert full_config["id"] == "test-model"
        mock_get_model.assert_called_once_with(model_provider="openai", model_id="gpt-4", include_disabled=False)

    @patch("server.api.utils.models.get")
    def test_get_full_config_unknown_model(self, mock_get_model):
        """Test full config retrieval with unknown model"""
        mock_get_model.side_effect = UnknownModelError("Model not found")
        model_config = {"model": "unknown/model"}

        with pytest.raises(UnknownModelError):
            models._get_full_config(model_config, self.sample_oci_config)

    @patch("server.api.utils.models._get_full_config")
    @patch("litellm.get_supported_openai_params")
    def test_get_litellm_config_basic(self, mock_get_params, mock_get_full_config):
        """Test basic LiteLLM config generation"""
        mock_get_full_config.return_value = (
            {"temperature": 0.7, "max_tokens": 4096, "api_base": "https://api.openai.com"},
            "openai",
        )
        mock_get_params.return_value = ["temperature", "max_tokens"]
        model_config = {"model": "openai/gpt-4"}

        result = models.get_litellm_config(model_config, self.sample_oci_config)

        assert result["model"] == "openai/gpt-4"
        assert result["temperature"] == 0.7
        assert result["max_tokens"] == 4096
        assert result["drop_params"] is True

    @patch("server.api.utils.models._get_full_config")
    @patch("litellm.get_supported_openai_params")
    def test_get_litellm_config_cohere(self, mock_get_params, mock_get_full_config):
        """Test LiteLLM config generation for Cohere"""
        mock_get_full_config.return_value = ({"api_base": "https://custom.cohere.com/v1"}, "cohere")
        mock_get_params.return_value = []
        model_config = {"model": "cohere/command"}

        result = models.get_litellm_config(model_config, self.sample_oci_config)

        assert result["api_base"] == "https://api.cohere.ai/compatibility/v1"
        assert result["model"] == "cohere/command"

    @patch("server.api.utils.models._get_full_config")
    @patch("litellm.get_supported_openai_params")
    def test_get_litellm_config_xai(self, mock_get_params, mock_get_full_config):
        """Test LiteLLM config generation for xAI"""
        mock_get_full_config.return_value = (
            {"temperature": 0.7, "presence_penalty": 0.1, "frequency_penalty": 0.1},
            "xai",
        )
        mock_get_params.return_value = ["temperature", "presence_penalty", "frequency_penalty"]
        model_config = {"model": "xai/grok"}

        result = models.get_litellm_config(model_config, self.sample_oci_config)

        assert result["temperature"] == 0.7
        assert "presence_penalty" not in result
        assert "frequency_penalty" not in result

    @patch("server.api.utils.models._get_full_config")
    @patch("litellm.get_supported_openai_params")
    def test_get_litellm_config_oci(self, mock_get_params, mock_get_full_config):
        """Test LiteLLM config generation for OCI"""
        mock_get_full_config.return_value = ({"temperature": 0.7}, "oci")
        mock_get_params.return_value = ["temperature"]
        model_config = {"model": "oci/cohere.command"}

        result = models.get_litellm_config(model_config, self.sample_oci_config)

        assert result["oci_user"] == "ocid1.user.oc1..testuser"
        assert result["oci_fingerprint"] == "test-fingerprint"
        assert result["oci_tenancy"] == "ocid1.tenancy.oc1..testtenant"
        assert result["oci_region"] == "us-ashburn-1"
        assert result["oci_key_file"] == "/path/to/key.pem"

    @patch("server.api.utils.models._get_full_config")
    @patch("litellm.get_supported_openai_params")
    def test_get_litellm_config_giskard(self, mock_get_params, mock_get_full_config):
        """Test LiteLLM config generation for Giskard"""
        mock_get_full_config.return_value = ({"temperature": 0.7, "model": "test-model"}, "openai")
        mock_get_params.return_value = ["temperature", "model"]
        model_config = {"model": "openai/gpt-4"}

        result = models.get_litellm_config(model_config, self.sample_oci_config, giskard=True)

        assert "model" not in result
        assert "temperature" not in result

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(models, "logger")
        assert models.logger.name == "api.utils.models"
