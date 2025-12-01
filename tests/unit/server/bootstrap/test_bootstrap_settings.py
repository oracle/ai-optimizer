"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/bootstrap/settings.py
Tests for settings bootstrap functionality.
"""

# pylint: disable=redefined-outer-name protected-access too-few-public-methods

import os
from unittest.mock import patch, MagicMock

import pytest

from server.bootstrap import settings as settings_module
from common.schema import Settings


@pytest.mark.usefixtures("reset_config_store")
class TestSettingsMain:
    """Tests for the settings.main() function."""

    def test_main_returns_list_of_settings(self):
        """main() should return a list of Settings objects."""
        result = settings_module.main()

        assert isinstance(result, list)
        assert all(isinstance(s, Settings) for s in result)

    def test_main_creates_default_and_server_clients(self):
        """main() should create settings for 'default' and 'server' clients."""
        result = settings_module.main()

        client_names = [s.client for s in result]
        assert "default" in client_names
        assert "server" in client_names
        assert len(result) == 2

    def test_main_without_config_uses_default_settings(self):
        """main() should use default Settings when no config is loaded."""
        result = settings_module.main()

        # Both should have default Settings values
        for s in result:
            assert isinstance(s, Settings)
            assert s.client in ["default", "server"]

    def test_main_with_config_uses_config_settings(self, reset_config_store, temp_config_file, make_settings):
        """main() should use config file settings when available."""
        # Create settings with custom values
        custom_settings = make_settings(client="config_client")
        custom_settings.ll_model.temperature = 0.9
        custom_settings.ll_model.max_tokens = 8192

        config_path = temp_config_file(client_settings=custom_settings)

        try:
            reset_config_store.load_from_file(config_path)
            result = settings_module.main()

            # Both clients should inherit from config settings
            for s in result:
                assert s.ll_model.temperature == 0.9
                assert s.ll_model.max_tokens == 8192
                # Client name should be overridden to default/server
                assert s.client in ["default", "server"]
        finally:
            os.unlink(config_path)

    def test_main_preserves_client_names_from_base_list(self, reset_config_store, temp_config_file, make_settings):
        """main() should override client field from config with base client names."""
        custom_settings = make_settings(client="original_name")
        config_path = temp_config_file(client_settings=custom_settings)

        try:
            reset_config_store.load_from_file(config_path)
            result = settings_module.main()

            # Client names should be "default" and "server", not "original_name"
            client_names = [s.client for s in result]
            assert "original_name" not in client_names
            assert "default" in client_names
            assert "server" in client_names
        finally:
            os.unlink(config_path)

    def test_main_with_config_but_no_client_settings(self, reset_config_store):
        """main() should use default Settings when config has no client_settings."""
        mock_config = MagicMock()
        mock_config.client_settings = None

        with patch.object(reset_config_store, "get", return_value=mock_config):
            result = settings_module.main()

            assert len(result) == 2
            assert all(isinstance(s, Settings) for s in result)

    def test_main_creates_copies_with_different_clients(self, reset_config_store, temp_config_file, make_settings):
        """main() should create separate Settings objects with unique client names.

        Note: Pydantic's model_copy() creates shallow copies by default,
        so nested objects (like ll_model) may be shared. However, the top-level
        Settings objects should be distinct with their own 'client' values.
        """
        custom_settings = make_settings(client="config_client")
        config_path = temp_config_file(client_settings=custom_settings)

        try:
            reset_config_store.load_from_file(config_path)
            result = settings_module.main()

            # The Settings objects themselves should be distinct
            assert result[0] is not result[1]
            # And have different client names
            assert result[0].client != result[1].client
            assert result[0].client in ["default", "server"]
            assert result[1].client in ["default", "server"]
        finally:
            os.unlink(config_path)


@pytest.mark.usefixtures("reset_config_store")
class TestSettingsMainAsScript:
    """Tests for running settings module as script."""

    def test_main_callable_directly(self):
        """main() should be callable when running as script."""
        # This tests the if __name__ == "__main__" block indirectly
        result = settings_module.main()
        assert result is not None
