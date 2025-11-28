"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access import-error import-outside-toplevel

from unittest.mock import patch, MagicMock, mock_open
import os

import pytest

from server.api.utils import settings
from common.schema import Settings, Configuration, Database, Model, OracleCloudSettings


#####################################################
# Helper functions for test data
#####################################################
def make_default_settings():
    """Create default settings for tests"""
    return Settings(client="default")


def make_test_client_settings():
    """Create test client settings for tests"""
    return Settings(client="test_client")


def make_sample_config_data():
    """Create sample configuration data for tests"""
    return {
        "database_configs": [{"name": "test_db", "user": "user", "password": "pass", "dsn": "dsn"}],
        "model_configs": [{"id": "test-model", "provider": "openai", "type": "ll"}],
        "oci_configs": [{"auth_profile": "DEFAULT", "compartment_id": "ocid1.compartment.oc1..test"}],
        "prompt_overrides": {"optimizer_basic-default": "You are helpful"},
        "client_settings": {"client": "default", "max_tokens": 1000, "temperature": 0.7},
    }


#####################################################
# Client Settings Tests
#####################################################
class TestClientSettings:
    """Test client settings CRUD operations"""

    # test_create_client_success: See test/unit/server/api/utils/test_utils_settings.py::TestCreateClient::test_create_client_success
    # test_create_client_already_exists: See test/unit/server/api/utils/test_utils_settings.py::TestCreateClient::test_create_client_raises_on_existing
    # test_get_client_found: See test/unit/server/api/utils/test_utils_settings.py::TestGetClient::test_get_client_success
    # test_get_client_not_found: See test/unit/server/api/utils/test_utils_settings.py::TestGetClient::test_get_client_raises_on_not_found
    # test_update_client: See test/unit/server/api/utils/test_utils_settings.py::TestUpdateClient::test_update_client_success
    pass


#####################################################
# Server Configuration Tests
#####################################################
class TestServerConfiguration:
    """Test server configuration operations"""

    # test_get_server: See test/unit/server/api/utils/test_utils_settings.py::TestGetServer::test_get_server_returns_config
    # test_update_server: See test/unit/server/api/utils/test_utils_settings.py::TestUpdateServer::test_update_server_updates_databases

    @patch("server.api.utils.settings.bootstrap")
    def test_update_server_mutates_lists_not_replaces(self, mock_bootstrap):
        """Test that update_server mutates existing lists rather than replacing them.

        This is critical because other modules import these lists directly
        (e.g., `from server.bootstrap.bootstrap import DATABASE_OBJECTS`).
        If we replace the list, those modules would hold stale references.
        """
        original_db_list = []
        original_model_list = []
        original_oci_list = []

        mock_bootstrap.DATABASE_OBJECTS = original_db_list
        mock_bootstrap.MODEL_OBJECTS = original_model_list
        mock_bootstrap.OCI_OBJECTS = original_oci_list

        settings.update_server(make_sample_config_data())

        # Verify the lists are the SAME objects (mutated, not replaced)
        assert mock_bootstrap.DATABASE_OBJECTS is original_db_list, "DATABASE_OBJECTS was replaced instead of mutated"
        assert mock_bootstrap.MODEL_OBJECTS is original_model_list, "MODEL_OBJECTS was replaced instead of mutated"
        assert mock_bootstrap.OCI_OBJECTS is original_oci_list, "OCI_OBJECTS was replaced instead of mutated"

        # Verify the lists now contain the new data
        assert len(original_db_list) == 1
        assert original_db_list[0].name == "test_db"
        assert len(original_model_list) == 1
        assert original_model_list[0].id == "test-model"
        assert len(original_oci_list) == 1
        assert original_oci_list[0].auth_profile == "DEFAULT"


#####################################################
# Config Loading Tests
#####################################################
class TestConfigLoading:
    """Test configuration loading operations"""

    # test_load_config_from_json_data_with_client: See test/unit/server/api/utils/test_utils_settings.py::TestLoadConfigFromJsonData::test_load_config_from_json_data_with_client
    # test_load_config_from_json_data_without_client: See test/unit/server/api/utils/test_utils_settings.py::TestLoadConfigFromJsonData::test_load_config_from_json_data_without_client
    # test_load_config_from_json_data_missing_client_settings: See test/unit/server/api/utils/test_utils_settings.py::TestLoadConfigFromJsonData::test_load_config_from_json_data_raises_missing_settings
    # test_read_config_from_json_file_success: See test/unit/server/api/utils/test_utils_settings.py::TestReadConfigFromJsonFile::test_read_config_from_json_file_success
    # test_read_config_from_json_file_not_exists: Empty test stub - not implemented
    # test_read_config_from_json_file_wrong_extension: Empty test stub - not implemented
    # test_logger_exists: See test/unit/server/api/utils/test_utils_settings.py::TestLoggerConfiguration::test_logger_exists
    pass


#####################################################
# Prompt Override Tests
#####################################################
class TestPromptOverrides:
    """Test prompt override operations"""

    # test_load_prompt_override_with_text: See test/unit/server/api/utils/test_utils_settings.py::TestLoadPromptOverride::test_load_prompt_override_with_text
    # test_load_prompt_override_without_text: See test/unit/server/api/utils/test_utils_settings.py::TestLoadPromptOverride::test_load_prompt_override_without_text

    @patch("server.api.utils.settings.cache")
    def test_load_prompt_override_empty_text(self, mock_cache):
        """Test loading prompt override when text is empty string"""
        prompt = {"name": "optimizer_test-prompt", "text": ""}

        result = settings._load_prompt_override(prompt)

        assert result is False
        mock_cache.set_override.assert_not_called()

    # test_load_prompt_configs_success: See test/unit/server/api/utils/test_utils_settings.py::TestLoadPromptConfigs::test_load_prompt_configs_with_prompts
    # test_load_prompt_configs_no_prompts_key: See test/unit/server/api/utils/test_utils_settings.py::TestLoadPromptConfigs::test_load_prompt_configs_without_key
    # test_load_prompt_configs_empty_list: See test/unit/server/api/utils/test_utils_settings.py::TestLoadPromptConfigs::test_load_prompt_configs_empty_list
