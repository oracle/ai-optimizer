# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for api_call module - focusing on graceful error handling when
API server is disconnected or returns errors.
"""
# spell-checker: disable

from unittest.mock import MagicMock
import requests


#############################################################################
# Test Graceful Error Handling on Server Errors
#############################################################################
class TestGracefulErrorHandling:
    """Test that API call functions handle server errors gracefully."""

    def test_get_handles_http_500_gracefully(self, app_server, monkeypatch):
        """Test that get() handles HTTP 500 errors gracefully without raising."""
        assert app_server is not None

        from client.utils import api_call
        import streamlit as st

        # Mock the requests.get to raise HTTPError with 500 status
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.return_value = {"detail": "Internal Server Error"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        mock_get = MagicMock(return_value=mock_response)
        monkeypatch.setattr(requests, "get", mock_get)

        # Mock st.error to capture error display
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call get() - should NOT raise, should return error dict and show error
        result = api_call.get(endpoint="v1/test", retries=0)

        # Should return error dict (not raise)
        assert "error" in result

        # Should have shown error to user
        assert mock_error.called

    def test_delete_handles_http_500_gracefully(self, app_server, monkeypatch):
        """Test that delete() handles HTTP 500 errors gracefully without raising."""
        assert app_server is not None

        from client.utils import api_call
        import streamlit as st

        # Mock the requests.delete to raise HTTPError with 500 status
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.return_value = {"detail": "Internal Server Error"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        mock_delete = MagicMock(return_value=mock_response)
        monkeypatch.setattr(requests, "delete", mock_delete)

        # Mock st.error to capture error display
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call delete() - should NOT raise, should return error dict and show error
        result = api_call.delete(endpoint="v1/test", retries=0, toast=False)

        # Should return error dict (not raise)
        assert "error" in result

        # Should have shown error to user
        assert mock_error.called

    def test_post_handles_http_500_gracefully(self, app_server, monkeypatch):
        """Test that post() handles HTTP 500 errors gracefully without raising."""
        assert app_server is not None

        from client.utils import api_call
        import streamlit as st

        # Mock the requests.post to raise HTTPError with 500 status
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.return_value = {"detail": "Internal Server Error"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        mock_post = MagicMock(return_value=mock_response)
        monkeypatch.setattr(requests, "post", mock_post)

        # Mock st.error to capture error display
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call post() - should NOT raise, should return error dict and show error
        result = api_call.post(endpoint="v1/test", retries=0)

        # Should return error dict (not raise)
        assert "error" in result

        # Should have shown error to user
        assert mock_error.called

    def test_patch_handles_http_500_gracefully(self, app_server, monkeypatch):
        """Test that patch() handles HTTP 500 errors gracefully without raising."""
        assert app_server is not None

        from client.utils import api_call
        import streamlit as st

        # Mock the requests.patch to raise HTTPError with 500 status
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.return_value = {"detail": "Internal Server Error"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        mock_patch = MagicMock(return_value=mock_response)
        monkeypatch.setattr(requests, "patch", mock_patch)

        # Mock st.error to capture error display
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call patch() - should NOT raise, should return error dict and show error
        result = api_call.patch(endpoint="v1/test", retries=0, toast=False)

        # Should return error dict (not raise)
        assert "error" in result

        # Should have shown error to user
        assert mock_error.called

    def test_get_handles_connection_error_gracefully(self, app_server, monkeypatch):
        """Test that get() handles connection errors gracefully after retries exhausted."""
        assert app_server is not None

        from client.utils import api_call
        import streamlit as st

        # Mock requests.get to raise ConnectionError
        mock_get = MagicMock(side_effect=requests.exceptions.ConnectionError("Connection refused"))
        monkeypatch.setattr(requests, "get", mock_get)

        # Mock st.error to capture error display
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call get() with no retries - should NOT raise, should return error dict and show error
        result = api_call.get(endpoint="v1/test", retries=0)

        # Should return error dict (not raise)
        assert "error" in result

        # Should have shown error to user
        assert mock_error.called

    def test_delete_handles_connection_error_gracefully(self, app_server, monkeypatch):
        """Test that delete() handles connection errors gracefully after retries exhausted."""
        assert app_server is not None

        from client.utils import api_call
        import streamlit as st

        # Mock requests.delete to raise ConnectionError
        mock_delete = MagicMock(side_effect=requests.exceptions.ConnectionError("Connection refused"))
        monkeypatch.setattr(requests, "delete", mock_delete)

        # Mock st.error to capture error display
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call delete() with no retries - should NOT raise, should return error dict and show error
        result = api_call.delete(endpoint="v1/test", retries=0, toast=False)

        # Should return error dict (not raise)
        assert "error" in result

        # Should have shown error to user
        assert mock_error.called


#############################################################################
# Test ApiError Class
#############################################################################
class TestApiError:
    """Test ApiError exception class."""

    def test_api_error_with_string_message(self, app_server):
        """Test ApiError with string message."""
        assert app_server is not None

        from client.utils.api_call import ApiError

        error = ApiError("Test error message")
        assert str(error) == "Test error message"
        assert error.message == "Test error message"

    def test_api_error_with_dict_message(self, app_server):
        """Test ApiError with dict message containing detail."""
        assert app_server is not None

        from client.utils.api_call import ApiError

        error = ApiError({"detail": "Detailed error message"})
        assert str(error) == "Detailed error message"
        assert error.message == "Detailed error message"

    def test_api_error_with_dict_no_detail(self, app_server):
        """Test ApiError with dict message without detail key."""
        assert app_server is not None

        from client.utils.api_call import ApiError

        error = ApiError({"error": "Some error"})
        # Should convert dict to string
        assert "error" in str(error)
