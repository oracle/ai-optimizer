"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/bootstrap/bootstrap.py
Tests for the main bootstrap module that coordinates all bootstrap operations.
"""

# pylint: disable=redefined-outer-name protected-access too-few-public-methods
# pylint: disable=import-outside-toplevel

import importlib
from unittest.mock import patch

from server.bootstrap import bootstrap


class TestBootstrapModule:
    """Tests for the bootstrap module initialization."""

    def test_database_objects_is_list(self):
        """DATABASE_OBJECTS should be a list."""
        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = []
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = []
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = []
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = []

                        # Reload to trigger module-level code with mocks
                        importlib.reload(bootstrap)

                        assert isinstance(bootstrap.DATABASE_OBJECTS, list)

    def test_model_objects_is_list(self):
        """MODEL_OBJECTS should be a list."""
        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = []
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = []
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = []
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = []

                        importlib.reload(bootstrap)

                        assert isinstance(bootstrap.MODEL_OBJECTS, list)

    def test_oci_objects_is_list(self):
        """OCI_OBJECTS should be a list."""
        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = []
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = []
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = []
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = []

                        importlib.reload(bootstrap)

                        assert isinstance(bootstrap.OCI_OBJECTS, list)

    def test_settings_objects_is_list(self):
        """SETTINGS_OBJECTS should be a list."""
        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = []
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = []
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = []
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = []

                        importlib.reload(bootstrap)

                        assert isinstance(bootstrap.SETTINGS_OBJECTS, list)

    def test_calls_all_bootstrap_functions(self):
        """Bootstrap module should call all main() functions."""
        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = []
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = []
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = []
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = []

                        importlib.reload(bootstrap)

                        mock_databases.assert_called_once()
                        mock_models.assert_called_once()
                        mock_oci.assert_called_once()
                        mock_settings.assert_called_once()

    def test_stores_database_results(self, make_database):
        """Bootstrap module should store database.main() results."""
        db1 = make_database(name="DB1")
        db2 = make_database(name="DB2")

        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = [db1, db2]
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = []
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = []
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = []

                        importlib.reload(bootstrap)

                        assert len(bootstrap.DATABASE_OBJECTS) == 2
                        assert bootstrap.DATABASE_OBJECTS[0].name == "DB1"

    def test_stores_model_results(self, make_model):
        """Bootstrap module should store models.main() results."""
        model1 = make_model(model_id="model1")
        model2 = make_model(model_id="model2")

        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = []
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = [model1, model2]
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = []
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = []

                        importlib.reload(bootstrap)

                        assert len(bootstrap.MODEL_OBJECTS) == 2

    def test_stores_oci_results(self, make_oci_config):
        """Bootstrap module should store oci.main() results."""
        oci1 = make_oci_config(auth_profile="PROFILE1")
        oci2 = make_oci_config(auth_profile="PROFILE2")

        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = []
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = []
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = [oci1, oci2]
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = []

                        importlib.reload(bootstrap)

                        assert len(bootstrap.OCI_OBJECTS) == 2

    def test_stores_settings_results(self, make_settings):
        """Bootstrap module should store settings.main() results."""
        settings1 = make_settings(client="client1")
        settings2 = make_settings(client="client2")

        with patch("server.bootstrap.databases.main") as mock_databases:
            mock_databases.return_value = []
            with patch("server.bootstrap.models.main") as mock_models:
                mock_models.return_value = []
                with patch("server.bootstrap.oci.main") as mock_oci:
                    mock_oci.return_value = []
                    with patch("server.bootstrap.settings.main") as mock_settings:
                        mock_settings.return_value = [settings1, settings2]

                        importlib.reload(bootstrap)

                        assert len(bootstrap.SETTINGS_OBJECTS) == 2


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured in bootstrap module."""
        assert hasattr(bootstrap, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert bootstrap.logger.name == "bootstrap"
