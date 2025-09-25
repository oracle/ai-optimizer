"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch

import pytest

from server.api.utils import models
from server.api.core.models import UnknownModelError
from common.schema import Model, OracleCloudSettings


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

    @patch("server.api.core.models.get_model")
    @patch("common.functions.is_url_accessible")
    def test_update_success(self, mock_url_check, mock_get_model):
        """Test successful model update"""
        mock_get_model.return_value = self.sample_model
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
        mock_get_model.assert_called_once_with(model_provider="openai", model_id="test-model")

    @patch("server.api.core.models.get_model")
    def test_get_full_config_success(self, mock_get_model):
        """Test successful full config retrieval"""
        mock_get_model.return_value = self.sample_model
        model_config = {"model": "openai/gpt-4", "temperature": 0.8}

        full_config, provider = models._get_full_config(model_config, self.sample_oci_config)

        assert provider == "openai"
        assert full_config["temperature"] == 0.8
        assert full_config["id"] == "test-model"
        mock_get_model.assert_called_once_with(model_provider="openai", model_id="gpt-4", include_disabled=False)

    @patch("server.api.core.models.get_model")
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
            {"temperature": 0.7, "max_completion_tokens": 4096, "api_base": "https://api.openai.com"},
            "openai",
        )
        mock_get_params.return_value = ["temperature", "max_completion_tokens"]
        model_config = {"model": "openai/gpt-4"}

        result = models.get_litellm_config(model_config, self.sample_oci_config)

        assert result["model"] == "openai/gpt-4"
        assert result["temperature"] == 0.7
        assert result["max_completion_tokens"] == 4096
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
