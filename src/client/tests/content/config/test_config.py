"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.config.config
"""
# spell-checker: disable

from unittest.mock import patch

import pytest

from client.tests.conftest import make_mock_tabs

MODULE = "client.app.content.config.config"

pytestmark = pytest.mark.unit


class TestConfigMain:
    """Tests for config.main()."""

    def test_creates_six_tabs(self, mock_st):
        """Creates six tabs and calls all display functions."""
        mock_st.tabs.return_value = make_mock_tabs(6)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.display_settings") as mock_settings,
            patch(f"{MODULE}.display_databases") as mock_db,
            patch(f"{MODULE}.display_models") as mock_models,
            patch(f"{MODULE}.display_oci") as mock_oci,
            patch(f"{MODULE}.display_mcp") as mock_mcp,
            patch(f"{MODULE}.display_agentspec") as mock_agentspec,
        ):
            from client.app.content.config.config import main

            main()

        mock_st.tabs.assert_called_once()
        assert len(mock_st.tabs.call_args[0][0]) == 6
        mock_settings.assert_called_once()
        mock_db.assert_called_once()
        mock_models.assert_called_once()
        mock_oci.assert_called_once()
        mock_mcp.assert_called_once()
        mock_agentspec.assert_called_once()

    def test_no_tabs_when_empty(self, mock_st):
        """Verify main() still works with the tab list (always has 6 items)."""
        mock_st.tabs.return_value = make_mock_tabs(6)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.display_settings"),
            patch(f"{MODULE}.display_databases"),
            patch(f"{MODULE}.display_models"),
            patch(f"{MODULE}.display_oci"),
            patch(f"{MODULE}.display_mcp"),
            patch(f"{MODULE}.display_agentspec"),
        ):
            from client.app.content.config.config import main

            main()  # Should not raise
