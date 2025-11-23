"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

import streamlit.components.v1 as components
from client.utils.st_footer import render_chat_footer


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    # Streamlit File path
    ST_FILE = "../src/client/utils/st_footer.py"

    def test_chat_page_disclaimer(self, app_server, app_test, monkeypatch):
        """Verify disclaimer appears on chat page"""
        assert app_server is not None

        # Mock components.html to capture rendered content
        def mock_html(html, **_kwargs):
            assert "LLMs can make mistakes. Always verify important information." in html

        monkeypatch.setattr(components, "html", mock_html)

        # Initialize app_test and run component
        at = app_test(self.ST_FILE)
        at = at.run()

        # Run the footer rendering
        render_chat_footer()

    def test_disclaimer_absence_on_other_pages(self, app_server, app_test, monkeypatch):
        """Verify disclaimer doesn't appear on non-chat/non-models pages"""
        assert app_server is not None

        # Mock components.html to capture rendered content
        def mock_html(html, **_kwargs):
            assert "LLMs can make mistakes. Always verify important information." not in html

        monkeypatch.setattr(components, "html", mock_html)

        # Initialize app_test and run component
        at = app_test(self.ST_FILE)

        # Mock session state for other page rendering
        at.session_state.current_page = "other"
        at = at.run()

        # Verify disclaimer doesn't appear on other pages
        assert "current_page" in at.session_state
        assert at.session_state.current_page == "other"
