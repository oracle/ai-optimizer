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

    def test_creates_three_tabs(self, mock_st, make_state):
        """Creates three tabs and renders only the active (default) tab body."""
        mock_st.tabs.return_value = make_mock_tabs(3)
        state = make_state()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.display_prompt_eng") as mock_pe,
            patch(f"{MODULE}.display_split_embed") as mock_se,
            patch(f"{MODULE}.display_deepsec") as mock_ds,
        ):
            from client.app.content.tools.tools import main

            main()

        mock_st.tabs.assert_called_once()
        assert len(mock_st.tabs.call_args[0][0]) == 3
        # With no tab selected, the default (Prompts) tab is active. Only
        # its body runs; rendering the inactive split/embed body would
        # mount its run_every polling fragment on every tab.
        mock_pe.assert_called_once()
        mock_se.assert_not_called()
        mock_ds.assert_not_called()

    def test_renders_only_active_tab(self, mock_st, make_state):
        """The active tab (tracked via the ``tools_tabs`` widget value)
        determines which display function runs."""
        mock_st.tabs.return_value = make_mock_tabs(3)
        state = make_state(extra={"tools_tabs": "📚 Split/Embed"})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.display_prompt_eng") as mock_pe,
            patch(f"{MODULE}.display_split_embed") as mock_se,
            patch(f"{MODULE}.display_deepsec") as mock_ds,
        ):
            from client.app.content.tools.tools import main

            main()

        mock_pe.assert_not_called()
        mock_se.assert_called_once()
        mock_ds.assert_not_called()

    def test_tab_labels(self, mock_st):
        """Tab labels include Prompts, Split/Embed and Deep Data Security."""
        mock_st.tabs.return_value = make_mock_tabs(3)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.display_prompt_eng"),
            patch(f"{MODULE}.display_split_embed"),
            patch(f"{MODULE}.display_deepsec"),
        ):
            from client.app.content.tools.tools import main

            main()

        tab_labels = mock_st.tabs.call_args[0][0]
        assert "Prompts" in tab_labels[0]
        assert "Split/Embed" in tab_labels[1]
        assert "Deep Data Security" in tab_labels[2]
