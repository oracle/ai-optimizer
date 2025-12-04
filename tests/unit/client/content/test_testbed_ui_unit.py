# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for testbed.py UI rendering functions.
Extracted from test_testbed_unit.py to reduce file size.
"""
# spell-checker: disable

from unittest.mock import MagicMock


#############################################################################
# Test render_existing_testset_ui Function
#############################################################################
class TestRenderExistingTestsetUI:
    """Test render_existing_testset_ui function"""

    def test_render_existing_testset_ui_database_with_selection(self, monkeypatch):
        """Test render_existing_testset_ui correctly extracts testset_id when database test set is selected"""
        from client.content import testbed
        import streamlit as st
        from streamlit import session_state as state

        # Mock session state
        state.testbed_db_testsets = [
            {"tid": "test1", "name": "Test Set 1", "created": "2024-01-01 10:00:00"},
            {"tid": "test2", "name": "Test Set 2", "created": "2024-01-02 11:00:00"},
        ]
        state.testbed = {"uploader_key": 1}

        # Mock streamlit components
        mock_radio = MagicMock(return_value="Database")
        mock_selectbox = MagicMock(return_value="Test Set 1 -- Created: 2024-01-01 10:00:00")
        mock_file_uploader = MagicMock()

        monkeypatch.setattr(st, "radio", mock_radio)
        monkeypatch.setattr(st, "selectbox", mock_selectbox)
        monkeypatch.setattr(st, "file_uploader", mock_file_uploader)

        # Call the function
        testset_sources = ["Database", "Local"]
        source, endpoint, disabled, testset_id = testbed.render_existing_testset_ui(testset_sources)

        # Verify the return values
        assert source == "Database", "Should return Database as source"
        assert endpoint == "v1/testbed/testset_qa", "Should return correct endpoint for database"
        assert disabled is False, "Button should not be disabled when test set is selected"
        assert testset_id == "test1", f"Should extract correct testset_id 'test1', got {testset_id}"

    def test_render_existing_testset_ui_database_no_selection(self, monkeypatch):
        """Test render_existing_testset_ui when no database test set is selected"""
        from client.content import testbed
        import streamlit as st
        from streamlit import session_state as state

        # Mock session state
        state.testbed_db_testsets = [
            {"tid": "test1", "name": "Test Set 1", "created": "2024-01-01 10:00:00"},
        ]
        state.testbed = {"uploader_key": 1}

        # Mock streamlit components
        mock_radio = MagicMock(return_value="Database")
        mock_selectbox = MagicMock(return_value=None)  # No selection
        mock_file_uploader = MagicMock()

        monkeypatch.setattr(st, "radio", mock_radio)
        monkeypatch.setattr(st, "selectbox", mock_selectbox)
        monkeypatch.setattr(st, "file_uploader", mock_file_uploader)

        # Call the function
        testset_sources = ["Database", "Local"]
        source, endpoint, disabled, testset_id = testbed.render_existing_testset_ui(testset_sources)

        # Verify the return values
        assert source == "Database", "Should return Database as source"
        assert endpoint == "v1/testbed/testset_qa", "Should return correct endpoint"
        assert disabled is True, "Button should be disabled when no test set is selected"
        assert testset_id is None, "Should return None for testset_id when nothing selected"

    def test_render_existing_testset_ui_local_mode_no_files(self, monkeypatch):
        """Test render_existing_testset_ui in Local mode with no files uploaded"""
        from client.content import testbed
        import streamlit as st
        from streamlit import session_state as state

        # Mock session state
        state.testbed = {"uploader_key": 1}
        state.testbed_db_testsets = []

        # Mock streamlit components
        mock_radio = MagicMock(return_value="Local")
        mock_selectbox = MagicMock()
        mock_file_uploader = MagicMock(return_value=[])  # No files uploaded

        monkeypatch.setattr(st, "radio", mock_radio)
        monkeypatch.setattr(st, "selectbox", mock_selectbox)
        monkeypatch.setattr(st, "file_uploader", mock_file_uploader)

        # Call the function
        testset_sources = ["Database", "Local"]
        source, endpoint, disabled, testset_id = testbed.render_existing_testset_ui(testset_sources)

        # Verify the return values
        assert source == "Local", "Should return Local as source"
        assert endpoint == "v1/testbed/testset_load", "Should return correct endpoint for local"
        assert disabled is True, "Button should be disabled when no files uploaded"
        assert testset_id is None, "Should return None for testset_id in Local mode"

    def test_render_existing_testset_ui_local_mode_with_files(self, monkeypatch):
        """Test render_existing_testset_ui in Local mode with files uploaded"""
        from client.content import testbed
        import streamlit as st
        from streamlit import session_state as state

        # Mock session state
        state.testbed = {"uploader_key": 1}
        state.testbed_db_testsets = []

        # Mock streamlit components
        mock_radio = MagicMock(return_value="Local")
        mock_selectbox = MagicMock()
        mock_file_uploader = MagicMock(return_value=["file1.json", "file2.json"])  # Files uploaded

        monkeypatch.setattr(st, "radio", mock_radio)
        monkeypatch.setattr(st, "selectbox", mock_selectbox)
        monkeypatch.setattr(st, "file_uploader", mock_file_uploader)

        # Call the function
        testset_sources = ["Database", "Local"]
        source, endpoint, disabled, testset_id = testbed.render_existing_testset_ui(testset_sources)

        # Verify the return values
        assert source == "Local", "Should return Local as source"
        assert endpoint == "v1/testbed/testset_load", "Should return correct endpoint for local"
        assert disabled is False, "Button should be enabled when files are uploaded"
        assert testset_id is None, "Should return None for testset_id in Local mode"

    def test_render_existing_testset_ui_with_multiple_testsets(self, monkeypatch):
        """Test render_existing_testset_ui correctly identifies testset when multiple exist with same name"""
        from client.content import testbed
        import streamlit as st
        from streamlit import session_state as state

        # Mock session state with multiple test sets (some with same name)
        state.testbed_db_testsets = [
            {"tid": "test1", "name": "Production Tests", "created": "2024-01-01 10:00:00"},
            {
                "tid": "test2",
                "name": "Production Tests",
                "created": "2024-01-02 11:00:00",
            },  # Same name, different date
            {"tid": "test3", "name": "Dev Tests", "created": "2024-01-03 12:00:00"},
        ]
        state.testbed = {"uploader_key": 1}

        # Mock streamlit components - select the second "Production Tests"
        mock_radio = MagicMock(return_value="Database")
        mock_selectbox = MagicMock(return_value="Production Tests -- Created: 2024-01-02 11:00:00")
        mock_file_uploader = MagicMock()

        monkeypatch.setattr(st, "radio", mock_radio)
        monkeypatch.setattr(st, "selectbox", mock_selectbox)
        monkeypatch.setattr(st, "file_uploader", mock_file_uploader)

        # Call the function
        testset_sources = ["Database", "Local"]
        _, _, disabled, testset_id = testbed.render_existing_testset_ui(testset_sources)

        # Verify it extracted the correct testset_id (test2, not test1)
        assert testset_id == "test2", f"Should extract 'test2' for second Production Tests, got {testset_id}"
        assert disabled is False, "Button should not be disabled"
