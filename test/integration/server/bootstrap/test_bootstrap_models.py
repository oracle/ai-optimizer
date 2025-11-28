"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/bootstrap/models.py

Tests the models bootstrap process with real configuration files
and environment variables.
"""

# pylint: disable=redefined-outer-name

import os
from unittest.mock import patch

import pytest

from server.bootstrap import models as models_module
from common.schema import Model


@pytest.mark.usefixtures("reset_config_store", "clean_bootstrap_env")
class TestModelsBootstrapBasic:
    """Integration tests for basic models bootstrap functionality."""

    def test_bootstrap_returns_model_objects(self):
        """models.main() should return list of Model objects."""
        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")
            result = models_module.main()

        assert isinstance(result, list)
        assert all(isinstance(m, Model) for m in result)

    def test_bootstrap_includes_base_models(self):
        """models.main() should include base model configurations."""
        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")
            result = models_module.main()

        model_ids = [m.id for m in result]
        # Check for some expected base models
        assert "gpt-4o-mini" in model_ids
        assert "command-r" in model_ids

    def test_bootstrap_includes_ll_and_embed_models(self):
        """models.main() should include both LLM and embedding models."""
        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")
            result = models_module.main()

        model_types = {m.type for m in result}
        assert "ll" in model_types
        assert "embed" in model_types


@pytest.mark.usefixtures("reset_config_store", "clean_bootstrap_env")
class TestModelsBootstrapWithApiKeys:
    """Integration tests for models bootstrap with API keys."""

    def test_bootstrap_enables_models_with_openai_key(self):
        """models.main() should enable OpenAI models when key is present."""
        os.environ["OPENAI_API_KEY"] = "test-openai-key"

        try:
            with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
                mock_accessible.return_value = (True, "OK")
                result = models_module.main()

            openai_model = next(m for m in result if m.id == "gpt-4o-mini")
            assert openai_model.enabled is True
            assert openai_model.api_key == "test-openai-key"
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_bootstrap_enables_models_with_cohere_key(self):
        """models.main() should enable Cohere models when key is present."""
        os.environ["COHERE_API_KEY"] = "test-cohere-key"

        try:
            with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
                mock_accessible.return_value = (True, "OK")
                result = models_module.main()

            cohere_model = next(m for m in result if m.id == "command-r")
            assert cohere_model.enabled is True
            assert cohere_model.api_key == "test-cohere-key"
        finally:
            del os.environ["COHERE_API_KEY"]

    def test_bootstrap_disables_models_without_keys(self):
        """models.main() should disable models when API keys are not present."""
        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")
            result = models_module.main()

        # Without OPENAI_API_KEY, the model should be disabled
        openai_model = next(m for m in result if m.id == "gpt-4o-mini")
        assert openai_model.enabled is False


@pytest.mark.usefixtures("reset_config_store", "clean_bootstrap_env")
class TestModelsBootstrapWithOnPremUrls:
    """Integration tests for models bootstrap with on-prem URLs."""

    def test_bootstrap_enables_ollama_with_url(self):
        """models.main() should enable Ollama models when URL is set."""
        os.environ["ON_PREM_OLLAMA_URL"] = "http://localhost:11434"

        try:
            with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
                mock_accessible.return_value = (True, "OK")
                result = models_module.main()

            ollama_model = next(m for m in result if m.id == "llama3.1")
            assert ollama_model.enabled is True
            assert ollama_model.api_base == "http://localhost:11434"
        finally:
            del os.environ["ON_PREM_OLLAMA_URL"]

    def test_bootstrap_checks_url_accessibility(self):
        """models.main() should check URL accessibility for enabled models."""
        os.environ["ON_PREM_OLLAMA_URL"] = "http://localhost:11434"

        try:
            with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
                mock_accessible.return_value = (False, "Connection refused")
                result = models_module.main()

            ollama_model = next(m for m in result if m.id == "llama3.1")
            # Should be disabled if URL is not accessible
            assert ollama_model.enabled is False
        finally:
            del os.environ["ON_PREM_OLLAMA_URL"]


@pytest.mark.usefixtures("clean_bootstrap_env")
class TestModelsBootstrapWithConfigStore:
    """Integration tests for models bootstrap with ConfigStore configuration."""

    def test_bootstrap_merges_config_store_models(self, reset_config_store, make_config_file):
        """models.main() should merge models from ConfigStore."""
        config_path = make_config_file(
            model_configs=[
                {
                    "id": "custom-model",
                    "type": "ll",
                    "provider": "custom",
                    "enabled": True,
                    "api_base": "https://custom.api/v1",
                    "api_key": "custom-key",
                },
            ],
        )

        try:
            reset_config_store.load_from_file(config_path)

            with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
                mock_accessible.return_value = (True, "OK")
                result = models_module.main()

            model_ids = [m.id for m in result]
            assert "custom-model" in model_ids

            custom_model = next(m for m in result if m.id == "custom-model")
            assert custom_model.provider == "custom"
            assert custom_model.api_base == "https://custom.api/v1"
        finally:
            pass

    def test_bootstrap_config_store_overrides_base_model(self, reset_config_store, make_config_file):
        """models.main() should let ConfigStore override base model settings."""
        config_path = make_config_file(
            model_configs=[
                {
                    "id": "gpt-4o-mini",
                    "type": "ll",
                    "provider": "openai",
                    "enabled": True,
                    "api_base": "https://api.openai.com/v1",
                    "api_key": "override-key",
                    "max_tokens": 9999,
                },
            ],
        )

        try:
            reset_config_store.load_from_file(config_path)

            with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
                mock_accessible.return_value = (True, "OK")
                result = models_module.main()

            openai_model = next(m for m in result if m.id == "gpt-4o-mini")
            assert openai_model.api_key == "override-key"
            assert openai_model.max_tokens == 9999
        finally:
            pass


@pytest.mark.usefixtures("clean_bootstrap_env")
class TestModelsBootstrapDuplicateDetection:
    """Integration tests for models bootstrap duplicate detection."""

    def test_bootstrap_deduplicates_config_store_models(self, reset_config_store, make_config_file):
        """models.main() should deduplicate models with same provider+id in ConfigStore.

        Note: ConfigStore models with the same (provider, id) key are deduplicated
        during the merge process (dict keyed by tuple keeps last value).
        This is different from base model duplicate detection which raises an error.
        """
        # Create config with duplicate model (same provider + id)
        config_path = make_config_file(
            model_configs=[
                {
                    "id": "duplicate-model",
                    "type": "ll",
                    "provider": "test",
                    "api_base": "http://test1",
                },
                {
                    "id": "duplicate-model",
                    "type": "ll",
                    "provider": "test",
                    "api_base": "http://test2",
                },
            ],
        )

        reset_config_store.load_from_file(config_path)

        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")
            result = models_module.main()

        # Should have only one model with the duplicate id (last one wins)
        dup_models = [m for m in result if m.id == "duplicate-model"]
        assert len(dup_models) == 1
        # The last entry in the config should win
        assert dup_models[0].api_base == "http://test2"

    def test_bootstrap_allows_same_id_different_provider(self, reset_config_store, make_config_file):
        """models.main() should allow same ID with different providers."""
        config_path = make_config_file(
            model_configs=[
                {
                    "id": "shared-model-name",
                    "type": "ll",
                    "provider": "provider1",
                    "api_base": "http://provider1",
                },
                {
                    "id": "shared-model-name",
                    "type": "ll",
                    "provider": "provider2",
                    "api_base": "http://provider2",
                },
            ],
        )

        reset_config_store.load_from_file(config_path)

        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")
            result = models_module.main()

        # Both should be present
        shared_models = [m for m in result if m.id == "shared-model-name"]
        assert len(shared_models) == 2
        providers = {m.provider for m in shared_models}
        assert providers == {"provider1", "provider2"}
