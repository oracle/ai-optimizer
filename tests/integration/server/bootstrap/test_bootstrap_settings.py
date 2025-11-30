"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/bootstrap/settings.py

Tests the settings bootstrap process with real configuration files.
"""

# pylint: disable=redefined-outer-name protected-access too-few-public-methods

import pytest

from server.bootstrap import settings as settings_module
from common.schema import Settings


@pytest.mark.usefixtures("reset_config_store", "clean_bootstrap_env")
class TestSettingsBootstrapWithConfig:
    """Integration tests for settings bootstrap with configuration files."""

    def test_bootstrap_creates_default_and_server_clients(self):
        """settings.main() should always create default and server clients."""
        result = settings_module.main()

        assert len(result) == 2
        client_names = [s.client for s in result]
        assert "default" in client_names
        assert "server" in client_names

    def test_bootstrap_returns_settings_objects(self):
        """settings.main() should return list of Settings objects."""
        result = settings_module.main()

        assert all(isinstance(s, Settings) for s in result)

    def test_bootstrap_with_config_file(self, reset_config_store, make_config_file):
        """settings.main() should use settings from config file."""
        config_path = make_config_file(
            client_settings={
                "client": "config_client",
                "ll_model": {
                    "model": "custom-model",
                    "temperature": 0.9,
                    "max_tokens": 8192,
                    "chat_history": False,
                },
            },
        )

        reset_config_store.load_from_file(config_path)
        result = settings_module.main()

        # All clients should inherit config file settings
        for s in result:
            assert s.ll_model.model == "custom-model"
            assert s.ll_model.temperature == 0.9
            assert s.ll_model.max_tokens == 8192
            assert s.ll_model.chat_history is False

    def test_bootstrap_overrides_client_names(self, reset_config_store, make_config_file):
        """settings.main() should override client field to default/server."""
        config_path = make_config_file(
            client_settings={
                "client": "original_client_name",
            },
        )

        reset_config_store.load_from_file(config_path)
        result = settings_module.main()

        client_names = [s.client for s in result]
        assert "original_client_name" not in client_names
        assert "default" in client_names
        assert "server" in client_names

    def test_bootstrap_with_vector_search_settings(self, reset_config_store, make_config_file):
        """settings.main() should load vector search settings from config."""
        config_path = make_config_file(
            client_settings={
                "client": "vs_client",
                "vector_search": {
                    "discovery": False,
                    "rephrase": False,
                    "grade": True,
                    "top_k": 10,
                    "search_type": "Similarity",
                },
            },
        )

        reset_config_store.load_from_file(config_path)
        result = settings_module.main()

        for s in result:
            assert s.vector_search.discovery is False
            assert s.vector_search.rephrase is False
            assert s.vector_search.grade is True
            assert s.vector_search.top_k == 10

    def test_bootstrap_with_oci_settings(self, reset_config_store, make_config_file):
        """settings.main() should load OCI settings from config."""
        config_path = make_config_file(
            client_settings={
                "client": "oci_client",
                "oci": {
                    "auth_profile": "CUSTOM_PROFILE",
                },
            },
        )

        reset_config_store.load_from_file(config_path)
        result = settings_module.main()

        for s in result:
            assert s.oci.auth_profile == "CUSTOM_PROFILE"

    def test_bootstrap_with_database_settings(self, reset_config_store, make_config_file):
        """settings.main() should load database settings from config."""
        config_path = make_config_file(
            client_settings={
                "client": "db_client",
                "database": {
                    "alias": "CUSTOM_DB",
                },
            },
        )

        reset_config_store.load_from_file(config_path)
        result = settings_module.main()

        for s in result:
            assert s.database.alias == "CUSTOM_DB"


@pytest.mark.usefixtures("clean_bootstrap_env")
class TestSettingsBootstrapWithoutConfig:
    """Integration tests for settings bootstrap without configuration."""

    def test_bootstrap_without_config_uses_defaults(self, reset_config_store):
        """settings.main() should use default values without config file."""
        # Ensure no config is loaded
        assert reset_config_store.get() is None

        result = settings_module.main()

        assert len(result) == 2
        # Should have default Settings values
        for s in result:
            assert isinstance(s, Settings)
            # Default values from Settings model
            assert s.oci.auth_profile == "DEFAULT"
            assert s.database.alias == "DEFAULT"


@pytest.mark.usefixtures("clean_bootstrap_env")
class TestSettingsBootstrapIdempotency:
    """Integration tests for settings bootstrap idempotency."""

    def test_bootstrap_produces_consistent_results(self, reset_config_store):
        """settings.main() should produce consistent results on multiple calls."""
        result1 = settings_module.main()

        # Reset and call again
        reset_config_store._config = None
        result2 = settings_module.main()

        assert len(result1) == len(result2)
        for s1, s2 in zip(result1, result2):
            assert s1.client == s2.client
