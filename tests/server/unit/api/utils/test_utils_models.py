"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access import-error import-outside-toplevel

from unittest.mock import patch, MagicMock

import pytest

from conftest import get_sample_oci_config
from server.api.utils import models
from server.api.utils.models import URLUnreachableError, InvalidModelError, ExistsModelError, UnknownModelError
from common.schema import Model


#####################################################
# Exceptions
#####################################################
class TestModelsExceptions:
    """Test custom exception classes"""

    # test_url_unreachable_error: See test/unit/server/api/utils/test_utils_models.py::TestExceptions::test_url_unreachable_error_is_value_error
    # test_invalid_model_error: See test/unit/server/api/utils/test_utils_models.py::TestExceptions::test_invalid_model_error_is_value_error
    # test_exists_model_error: See test/unit/server/api/utils/test_utils_models.py::TestExceptions::test_exists_model_error_is_value_error
    # test_unknown_model_error: See test/unit/server/api/utils/test_utils_models.py::TestExceptions::test_unknown_model_error_is_value_error
    pass


#####################################################
# CRUD Functions
#####################################################
class TestModelsCRUD:
    """Test models module functionality"""

    @pytest.fixture
    def sample_model(self):
        """Sample model fixture"""
        return Model(
            id="test-model", provider="openai", type="ll", enabled=True, api_base="https://api.openai.com"
        )

    @pytest.fixture
    def disabled_model(self):
        """Disabled model fixture"""
        return Model(id="disabled-model", provider="anthropic", type="ll", enabled=False)

    # test_get_model_all_models: See test/unit/server/api/utils/test_utils_models.py::TestGet::test_get_all_models

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_model_by_id_found(self, mock_model_objects, sample_model):
        """Test getting model by ID when it exists"""
        mock_model_objects.__iter__ = MagicMock(return_value=iter([sample_model]))
        mock_model_objects.__len__ = MagicMock(return_value=1)

        (result,) = models.get(model_id="test-model")

        assert result == sample_model

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_model_by_id_not_found(self, mock_model_objects, sample_model):
        """Test getting model by ID when it doesn't exist"""
        mock_model_objects.__iter__ = MagicMock(return_value=iter([sample_model]))
        mock_model_objects.__len__ = MagicMock(return_value=1)

        with pytest.raises(UnknownModelError, match="nonexistent not found"):
            models.get(model_id="nonexistent")

    # test_get_model_by_provider: See test/unit/server/api/utils/test_utils_models.py::TestGet::test_get_by_provider
    # test_get_model_by_type: See test/unit/server/api/utils/test_utils_models.py::TestGet::test_get_by_type
    # test_get_model_exclude_disabled: See test/unit/server/api/utils/test_utils_models.py::TestGet::test_get_exclude_disabled

    # test_create_model_success: See test/unit/server/api/utils/test_utils_models.py::TestCreate::test_create_success
    # test_create_model_already_exists: See test/unit/server/api/utils/test_utils_models.py::TestCreate::test_create_raises_exists_error

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
    def test_create_model_skip_url_check(self, sample_model):
        """Test creating model without URL check"""
        result = models.create(sample_model, check_url=False)

        assert result == sample_model
        assert result in models.MODEL_OBJECTS

    # test_delete_model: See test/unit/server/api/utils/test_utils_models.py::TestDelete::test_delete_removes_model
    # test_logger_exists: See test/unit/server/api/utils/test_utils_models.py::TestLoggerConfiguration::test_logger_exists
    pass


#####################################################
# Utility Functions
#####################################################
class TestModelsUtils:
    """Test models utility functions"""

    @pytest.fixture
    def sample_model(self):
        """Sample model fixture"""
        return Model(
            id="test-model", provider="openai", type="ll", enabled=True, api_base="https://api.openai.com"
        )

    @pytest.fixture
    def sample_oci_config(self):
        """Sample OCI config fixture"""
        return get_sample_oci_config()

    # test_update_success: See test/unit/server/api/utils/test_utils_models.py::TestUpdate::test_update_success

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
    def test_update_multiple_fields(self, mock_url_check, sample_model):
        """Test updating multiple fields at once"""
        # Create a model
        models.MODEL_OBJECTS.append(sample_model)
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

    # test_get_full_config_success: See test/unit/server/api/utils/test_utils_models.py::TestGetFullConfig::test_get_full_config_success
    # test_get_full_config_unknown_model: See test/unit/server/api/utils/test_utils_models.py::TestGetFullConfig::test_get_full_config_raises_unknown_model
    # test_get_litellm_config_basic: See test/unit/server/api/utils/test_utils_models.py::TestGetLitellmConfig::test_get_litellm_config_basic

    @patch("server.api.utils.models._get_full_config")
    @patch("litellm.get_supported_openai_params")
    def test_get_litellm_config_cohere(self, mock_get_params, mock_get_full_config, sample_oci_config):
        """Test LiteLLM config generation for Cohere"""
        mock_get_full_config.return_value = ({"api_base": "https://custom.cohere.com/v1"}, "cohere")
        mock_get_params.return_value = []
        model_config = {"model": "cohere/command"}

        result = models.get_litellm_config(model_config, sample_oci_config)

        assert result["api_base"] == "https://api.cohere.ai/compatibility/v1"
        assert result["model"] == "cohere/command"

    @patch("server.api.utils.models._get_full_config")
    @patch("litellm.get_supported_openai_params")
    def test_get_litellm_config_xai(self, mock_get_params, mock_get_full_config, sample_oci_config):
        """Test LiteLLM config generation for xAI"""
        mock_get_full_config.return_value = (
            {"temperature": 0.7, "presence_penalty": 0.1, "frequency_penalty": 0.1},
            "xai",
        )
        mock_get_params.return_value = ["temperature", "presence_penalty", "frequency_penalty"]
        model_config = {"model": "xai/grok"}

        result = models.get_litellm_config(model_config, sample_oci_config)

        assert result["temperature"] == 0.7
        assert "presence_penalty" not in result
        assert "frequency_penalty" not in result

    # test_get_litellm_config_oci: See test/unit/server/api/utils/test_utils_models.py::TestGetLitellmConfig::test_get_litellm_config_oci_provider

    @patch("server.api.utils.models._get_full_config")
    @patch("litellm.get_supported_openai_params")
    def test_get_litellm_config_giskard(self, mock_get_params, mock_get_full_config, sample_oci_config):
        """Test LiteLLM config generation for Giskard"""
        mock_get_full_config.return_value = ({"temperature": 0.7, "model": "test-model"}, "openai")
        mock_get_params.return_value = ["temperature", "model"]
        model_config = {"model": "openai/gpt-4"}

        result = models.get_litellm_config(model_config, sample_oci_config, giskard=True)

        assert "model" not in result
        assert "temperature" not in result

    # test_logger_exists: See test/unit/server/api/utils/test_utils_models.py::TestLoggerConfiguration::test_logger_exists
