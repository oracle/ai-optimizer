"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.tools.tools
"""
# spell-checker: disable

from unittest.mock import patch

import pytest

from client.tests.conftest import make_mock_tabs

MODULE = "client.app.content.tools.tools"

pytestmark = pytest.mark.unit


class TestToolsMain:
    """Tests for tools.main()."""

    def test_creates_two_tabs(self, mock_st):
        """Creates two tabs and calls both display functions."""
        mock_st.tabs.return_value = make_mock_tabs(2)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.display_prompt_eng") as mock_pe,
            patch(f"{MODULE}.display_split_embed") as mock_se,
        ):
            from client.app.content.tools.tools import main

            main()

        mock_st.tabs.assert_called_once()
        assert len(mock_st.tabs.call_args[0][0]) == 2
        mock_pe.assert_called_once()
        mock_se.assert_called_once()

    def test_tab_labels(self, mock_st):
        """Tab labels include Prompts and Split/Embed."""
        mock_st.tabs.return_value = make_mock_tabs(2)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.display_prompt_eng"),
            patch(f"{MODULE}.display_split_embed"),
        ):
            from client.app.content.tools.tools import main

            main()

        tab_labels = mock_st.tabs.call_args[0][0]
        assert "Prompts" in tab_labels[0]
        assert "Split/Embed" in tab_labels[1]
