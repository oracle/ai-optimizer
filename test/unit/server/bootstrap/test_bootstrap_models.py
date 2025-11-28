"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/bootstrap/models.py
Tests for model bootstrap functionality.
"""

# pylint: disable=redefined-outer-name protected-access too-few-public-methods

import os
from unittest.mock import patch

from test.shared_fixtures import assert_model_list_valid, get_model_by_id

import pytest

from server.bootstrap import models as models_module


@pytest.mark.usefixtures("reset_config_store", "clean_env", "mock_is_url_accessible")
class TestModelsMain:
    """Tests for the models.main() function."""

    def test_main_returns_list_of_models(self):
        """main() should return a list of Model objects."""
        result = models_module.main()
        assert_model_list_valid(result)

    def test_main_includes_base_models(self):
        """main() should include base model configurations."""
        result = models_module.main()

        model_ids = [m.id for m in result]
        # Should include at least some base models
        assert "gpt-4o-mini" in model_ids
        assert "command-r" in model_ids

    def test_main_enables_models_with_api_keys(self):
        """main() should enable models when API keys are present."""
        os.environ["OPENAI_API_KEY"] = "test-openai-key"

        try:
            model_list = models_module.main()
            gpt_model = get_model_by_id(model_list, "gpt-4o-mini")
            assert gpt_model.enabled is True
            assert gpt_model.api_key == "test-openai-key"
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_main_disables_models_without_api_keys(self):
        """main() should disable models when API keys are not present."""
        model_list = models_module.main()
        gpt_model = get_model_by_id(model_list, "gpt-4o-mini")
        assert gpt_model.enabled is False

    @pytest.mark.usefixtures("reset_config_store", "clean_env")
    def test_main_checks_url_accessibility(self):
        """main() should check URL accessibility for enabled models."""
        os.environ["OPENAI_API_KEY"] = "test-key"

        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (False, "Connection refused")

            try:
                result = models_module.main()
                openai_model = get_model_by_id(result, "gpt-4o-mini")
                assert openai_model.enabled is False  # Model disabled if URL not accessible
                mock_accessible.assert_called()
            finally:
                del os.environ["OPENAI_API_KEY"]

    @pytest.mark.usefixtures("reset_config_store", "clean_env")
    def test_main_caches_url_accessibility_results(self):
        """main() should cache URL accessibility results for same URLs."""
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["COHERE_API_KEY"] = "test-key"

        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")

            try:
                models_module.main()

                # Multiple models share the same base URL, should only check once per URL
                call_urls = [call[0][0] for call in mock_accessible.call_args_list]
                # Should not have duplicate URL checks
                assert len(call_urls) == len(set(call_urls))
            finally:
                del os.environ["OPENAI_API_KEY"]
                del os.environ["COHERE_API_KEY"]


@pytest.mark.usefixtures("clean_env")
class TestGetBaseModelsList:
    """Tests for the _get_base_models_list function."""

    def test_returns_list_of_dicts(self):
        """_get_base_models_list should return a list of dictionaries."""
        result = models_module._get_base_models_list()

        assert isinstance(result, list)
        assert all(isinstance(m, dict) for m in result)

    def test_includes_required_fields(self):
        """_get_base_models_list should include required fields for each model."""
        result = models_module._get_base_models_list()

        for model in result:
            assert "id" in model
            assert "type" in model
            assert "provider" in model
            assert "api_base" in model

    def test_includes_ll_and_embed_models(self):
        """_get_base_models_list should include both LLM and embedding models."""
        result = models_module._get_base_models_list()

        types = {m["type"] for m in result}
        assert "ll" in types
        assert "embed" in types


class TestCheckForDuplicates:
    """Tests for the _check_for_duplicates function."""

    def test_no_error_for_unique_models(self):
        """_check_for_duplicates should not raise for unique models."""
        models_list = [
            {"id": "model1", "provider": "openai"},
            {"id": "model2", "provider": "openai"},
            {"id": "model1", "provider": "cohere"},  # Same ID, different provider
        ]

        # Should not raise
        models_module._check_for_duplicates(models_list)

    def test_raises_for_duplicate_models(self):
        """_check_for_duplicates should raise ValueError for duplicates."""
        models_list = [
            {"id": "model1", "provider": "openai"},
            {"id": "model1", "provider": "openai"},  # Duplicate
        ]

        with pytest.raises(ValueError, match="already exists"):
            models_module._check_for_duplicates(models_list)


class TestValuesDiffer:
    """Tests for the _values_differ function."""

    def test_bool_comparison(self):
        """_values_differ should handle boolean comparisons."""
        assert models_module._values_differ(True, False) is True
        assert models_module._values_differ(True, True) is False
        assert models_module._values_differ(False, False) is False

    def test_numeric_comparison(self):
        """_values_differ should handle numeric comparisons."""
        assert models_module._values_differ(1, 2) is True
        assert models_module._values_differ(1.0, 1.0) is False
        assert models_module._values_differ(1, 1.0) is False
        # Small float differences should be considered equal
        assert models_module._values_differ(1.0, 1.0 + 1e-9) is False
        assert models_module._values_differ(1.0, 1.1) is True

    def test_string_comparison(self):
        """_values_differ should handle string comparisons with strip."""
        assert models_module._values_differ("test", "test") is False
        assert models_module._values_differ(" test ", "test") is False
        assert models_module._values_differ("test", "other") is True

    def test_general_comparison(self):
        """_values_differ should handle general equality comparison."""
        assert models_module._values_differ([1, 2], [1, 2]) is False
        assert models_module._values_differ([1, 2], [1, 3]) is True
        assert models_module._values_differ(None, None) is False
        assert models_module._values_differ(None, "value") is True


@pytest.mark.usefixtures("reset_config_store")
class TestMergeWithConfigStore:
    """Tests for the _merge_with_config_store function."""

    def test_returns_unchanged_when_no_config(self):
        """_merge_with_config_store should return unchanged list when no config."""
        models_list = [{"id": "model1", "provider": "openai", "enabled": False}]

        result = models_module._merge_with_config_store(models_list)

        assert result == models_list

    def test_merges_config_store_models(
        self, reset_config_store, temp_config_file, make_settings, make_model
    ):
        """_merge_with_config_store should merge models from ConfigStore."""
        settings = make_settings()
        config_model = make_model(model_id="config-model", provider="custom")
        config_path = temp_config_file(client_settings=settings, model_configs=[config_model])

        models_list = [{"id": "existing", "provider": "openai", "enabled": False}]

        try:
            reset_config_store.load_from_file(config_path)
            result = models_module._merge_with_config_store(models_list)

            model_keys = [(m["provider"], m["id"]) for m in result]
            assert ("custom", "config-model") in model_keys
            assert ("openai", "existing") in model_keys
        finally:
            os.unlink(config_path)

    def test_overrides_existing_model_values(
        self, reset_config_store, temp_config_file, make_settings, make_model
    ):
        """_merge_with_config_store should override existing model values."""
        settings = make_settings()
        config_model = make_model(model_id="existing", provider="openai", enabled=True)
        config_path = temp_config_file(client_settings=settings, model_configs=[config_model])

        models_list = [
            {"id": "existing", "provider": "openai", "enabled": False, "api_base": "https://api.openai.com/v1"}
        ]

        try:
            reset_config_store.load_from_file(config_path)
            result = models_module._merge_with_config_store(models_list)

            merged_model = next(m for m in result if m["id"] == "existing")
            assert merged_model["enabled"] is True
        finally:
            os.unlink(config_path)


class ModelDict(dict):
    """Dict subclass that also supports attribute access for 'id'.

    The _update_env_var function in models.py uses both dict-style (.get(), [])
    and attribute-style (.id) access, so tests need objects that support both.
    """

    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")


@pytest.mark.usefixtures("clean_env")
class TestApplyEnvVarOverrides:
    """Tests for the _apply_env_var_overrides function."""

    def test_applies_cohere_api_key(self):
        """_apply_env_var_overrides should apply COHERE_API_KEY."""
        # Use ModelDict to support both dict and attribute access (needed for model.id)
        models_list = [ModelDict({"id": "command-r", "provider": "cohere", "api_key": "original"})]
        os.environ["COHERE_API_KEY"] = "env-key"

        try:
            models_module._apply_env_var_overrides(models_list)

            assert models_list[0]["api_key"] == "env-key"
        finally:
            del os.environ["COHERE_API_KEY"]

    def test_applies_ollama_url(self):
        """_apply_env_var_overrides should apply ON_PREM_OLLAMA_URL."""
        models_list = [ModelDict({"id": "llama3.1", "provider": "ollama", "api_base": "http://localhost:11434"})]
        os.environ["ON_PREM_OLLAMA_URL"] = "http://custom:11434"

        try:
            models_module._apply_env_var_overrides(models_list)

            assert models_list[0]["api_base"] == "http://custom:11434"
        finally:
            del os.environ["ON_PREM_OLLAMA_URL"]

    def test_does_not_apply_to_wrong_provider(self):
        """_apply_env_var_overrides should not apply overrides to wrong provider."""
        models_list = [ModelDict({"id": "gpt-4o-mini", "provider": "openai", "api_key": "original"})]
        os.environ["COHERE_API_KEY"] = "env-key"

        try:
            models_module._apply_env_var_overrides(models_list)

            assert models_list[0]["api_key"] == "original"
        finally:
            del os.environ["COHERE_API_KEY"]


@pytest.mark.usefixtures("clean_env")
class TestUpdateEnvVar:
    """Tests for the _update_env_var function.

    Note: _update_env_var uses dict-style access (.get(), []) but also accesses
    model.id directly for logging. Use ModelDict for compatibility.
    """

    def test_updates_matching_provider(self):
        """_update_env_var should update model when provider matches."""
        model = ModelDict({"id": "gpt-4o-mini", "provider": "openai", "api_key": "old"})
        os.environ["TEST_KEY"] = "new"

        try:
            models_module._update_env_var(model, "openai", "api_key", "TEST_KEY")

            assert model["api_key"] == "new"
        finally:
            del os.environ["TEST_KEY"]

    def test_ignores_non_matching_provider(self):
        """_update_env_var should not update when provider doesn't match."""
        model = ModelDict({"id": "command-r", "provider": "cohere", "api_key": "old"})
        os.environ["TEST_KEY"] = "new"

        try:
            models_module._update_env_var(model, "openai", "api_key", "TEST_KEY")

            assert model["api_key"] == "old"
        finally:
            del os.environ["TEST_KEY"]

    def test_ignores_when_env_var_not_set(self):
        """_update_env_var should not update when env var is not set."""
        model = ModelDict({"id": "gpt-4o-mini", "provider": "openai", "api_key": "old"})

        models_module._update_env_var(model, "openai", "api_key", "NONEXISTENT_VAR")

        assert model["api_key"] == "old"

    def test_ignores_when_value_unchanged(self):
        """_update_env_var should not update when value is the same."""
        model = ModelDict({"id": "gpt-4o-mini", "provider": "openai", "api_key": "same"})
        os.environ["TEST_KEY"] = "same"

        try:
            models_module._update_env_var(model, "openai", "api_key", "TEST_KEY")

            assert model["api_key"] == "same"
        finally:
            del os.environ["TEST_KEY"]


@pytest.mark.usefixtures("clean_env")
class TestCheckUrlAccessibility:
    """Tests for the _check_url_accessibility function."""

    def test_disables_inaccessible_urls(self):
        """_check_url_accessibility should disable models with inaccessible URLs."""
        models_list = [{"id": "test", "api_base": "http://localhost:1234", "enabled": True}]

        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (False, "Connection refused")

            models_module._check_url_accessibility(models_list)

            assert models_list[0]["enabled"] is False

    def test_keeps_accessible_urls_enabled(self):
        """_check_url_accessibility should keep models with accessible URLs enabled."""
        models_list = [{"id": "test", "api_base": "http://localhost:1234", "enabled": True}]

        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")

            models_module._check_url_accessibility(models_list)

            assert models_list[0]["enabled"] is True

    def test_skips_disabled_models(self):
        """_check_url_accessibility should skip models that are already disabled."""
        models_list = [{"id": "test", "api_base": "http://localhost:1234", "enabled": False}]

        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            models_module._check_url_accessibility(models_list)

            mock_accessible.assert_not_called()

    def test_caches_url_results(self):
        """_check_url_accessibility should cache results for the same URL."""
        models_list = [
            {"id": "test1", "api_base": "http://localhost:1234", "enabled": True},
            {"id": "test2", "api_base": "http://localhost:1234", "enabled": True},
        ]

        with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
            mock_accessible.return_value = (True, "OK")

            models_module._check_url_accessibility(models_list)

            # Should only be called once for the shared URL
            assert mock_accessible.call_count == 1


@pytest.mark.usefixtures("reset_config_store", "clean_env", "mock_is_url_accessible")
class TestModelsMainAsScript:
    """Tests for running models module as script."""

    def test_main_callable_directly(self):
        """main() should be callable when running as script."""
        result = models_module.main()
        assert result is not None


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured in models module."""
        assert hasattr(models_module, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert models_module.logger.name == "bootstrap.models"
