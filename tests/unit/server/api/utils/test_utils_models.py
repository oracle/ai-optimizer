"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/models.py
Tests for model utility functions.
"""

# pylint: disable=too-few-public-methods

from unittest.mock import patch, MagicMock
import pytest

from server.api.utils import models as utils_models
from server.api.utils.models import (
    URLUnreachableError,
    InvalidModelError,
    ExistsModelError,
    UnknownModelError,
)


class TestExceptions:
    """Tests for custom exception classes."""

    def test_url_unreachable_error_is_value_error(self):
        """URLUnreachableError should inherit from ValueError."""
        exc = URLUnreachableError("URL unreachable")
        assert isinstance(exc, ValueError)

    def test_invalid_model_error_is_value_error(self):
        """InvalidModelError should inherit from ValueError."""
        exc = InvalidModelError("Invalid model")
        assert isinstance(exc, ValueError)

    def test_exists_model_error_is_value_error(self):
        """ExistsModelError should inherit from ValueError."""
        exc = ExistsModelError("Model exists")
        assert isinstance(exc, ValueError)

    def test_unknown_model_error_is_value_error(self):
        """UnknownModelError should inherit from ValueError."""
        exc = UnknownModelError("Model not found")
        assert isinstance(exc, ValueError)


class TestCreate:
    """Tests for the create function."""

    @patch("server.api.utils.models.get")
    @patch("server.api.utils.models.MODEL_OBJECTS", [])
    def test_create_success(self, mock_get, make_model):
        """create should add model to MODEL_OBJECTS."""
        model = make_model(model_id="gpt-4", provider="openai")
        mock_get.side_effect = [UnknownModelError("Not found"), (model,)]

        result = utils_models.create(model)

        assert result == model

    @patch("server.api.utils.models.get")
    def test_create_raises_exists_error(self, mock_get, make_model):
        """create should raise ExistsModelError if model exists."""
        model = make_model(model_id="gpt-4", provider="openai")
        mock_get.return_value = [model]

        with pytest.raises(ExistsModelError):
            utils_models.create(model)

    @patch("server.api.utils.models.get")
    @patch("server.api.utils.models.is_url_accessible")
    @patch("server.api.utils.models.MODEL_OBJECTS", [])
    def test_create_disables_model_if_url_inaccessible(self, mock_url_check, mock_get, make_model):
        """create should disable model if API base URL is inaccessible."""
        model = make_model(model_id="custom", provider="openai")
        model.api_base = "https://unreachable.example.com"
        mock_get.side_effect = [UnknownModelError("Not found"), (model,)]
        mock_url_check.return_value = (False, "Connection refused")

        result = utils_models.create(model, check_url=True)

        assert result.enabled is False


class TestGet:
    """Tests for the get function."""

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_all_models(self, mock_objects, make_model):
        """get should return all models when no filters."""
        model1 = make_model(model_id="gpt-4", provider="openai")
        model2 = make_model(model_id="claude-3", provider="anthropic")
        mock_objects.__iter__ = lambda _: iter([model1, model2])
        mock_objects.__len__ = lambda _: 2

        result = utils_models.get()

        assert len(result) == 2

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_by_provider(self, mock_objects, make_model):
        """get should filter by provider."""
        model1 = make_model(model_id="gpt-4", provider="openai")
        model2 = make_model(model_id="claude-3", provider="anthropic")
        mock_objects.__iter__ = lambda _: iter([model1, model2])
        mock_objects.__len__ = lambda _: 2

        result = utils_models.get(model_provider="openai")

        assert len(result) == 1
        assert result[0].provider == "openai"

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_by_type(self, mock_objects, make_model):
        """get should filter by type."""
        model1 = make_model(model_id="gpt-4", model_type="ll")
        model2 = make_model(model_id="embed-3", model_type="embed")
        mock_objects.__iter__ = lambda _: iter([model1, model2])
        mock_objects.__len__ = lambda _: 2

        result = utils_models.get(model_type="embed")

        assert len(result) == 1
        assert result[0].type == "embed"

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_exclude_disabled(self, mock_objects, make_model):
        """get should exclude disabled models when include_disabled=False."""
        model1 = make_model(model_id="gpt-4", enabled=True)
        model2 = make_model(model_id="gpt-3", enabled=False)
        mock_objects.__iter__ = lambda _: iter([model1, model2])
        mock_objects.__len__ = lambda _: 2

        result = utils_models.get(include_disabled=False)

        assert len(result) == 1
        assert result[0].enabled is True

    @patch("server.api.utils.models.MODEL_OBJECTS")
    def test_get_raises_unknown_error(self, mock_objects):
        """get should raise UnknownModelError if model_id not found."""
        mock_objects.__iter__ = lambda _: iter([])
        mock_objects.__len__ = lambda _: 0

        with pytest.raises(UnknownModelError):
            utils_models.get(model_id="nonexistent")


class TestUpdate:
    """Tests for the update function."""

    @patch("server.api.utils.models.get")
    @patch("server.api.utils.models.is_url_accessible")
    def test_update_success(self, mock_url_check, mock_get, make_model):
        """update should update model in place."""
        existing_model = make_model(model_id="gpt-4", provider="openai")
        mock_get.return_value = (existing_model,)
        mock_url_check.return_value = (True, "OK")

        payload = make_model(model_id="gpt-4", provider="openai")
        payload.temperature = 0.9

        result = utils_models.update(payload)

        assert result.temperature == 0.9

    @patch("server.api.utils.models.get")
    @patch("server.api.utils.models.is_url_accessible")
    def test_update_raises_url_unreachable(self, mock_url_check, mock_get, make_model):
        """update should raise URLUnreachableError if URL inaccessible."""
        existing_model = make_model(model_id="gpt-4", provider="openai")
        mock_get.return_value = (existing_model,)
        mock_url_check.return_value = (False, "Connection refused")

        payload = make_model(model_id="gpt-4", provider="openai", enabled=True)
        payload.api_base = "https://unreachable.example.com"

        with pytest.raises(URLUnreachableError):
            utils_models.update(payload)


class TestDelete:
    """Tests for the delete function."""

    def test_delete_removes_model(self, make_model):
        """delete should remove model from MODEL_OBJECTS."""
        model1 = make_model(model_id="gpt-4", provider="openai")
        model2 = make_model(model_id="claude-3", provider="anthropic")

        with patch("server.api.utils.models.MODEL_OBJECTS", [model1, model2]) as mock_objects:
            utils_models.delete("openai", "gpt-4")
            assert len(mock_objects) == 1
            assert mock_objects[0].id == "claude-3"


class TestGetSupported:
    """Tests for the get_supported function."""

    @patch("server.api.utils.models.litellm")
    def test_get_supported_returns_providers(self, mock_litellm):
        """get_supported should return list of providers."""
        mock_provider = MagicMock()
        mock_provider.value = "openai"
        mock_litellm.provider_list = [mock_provider]
        mock_litellm.models_by_provider = {"openai": ["gpt-4"]}
        mock_litellm.get_model_info.return_value = {"mode": "chat", "key": "gpt-4"}
        mock_litellm.get_llm_provider.return_value = ("openai", None, None, "https://api.openai.com/v1")

        result = utils_models.get_supported()

        assert len(result) >= 1
        assert result[0]["provider"] == "openai"

    @patch("server.api.utils.models.litellm")
    def test_get_supported_filters_by_provider(self, mock_litellm):
        """get_supported should filter by provider."""
        mock_provider1 = MagicMock()
        mock_provider1.value = "openai"
        mock_provider2 = MagicMock()
        mock_provider2.value = "anthropic"
        mock_litellm.provider_list = [mock_provider1, mock_provider2]
        mock_litellm.models_by_provider = {"openai": [], "anthropic": []}

        result = utils_models.get_supported(model_provider="anthropic")

        assert len(result) == 1
        assert result[0]["provider"] == "anthropic"


class TestCreateGenai:
    """Tests for the create_genai function."""

    @patch("server.api.utils.models.utils_oci.get_genai_models")
    @patch("server.api.utils.models.get")
    @patch("server.api.utils.models.delete")
    @patch("server.api.utils.models.create")
    def test_create_genai_creates_models(self, mock_create, _mock_delete, mock_get, mock_get_genai, make_oci_config):
        """create_genai should create GenAI models."""
        mock_get_genai.return_value = [
            {"model_name": "cohere.command-r", "capabilities": ["CHAT"]},
            {"model_name": "cohere.embed-v3", "capabilities": ["TEXT_EMBEDDINGS"]},
        ]
        mock_get.return_value = []

        config = make_oci_config(genai_region="us-chicago-1")
        config.genai_compartment_id = "ocid1.compartment.oc1..test"

        utils_models.create_genai(config)

        assert mock_create.call_count == 2

    @patch("server.api.utils.models.utils_oci.get_genai_models")
    def test_create_genai_returns_empty_when_no_models(self, mock_get_genai, make_oci_config):
        """create_genai should return empty list when no models."""
        mock_get_genai.return_value = []

        config = make_oci_config(genai_region="us-chicago-1")

        result = utils_models.create_genai(config)

        assert not result


class TestGetFullConfig:  # pylint: disable=protected-access
    """Tests for the _get_full_config function."""

    @patch("server.api.utils.models.get")
    def test_get_full_config_success(self, mock_get, make_model):
        """_get_full_config should merge model config with defined model."""
        defined_model = make_model(model_id="gpt-4", provider="openai")
        defined_model.api_base = "https://api.openai.com/v1"
        mock_get.return_value = (defined_model,)

        model_config = {"model": "openai/gpt-4", "temperature": 0.9}

        full_config, provider = utils_models._get_full_config(model_config, None)

        assert provider == "openai"
        assert full_config["temperature"] == 0.9
        assert full_config["api_base"] == "https://api.openai.com/v1"

    @patch("server.api.utils.models.get")
    def test_get_full_config_raises_unknown_model(self, mock_get):
        """_get_full_config should raise UnknownModelError if not found."""
        mock_get.side_effect = UnknownModelError("Model not found")

        model_config = {"model": "openai/nonexistent"}

        with pytest.raises(UnknownModelError):
            utils_models._get_full_config(model_config, None)


class TestGetLitellmConfig:
    """Tests for the get_litellm_config function."""

    @patch("server.api.utils.models._get_full_config")
    @patch("server.api.utils.models.litellm.get_supported_openai_params")
    def test_get_litellm_config_basic(self, mock_get_params, mock_get_full):
        """get_litellm_config should return LiteLLM config."""
        mock_get_full.return_value = (
            {"model": "openai/gpt-4", "temperature": 0.7, "api_base": "https://api.openai.com/v1"},
            "openai",
        )
        mock_get_params.return_value = ["temperature", "max_tokens"]

        model_config = {"model": "openai/gpt-4"}

        result = utils_models.get_litellm_config(model_config, None)

        assert result["model"] == "openai/gpt-4"
        assert result["drop_params"] is True

    @patch("server.api.utils.models._get_full_config")
    @patch("server.api.utils.models.litellm.get_supported_openai_params")
    @patch("server.api.utils.models.utils_oci.get_signer")
    def test_get_litellm_config_oci_provider(self, mock_get_signer, mock_get_params, mock_get_full, make_oci_config):
        """get_litellm_config should include OCI params for OCI provider."""
        mock_get_full.return_value = (
            {
                "model": "oci/cohere.command-r",
                "api_base": "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com",
            },
            "oci",
        )
        mock_get_params.return_value = ["temperature"]
        mock_get_signer.return_value = None  # API key auth

        oci_config = make_oci_config(genai_region="us-chicago-1")
        oci_config.genai_compartment_id = "ocid1.compartment.oc1..test"
        oci_config.tenancy = "test-tenancy"
        oci_config.user = "test-user"
        oci_config.fingerprint = "test-fingerprint"
        oci_config.key_file = "/path/to/key"

        model_config = {"model": "oci/cohere.command-r"}

        result = utils_models.get_litellm_config(model_config, oci_config)

        assert result["oci_region"] == "us-chicago-1"
        assert result["oci_compartment_id"] == "ocid1.compartment.oc1..test"


    @patch("server.api.utils.models._get_full_config")
    @patch("server.api.utils.models.litellm.get_supported_openai_params")
    def test_get_litellm_config_giskard_includes_max_chunk_size(self, mock_get_params, mock_get_full):
        """get_litellm_config should include max_chunk_size when giskard=True."""
        mock_get_full.return_value = (
            {
                "model": "openai/text-embedding-3-small",
                "type": "embed",
                "max_chunk_size": 8192,
                "api_base": "https://api.openai.com/v1",
            },
            "openai",
        )
        mock_get_params.return_value = ["temperature"]

        model_config = {"model": "openai/text-embedding-3-small"}

        result = utils_models.get_litellm_config(model_config, None, giskard=True)

        assert result["max_chunk_size"] == 8192

    @patch("server.api.utils.models._get_full_config")
    @patch("server.api.utils.models.litellm.get_supported_openai_params")
    def test_get_litellm_config_giskard_ll_renames_model_to_llm_model(self, mock_get_params, mock_get_full):
        """get_litellm_config should rename model to llm_model for ll type when giskard=True."""
        mock_get_full.return_value = (
            {
                "model": "openai/gpt-4",
                "type": "ll",
                "api_base": "https://api.openai.com/v1",
            },
            "openai",
        )
        mock_get_params.return_value = ["temperature"]

        model_config = {"model": "openai/gpt-4"}

        result = utils_models.get_litellm_config(model_config, None, giskard=True)

        assert "llm_model" in result
        assert "model" not in result

    @patch("server.api.utils.models._get_full_config")
    @patch("server.api.utils.models.litellm.get_supported_openai_params")
    def test_get_litellm_config_ollama_embed_keeps_ollama_prefix(self, mock_get_params, mock_get_full):
        """get_litellm_config should NOT replace ollama/ with ollama_chat/ for embed models."""
        mock_get_full.return_value = (
            {
                "model": "ollama/mxbai-embed-large",
                "type": "embed",
                "max_chunk_size": 512,
                "api_base": "http://localhost:11434",
            },
            "ollama",
        )
        mock_get_params.return_value = []

        model_config = {"model": "ollama/mxbai-embed-large"}

        result = utils_models.get_litellm_config(model_config, None)

        assert result["model"] == "ollama/mxbai-embed-large"
        assert "ollama_chat" not in result["model"]

    @patch("server.api.utils.models._get_full_config")
    @patch("server.api.utils.models.litellm.get_supported_openai_params")
    def test_get_litellm_config_ollama_ll_uses_ollama_chat(self, mock_get_params, mock_get_full):
        """get_litellm_config should replace ollama/ with ollama_chat/ for ll models."""
        mock_get_full.return_value = (
            {
                "model": "ollama/llama3",
                "type": "ll",
                "api_base": "http://localhost:11434",
            },
            "ollama",
        )
        mock_get_params.return_value = []

        model_config = {"model": "ollama/llama3"}

        result = utils_models.get_litellm_config(model_config, None)

        assert result["model"] == "ollama_chat/llama3"


class TestGetClientEmbed:
    """Tests for the get_client_embed function."""

    @patch("server.api.utils.models._get_full_config")
    @patch("server.api.utils.models.utils_oci.init_genai_client")
    @patch("server.api.utils.models.OCIGenAIEmbeddings")
    def test_get_client_embed_oci(self, mock_embeddings, mock_init_client, mock_get_full, make_oci_config):
        """get_client_embed should return OCIGenAIEmbeddings for OCI provider."""
        mock_get_full.return_value = ({"id": "cohere.embed-v3"}, "oci")
        mock_init_client.return_value = MagicMock()
        mock_embeddings.return_value = MagicMock()

        oci_config = make_oci_config()
        oci_config.genai_compartment_id = "ocid1.compartment.oc1..test"

        model_config = {"model": "oci/cohere.embed-v3"}

        utils_models.get_client_embed(model_config, oci_config)

        mock_embeddings.assert_called_once()

    @patch("server.api.utils.models._get_full_config")
    @patch("server.api.utils.models.init_embeddings")
    def test_get_client_embed_openai(self, mock_init_embeddings, mock_get_full, make_oci_config):
        """get_client_embed should use init_embeddings for non-OCI providers."""
        mock_get_full.return_value = (
            {"id": "text-embedding-3-small", "api_base": "https://api.openai.com/v1"},
            "openai",
        )
        mock_init_embeddings.return_value = MagicMock()

        oci_config = make_oci_config()
        model_config = {"model": "openai/text-embedding-3-small"}

        utils_models.get_client_embed(model_config, oci_config)

        mock_init_embeddings.assert_called_once()


class TestProcessModelEntry:  # pylint: disable=protected-access
    """Tests for the _process_model_entry function."""

    @patch("server.api.utils.models.litellm")
    def test_process_model_entry_success(self, mock_litellm):
        """_process_model_entry should return model dict."""
        mock_litellm.get_model_info.return_value = {"mode": "chat", "key": "gpt-4"}
        mock_litellm.get_llm_provider.return_value = ("openai", None, None, "https://api.openai.com/v1")

        type_to_modes = {"ll": {"chat"}}
        allowed_modes = {"chat"}

        result = utils_models._process_model_entry("gpt-4", type_to_modes, allowed_modes, "openai")

        assert result is not None
        assert result["type"] == "ll"

    @patch("server.api.utils.models.litellm")
    def test_process_model_entry_filters_mode(self, mock_litellm):
        """_process_model_entry should return None for unsupported modes."""
        mock_litellm.get_model_info.return_value = {"mode": "moderation"}

        type_to_modes = {"ll": {"chat"}}
        allowed_modes = {"chat"}

        result = utils_models._process_model_entry("mod-model", type_to_modes, allowed_modes, "openai")

        assert result is None

    @patch("server.api.utils.models.litellm")
    def test_process_model_entry_handles_exception(self, mock_litellm):
        """_process_model_entry should handle exceptions gracefully."""
        mock_litellm.get_model_info.side_effect = Exception("API error")

        type_to_modes = {"ll": {"chat"}}
        allowed_modes = {"chat"}

        result = utils_models._process_model_entry("bad-model", type_to_modes, allowed_modes, "openai")

        assert result == {"key": "bad-model"}
