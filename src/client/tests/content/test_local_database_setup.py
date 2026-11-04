"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the restricted local database setup page.
"""

from unittest.mock import MagicMock, patch

import pytest

MODULE = "client.app.content.local_database_setup"
pytestmark = pytest.mark.unit


def _mock_streamlit(*, submitted: bool, username: str = "AI_OPTIMIZER", password: str = "secret", dsn: str = "dsn"):
    streamlit = MagicMock()
    streamlit.form.return_value.__enter__ = MagicMock()
    streamlit.form.return_value.__exit__ = MagicMock(return_value=False)
    streamlit.text_input.side_effect = [username, password, "", ""]
    streamlit.text_area.return_value = dsn
    streamlit.form_submit_button.return_value = submitted
    return streamlit


def test_unsubmitted_form_does_not_return_configuration():
    streamlit = _mock_streamlit(submitted=False)
    with patch(f"{MODULE}.st", streamlit):
        from client.app.content.local_database_setup import display_local_database_setup

        assert display_local_database_setup() is None


def test_submitted_form_returns_core_configuration():
    streamlit = _mock_streamlit(submitted=True)
    with patch(f"{MODULE}.st", streamlit):
        from client.app.content.local_database_setup import display_local_database_setup

        result = display_local_database_setup()

    assert result is not None
    assert result.username == "AI_OPTIMIZER"
    assert result.password.get_secret_value() == "secret"
    assert result.dsn == "dsn"


def test_incomplete_form_reports_validation_error():
    streamlit = _mock_streamlit(submitted=True, password="", dsn="")
    with patch(f"{MODULE}.st", streamlit):
        from client.app.content.local_database_setup import display_local_database_setup

        assert display_local_database_setup() is None

    streamlit.error.assert_called_once()
