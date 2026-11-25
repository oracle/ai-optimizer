"""Tests for the sign-out navigation page."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_signout_page_signs_out_and_returns_to_chat():
    module_path = "client.app.content.signout"
    streamlit = MagicMock()
    sys.modules.pop(module_path, None)
    with patch("streamlit.switch_page", streamlit.switch_page), patch("client.app.core.auth.sign_out") as sign_out:
        try:
            importlib.import_module(module_path)
        finally:
            sys.modules.pop(module_path, None)

    sign_out.assert_called_once_with()
    streamlit.switch_page.assert_called_once_with("content/chatbot.py")
