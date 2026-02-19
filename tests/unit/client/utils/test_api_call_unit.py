# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for api_call module - focusing on error handling when
API server is disconnected or returns errors.
"""
# spell-checker: disable

from unittest.mock import MagicMock
import pytest
import requests


#############################################################################
# Test Error Handling Raises ApiError
#############################################################################
class TestErrorHandlingRaisesApiError:
    """Test that API call functions raise ApiError on server errors."""

    def test_get_raises_api_error_on_http_500(self, app_server, monkeypatch):
        """Test that get() raises ApiError on HTTP 500 errors."""
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

        # Call get() - should raise ApiError
        with pytest.raises(api_call.ApiError) as exc_info:
            api_call.get(endpoint="v1/test", retries=0)

        # Should have the error message
        assert "Internal Server Error" in str(exc_info.value)

        # Should have shown error to user
        assert mock_error.called

    def test_delete_raises_api_error_on_http_500(self, app_server, monkeypatch):
        """Test that delete() raises ApiError on HTTP 500 errors."""
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

        # Call delete() - should raise ApiError
        with pytest.raises(api_call.ApiError) as exc_info:
            api_call.delete(endpoint="v1/test", retries=0, toast=False)

        # Should have the error message
        assert "Internal Server Error" in str(exc_info.value)

        # Should have shown error to user
        assert mock_error.called

    def test_post_raises_api_error_on_http_500(self, app_server, monkeypatch):
        """Test that post() raises ApiError on HTTP 500 errors."""
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

        # Call post() - should raise ApiError
        with pytest.raises(api_call.ApiError) as exc_info:
            api_call.post(endpoint="v1/test", retries=0)

        # Should have the error message
        assert "Internal Server Error" in str(exc_info.value)

        # Should have shown error to user
        assert mock_error.called

    def test_patch_raises_api_error_on_http_500(self, app_server, monkeypatch):
        """Test that patch() raises ApiError on HTTP 500 errors."""
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

        # Call patch() - should raise ApiError
        with pytest.raises(api_call.ApiError) as exc_info:
            api_call.patch(endpoint="v1/test", retries=0, toast=False)

        # Should have the error message
        assert "Internal Server Error" in str(exc_info.value)

        # Should have shown error to user
        assert mock_error.called

    def test_get_raises_api_error_on_connection_error(self, app_server, monkeypatch):
        """Test that get() raises ApiError on connection errors after retries exhausted."""
        assert app_server is not None

        from client.utils import api_call
        import streamlit as st

        # Mock requests.get to raise ConnectionError
        mock_get = MagicMock(side_effect=requests.exceptions.ConnectionError("Connection refused"))
        monkeypatch.setattr(requests, "get", mock_get)

        # Mock st.error to capture error display
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call get() with no retries - should raise ApiError
        with pytest.raises(api_call.ApiError) as exc_info:
            api_call.get(endpoint="v1/test", retries=0)

        # Should have connection failure message
        assert "Connection failed" in str(exc_info.value)

        # Should have shown error to user
        assert mock_error.called

    def test_delete_raises_api_error_on_connection_error(self, app_server, monkeypatch):
        """Test that delete() raises ApiError on connection errors after retries exhausted."""
        assert app_server is not None

        from client.utils import api_call
        import streamlit as st

        # Mock requests.delete to raise ConnectionError
        mock_delete = MagicMock(side_effect=requests.exceptions.ConnectionError("Connection refused"))
        monkeypatch.setattr(requests, "delete", mock_delete)

        # Mock st.error to capture error display
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call delete() with no retries - should raise ApiError
        with pytest.raises(api_call.ApiError) as exc_info:
            api_call.delete(endpoint="v1/test", retries=0, toast=False)

        # Should have connection failure message
        assert "Connection failed" in str(exc_info.value)

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
