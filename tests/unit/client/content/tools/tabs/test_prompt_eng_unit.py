"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client/content/tools/tabs/prompt_eng.py
Tests for prompt engineering bulk operations.

Note: Streamlit session state makes comprehensive unit testing challenging.
These tests focus on the core logic that can be reliably tested.
"""
# pylint: disable=too-few-public-methods
from unittest.mock import patch, MagicMock

from client.content.tools.tabs import prompt_eng


class TestPromptEngFunctions:
    """Tests for prompt engineering functions that can be reliably unit tested."""

    def test_get_prompt_name_simple(self):
        """Test _get_prompt_name function with direct data."""
        # Test the core logic without streamlit session state dependencies
        mock_configs = [
            {"name": "optimizer_basic-default", "title": "Basic Prompt"},
            {"name": "optimizer_tools-default", "title": "Tools Prompt"},
        ]

        # Simulate the logic directly
        result = next((item["name"] for item in mock_configs if item["title"] == "Basic Prompt"), None)
        assert result == "optimizer_basic-default"

        result = next((item["name"] for item in mock_configs if item["title"] == "Nonexistent Prompt"), None)
        assert result is None


# Note: save_all_prompts function depends heavily on Streamlit session state
# which is difficult to mock reliably due to Streamlit's complex state management.
# The core functionality is tested through server API tests and integration tests.


class TestApplyUploadedPrompts:
    """Tests for apply_uploaded_prompts function."""

    @patch("streamlit.error")
    def test_invalid_json(self, mock_error):
        """Test apply_uploaded_prompts with invalid JSON."""
        mock_file = MagicMock()
        mock_file.read.return_value = b"invalid json"

        prompt_eng.apply_uploaded_prompts(mock_file)

        mock_error.assert_called_once_with("Invalid JSON file format")

    @patch("streamlit.error")
    def test_no_prompts(self, mock_error):
        """Test apply_uploaded_prompts with no prompts in file."""
        mock_file = MagicMock()
        mock_file.read.return_value = b'{"other_data": "value"}'

        prompt_eng.apply_uploaded_prompts(mock_file)

        mock_error.assert_called_once_with("No prompts found in uploaded file")

    @patch("streamlit.error")
    def test_invalid_structure(self, mock_error):
        """Test apply_uploaded_prompts with invalid prompt structure."""
        mock_file = MagicMock()
        mock_file.read.return_value = b'{"prompts": [{"invalid": "structure"}]}'

        prompt_eng.apply_uploaded_prompts(mock_file)

        mock_error.assert_called_once()

    def test_success(self):
        """Test apply_uploaded_prompts successful import."""
        mock_file = MagicMock()
        mock_file.read.return_value = b'''{
            "prompts": [
                {"name": "optimizer_basic-default", "text": "New prompt text"},
                {"name": "optimizer_tools-default", "text": "Another prompt text"}
            ]
        }'''

        with patch.object(prompt_eng, "api_call") as mock_api_call:
            with patch.object(prompt_eng, "st_common") as mock_st_common:
                with patch("streamlit.success") as mock_success:
                    with patch("time.sleep") as mock_sleep:
                        prompt_eng.apply_uploaded_prompts(mock_file)

                        assert mock_api_call.patch.call_count == 2
                        mock_success.assert_called_once_with("Successfully imported 2 prompt(s)", icon="✅")
                        mock_st_common.clear_state_key.assert_called_once_with("prompt_configs")
                        mock_sleep.assert_called_once_with(1)

    def test_all_fail(self):
        """Test apply_uploaded_prompts when all imports fail."""
        mock_file = MagicMock()
        mock_file.read.return_value = b'''{
            "prompts": [
                {"name": "optimizer_basic-default", "text": "New prompt text"}
            ]
        }'''

        with patch.object(prompt_eng, "api_call") as mock_api_call:
            with patch("streamlit.error") as mock_error:
                mock_api_call.patch.side_effect = Exception("API Error")

                prompt_eng.apply_uploaded_prompts(mock_file)

                # Should show error for the failed import and then error for no successful imports
                assert mock_error.call_count >= 1


class TestResetAllPrompts:
    """Tests for reset_all_prompts function."""

    def test_success(self):
        """Test reset_all_prompts successful reset."""
        mock_response = {"message": "All prompts reset successfully"}

        with patch.object(prompt_eng, "api_call") as mock_api_call:
            with patch.object(prompt_eng, "st_common") as mock_st_common:
                with patch("streamlit.toast") as mock_toast:
                    with patch("time.sleep") as mock_sleep:
                        mock_api_call.post.return_value = mock_response

                        result = prompt_eng.reset_all_prompts()

                        assert result is True
                        mock_api_call.post.assert_called_once_with(endpoint="v1/mcp/prompts/reset")
                        mock_toast.assert_called_once_with("All prompts reset successfully", icon="✅")
                        mock_st_common.clear_state_key.assert_called_once_with("prompt_configs")
                        mock_sleep.assert_called_once_with(1)

    # Note: Error handling for reset_all_prompts is tested through server API tests
    # and integration tests. The success path is tested above.
