"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/bootstrap/configfile.py

Tests the ConfigStore class with real file I/O operations.
"""

# pylint: disable=redefined-outer-name

import json
import os
from pathlib import Path

import pytest

from server.bootstrap.configfile import config_file_path


class TestConfigStoreFileOperations:
    """Integration tests for ConfigStore with real file operations."""

    def test_load_valid_json_file(self, reset_config_store, make_config_file, sample_settings_config):
        """ConfigStore should load a valid JSON configuration file."""
        config_path = make_config_file(
            client_settings=sample_settings_config,
        )

        reset_config_store.load_from_file(config_path)
        config = reset_config_store.get()

        assert config is not None
        assert config.client_settings.client == "integration_client"

    def test_load_file_with_all_sections(
        self,
        reset_config_store,
        make_config_file,
        sample_settings_config,
        sample_database_config,
        sample_model_config,
        sample_oci_config,
    ):
        """ConfigStore should load file with all configuration sections."""
        config_path = make_config_file(
            client_settings=sample_settings_config,
            database_configs=[sample_database_config],
            model_configs=[sample_model_config],
            oci_configs=[sample_oci_config],
        )

        reset_config_store.load_from_file(config_path)
        config = reset_config_store.get()

        assert config is not None
        assert len(config.database_configs) == 1
        assert config.database_configs[0].name == "INTEGRATION_DB"
        assert len(config.model_configs) == 1
        assert config.model_configs[0].id == "integration-model"
        assert len(config.oci_configs) == 1
        assert config.oci_configs[0].auth_profile == "INTEGRATION"

    def test_load_nonexistent_file_returns_none(self, reset_config_store, temp_dir):
        """ConfigStore should handle nonexistent files gracefully."""
        nonexistent_path = temp_dir / "does_not_exist.json"

        reset_config_store.load_from_file(nonexistent_path)
        config = reset_config_store.get()

        assert config is None

    def test_load_file_with_unicode_content(self, reset_config_store, temp_dir):
        """ConfigStore should handle files with unicode content."""
        config_data = {
            "client_settings": {"client": "unicode_test_客户端"},
            "database_configs": [],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
        }

        config_path = temp_dir / "unicode_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False)

        reset_config_store.load_from_file(config_path)
        config = reset_config_store.get()

        assert config is not None
        assert config.client_settings.client == "unicode_test_客户端"

    def test_load_file_with_nested_settings(self, reset_config_store, temp_dir):
        """ConfigStore should handle deeply nested settings."""
        config_data = {
            "client_settings": {
                "client": "nested_test",
                "ll_model": {
                    "model": "gpt-4o-mini",
                    "temperature": 0.5,
                    "max_tokens": 2048,
                    "chat_history": True,
                },
                "vector_search": {
                    "discovery": True,
                    "rephrase": True,
                    "grade": True,
                    "top_k": 5,
                },
            },
            "database_configs": [],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
        }

        config_path = temp_dir / "nested_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f)

        reset_config_store.load_from_file(config_path)
        config = reset_config_store.get()

        assert config is not None
        assert config.client_settings.ll_model.temperature == 0.5
        assert config.client_settings.vector_search.top_k == 5

    def test_load_large_config_file(self, reset_config_store, temp_dir):
        """ConfigStore should handle large configuration files."""
        # Create config with many database entries
        database_configs = [
            {
                "name": f"DB_{i}",
                "user": f"user_{i}",
                "password": f"pass_{i}",
                "dsn": f"host{i}:1521/PDB{i}",
            }
            for i in range(50)
        ]

        config_data = {
            "client_settings": {"client": "large_test"},
            "database_configs": database_configs,
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
        }

        config_path = temp_dir / "large_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f)

        reset_config_store.load_from_file(config_path)
        config = reset_config_store.get()

        assert config is not None
        assert len(config.database_configs) == 50

    def test_load_file_preserves_field_types(self, reset_config_store, temp_dir):
        """ConfigStore should preserve correct field types after loading."""
        config_data = {
            "client_settings": {
                "client": "type_test",
                "ll_model": {
                    "model": "test-model",
                    "temperature": 0.7,  # float
                    "max_tokens": 4096,  # int
                    "chat_history": True,  # bool
                },
            },
            "database_configs": [],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
        }

        config_path = temp_dir / "types_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f)

        reset_config_store.load_from_file(config_path)
        config = reset_config_store.get()

        assert isinstance(config.client_settings.ll_model.temperature, float)
        assert isinstance(config.client_settings.ll_model.max_tokens, int)
        assert isinstance(config.client_settings.ll_model.chat_history, bool)


class TestConfigStoreValidation:
    """Integration tests for ConfigStore validation with real files."""

    def test_load_file_validates_required_fields(self, reset_config_store, temp_dir):
        """ConfigStore should validate required fields in config."""
        # Missing required 'client' field in client_settings
        config_data = {
            "client_settings": {},  # Missing 'client'
            "database_configs": [],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
        }

        config_path = temp_dir / "invalid_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f)

        with pytest.raises(Exception):  # Pydantic ValidationError
            reset_config_store.load_from_file(config_path)

    def test_load_malformed_json_raises_error(self, reset_config_store, temp_dir):
        """ConfigStore should raise error for malformed JSON."""
        config_path = temp_dir / "malformed.json"
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json content }")

        with pytest.raises(json.JSONDecodeError):
            reset_config_store.load_from_file(config_path)


class TestConfigFilePath:
    """Integration tests for config_file_path function."""

    def test_config_file_path_returns_valid_path(self):
        """config_file_path should return a valid filesystem path."""
        path = config_file_path()

        assert path is not None
        assert isinstance(path, str)
        assert path.endswith("configuration.json")

    def test_config_file_path_parent_directory_structure(self):
        """config_file_path should point to server/etc directory."""
        path = config_file_path()
        path_obj = Path(path)

        # Parent should be 'etc' directory
        assert path_obj.parent.name == "etc"
        # Grandparent should be 'server' directory
        assert path_obj.parent.parent.name == "server"

    def test_config_file_path_is_absolute(self):
        """config_file_path should return an absolute path."""
        path = config_file_path()

        assert os.path.isabs(path)
