"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/bootstrap/configfile.py
Tests for ConfigStore class and config_file_path function.
"""

# pylint: disable=redefined-outer-name protected-access too-few-public-methods

import json
import os
import tempfile
from pathlib import Path
from threading import Thread, Barrier

import pytest

from server.bootstrap.configfile import config_file_path


class TestConfigStore:
    """Tests for the ConfigStore class."""

    def test_load_from_file_success(self, reset_config_store, temp_config_file, make_settings):
        """ConfigStore should load configuration from a valid JSON file."""
        settings = make_settings(client="test_client")
        config_path = temp_config_file(client_settings=settings)

        try:
            reset_config_store.load_from_file(config_path)
            config = reset_config_store.get()

            assert config is not None
            assert config.client_settings.client == "test_client"
        finally:
            os.unlink(config_path)

    def test_load_from_file_nonexistent_file(self, reset_config_store):
        """ConfigStore should handle nonexistent files gracefully."""
        nonexistent_path = Path("/nonexistent/path/config.json")

        reset_config_store.load_from_file(nonexistent_path)
        config = reset_config_store.get()

        assert config is None

    def test_load_from_file_wrong_extension_warns(self, reset_config_store, caplog):
        """ConfigStore should warn when file has wrong extension."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as temp_file:
            # Need valid client_settings with required 'client' field
            json.dump(
                {
                    "client_settings": {"client": "test"},
                    "database_configs": [],
                    "model_configs": [],
                    "oci_configs": [],
                    "prompt_configs": [],
                },
                temp_file,
            )
            temp_path = Path(temp_file.name)

        try:
            reset_config_store.load_from_file(temp_path)
            assert "should be a .json file" in caplog.text
        finally:
            os.unlink(temp_path)

    def test_load_from_file_only_loads_once(self, reset_config_store, temp_config_file, make_settings):
        """ConfigStore should only load configuration once (singleton pattern)."""
        settings1 = make_settings(client="first_client")
        settings2 = make_settings(client="second_client")

        config_path1 = temp_config_file(client_settings=settings1)
        config_path2 = temp_config_file(client_settings=settings2)

        try:
            reset_config_store.load_from_file(config_path1)
            reset_config_store.load_from_file(config_path2)  # Should be ignored

            config = reset_config_store.get()
            assert config.client_settings.client == "first_client"
        finally:
            os.unlink(config_path1)
            os.unlink(config_path2)

    def test_load_from_file_thread_safety(self, reset_config_store, temp_config_file, make_settings):
        """ConfigStore should handle concurrent loading safely."""
        settings = make_settings(client="thread_test")
        config_path = temp_config_file(client_settings=settings)

        num_threads = 5
        barrier = Barrier(num_threads)
        results = []

        def load_config():
            barrier.wait()  # Synchronize threads
            reset_config_store.load_from_file(config_path)
            results.append(reset_config_store.get())

        try:
            threads = [Thread(target=load_config) for _ in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All threads should see the same config
            assert len(results) == num_threads
            assert all(r is not None for r in results)
            assert all(r.client_settings.client == "thread_test" for r in results)
        finally:
            os.unlink(config_path)

    def test_load_from_file_with_database_configs(
        self, reset_config_store, temp_config_file, make_settings, make_database
    ):
        """ConfigStore should load database configurations."""
        settings = make_settings()
        db = make_database(name="TEST_DB", user="admin")
        config_path = temp_config_file(client_settings=settings, database_configs=[db])

        try:
            reset_config_store.load_from_file(config_path)
            config = reset_config_store.get()

            assert config is not None
            assert len(config.database_configs) == 1
            assert config.database_configs[0].name == "TEST_DB"
            assert config.database_configs[0].user == "admin"
        finally:
            os.unlink(config_path)

    def test_load_from_file_with_model_configs(self, reset_config_store, temp_config_file, make_settings, make_model):
        """ConfigStore should load model configurations."""
        settings = make_settings()
        model = make_model(model_id="test-model", provider="openai")
        config_path = temp_config_file(client_settings=settings, model_configs=[model])

        try:
            reset_config_store.load_from_file(config_path)
            config = reset_config_store.get()

            assert config is not None
            assert len(config.model_configs) == 1
            assert config.model_configs[0].id == "test-model"
        finally:
            os.unlink(config_path)

    def test_load_from_file_with_oci_configs(
        self, reset_config_store, temp_config_file, make_settings, make_oci_config
    ):
        """ConfigStore should load OCI configurations."""
        settings = make_settings()
        oci_config = make_oci_config(auth_profile="TEST_PROFILE")
        config_path = temp_config_file(client_settings=settings, oci_configs=[oci_config])

        try:
            reset_config_store.load_from_file(config_path)
            config = reset_config_store.get()

            assert config is not None
            assert len(config.oci_configs) == 1
            assert config.oci_configs[0].auth_profile == "TEST_PROFILE"
        finally:
            os.unlink(config_path)

    def test_load_from_file_invalid_json(self, reset_config_store):
        """ConfigStore should raise error for invalid JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as temp_file:
            temp_file.write("not valid json {")
            temp_path = Path(temp_file.name)

        try:
            with pytest.raises(json.JSONDecodeError):
                reset_config_store.load_from_file(temp_path)
        finally:
            os.unlink(temp_path)

    def test_get_returns_none_when_not_loaded(self, reset_config_store):
        """ConfigStore.get() should return None when config not loaded."""
        config = reset_config_store.get()
        assert config is None


class TestConfigFilePath:
    """Tests for the config_file_path function."""

    def test_config_file_path_returns_string(self):
        """config_file_path should return a string path."""
        path = config_file_path()
        assert isinstance(path, str)

    def test_config_file_path_ends_with_json(self):
        """config_file_path should return a .json file path."""
        path = config_file_path()
        assert path.endswith(".json")

    def test_config_file_path_contains_etc_directory(self):
        """config_file_path should include etc directory."""
        path = config_file_path()
        assert "etc" in path
        assert "configuration.json" in path

    def test_config_file_path_is_absolute(self):
        """config_file_path should return an absolute path."""
        path = config_file_path()
        assert os.path.isabs(path)

    def test_config_file_path_parent_is_server_directory(self):
        """config_file_path should be relative to server directory."""
        path = config_file_path()
        path_obj = Path(path)
        # Should be under server/etc/configuration.json
        assert path_obj.parent.name == "etc"
