"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

import importlib
from unittest.mock import patch, MagicMock

from server.bootstrap import bootstrap


class TestBootstrap:
    """Test bootstrap module functionality"""

    @patch("server.bootstrap.databases.main")
    @patch("server.bootstrap.models.main")
    @patch("server.bootstrap.oci.main")
    @patch("server.bootstrap.settings.main")
    def test_module_imports_and_initialization(
        self, mock_settings, mock_oci, mock_models, mock_databases
    ):
        """Test that all bootstrap objects are properly initialized"""
        # Mock return values
        mock_databases.return_value = [MagicMock()]
        mock_models.return_value = [MagicMock()]
        mock_oci.return_value = [MagicMock()]
        mock_settings.return_value = [MagicMock()]

        # Reload the module to trigger initialization

        importlib.reload(bootstrap)

        # Verify all bootstrap functions were called
        mock_databases.assert_called_once()
        mock_models.assert_called_once()
        mock_oci.assert_called_once()
        mock_settings.assert_called_once()

        # Verify objects are created
        assert hasattr(bootstrap, "DATABASE_OBJECTS")
        assert hasattr(bootstrap, "MODEL_OBJECTS")
        assert hasattr(bootstrap, "OCI_OBJECTS")
        assert hasattr(bootstrap, "SETTINGS_OBJECTS")

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(bootstrap, "logger")
        assert bootstrap.logger.name == "bootstrap"
