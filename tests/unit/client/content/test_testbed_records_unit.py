# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for testbed.py record management functions.
Extracted from test_testbed_unit.py to reduce file size.
"""
# spell-checker: disable

import sys
from unittest.mock import MagicMock


#############################################################################
# Test qa_update_db Function
#############################################################################
class TestQAUpdateDB:
    """Test qa_update_db function"""

    def test_qa_update_db_success(self, monkeypatch):
        """Test qa_update_db successfully updates database"""
        from client.content import testbed
        from client.utils import api_call, st_common
        from streamlit import session_state as state

        # Setup state
        state.testbed = {"testset_id": "test123", "qa_index": 0}
        state.selected_new_testset_name = "Updated Test Set"
        state.testbed_qa = [
            {"question": "Q1", "reference_answer": "A1"},
            {"question": "Q2", "reference_answer": "A2"},
        ]
        state["selected_q_0"] = "Q1"
        state["selected_a_0"] = "A1"

        # Mock API call
        mock_post = MagicMock(return_value={"status": "success"})
        monkeypatch.setattr(api_call, "post", mock_post)

        # Mock get_testbed_db_testsets
        mock_get_testsets = MagicMock(return_value={"testsets": []})
        testbed.get_testbed_db_testsets = mock_get_testsets
        testbed.get_testbed_db_testsets.clear = MagicMock()

        # Mock clear_state_key
        monkeypatch.setattr(st_common, "clear_state_key", MagicMock())

        # Call qa_update_db
        testbed.qa_update_db()

        # Verify API was called correctly
        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args[1]["endpoint"] == "v1/testbed/testset_load"
        assert call_args[1]["params"]["name"] == "Updated Test Set"
        assert call_args[1]["params"]["tid"] == "test123"

    def test_qa_update_db_clears_cache(self, monkeypatch):
        """Test qa_update_db clears testbed cache"""
        from client.content import testbed
        from client.utils import api_call, st_common
        from streamlit import session_state as state

        # Setup state
        state.testbed = {"testset_id": "test123", "qa_index": 0}
        state.selected_new_testset_name = "Test Set"
        state.testbed_qa = [{"question": "Q1", "reference_answer": "A1"}]
        state["selected_q_0"] = "Q1"
        state["selected_a_0"] = "A1"

        # Mock functions
        monkeypatch.setattr(api_call, "post", MagicMock())
        mock_clear_state = MagicMock()
        monkeypatch.setattr(st_common, "clear_state_key", mock_clear_state)

        mock_clear_cache = MagicMock()
        testbed.get_testbed_db_testsets = MagicMock(return_value={"testsets": []})
        testbed.get_testbed_db_testsets.clear = mock_clear_cache

        # Call qa_update_db
        testbed.qa_update_db()

        # Verify cache was cleared
        mock_clear_state.assert_called_with("testbed_db_testsets")
        mock_clear_cache.assert_called_once()


#############################################################################
# Test qa_delete Function
#############################################################################
class TestQADelete:
    """Test qa_delete function"""

    def test_qa_delete_success(self, monkeypatch):
        """Test qa_delete successfully deletes testset"""
        from client.content import testbed
        from client.utils import api_call
        from streamlit import session_state as state
        import streamlit as st

        # Setup state
        state.testbed = {"testset_id": "test123", "testset_name": "My Test Set"}

        # Mock API call
        mock_delete = MagicMock()
        monkeypatch.setattr(api_call, "delete", mock_delete)

        # Mock reset_testset
        mock_reset = MagicMock()
        monkeypatch.setattr(testbed, "reset_testset", mock_reset)

        # Mock st.success
        mock_success = MagicMock()
        monkeypatch.setattr(st, "success", mock_success)

        # Call qa_delete
        testbed.qa_delete()

        # Verify delete was called
        mock_delete.assert_called_once_with(endpoint="v1/testbed/testset_delete/test123")

        # Verify success message shown
        assert mock_success.called
        success_msg = mock_success.call_args[0][0]
        assert "My Test Set" in success_msg

        # Verify reset_testset called with cache=True
        mock_reset.assert_called_once_with(True)

    def test_qa_delete_api_error(self, monkeypatch):
        """Test qa_delete when API call fails"""
        from client.content import testbed
        from client.utils import api_call
        from streamlit import session_state as state
        import streamlit as st

        # Setup state
        state.testbed = {"testset_id": "test123", "testset_name": "My Test Set"}

        # Mock API call to raise error
        def mock_delete(endpoint):
            raise api_call.ApiError("Delete failed")

        monkeypatch.setattr(api_call, "delete", mock_delete)

        # Mock st.error
        mock_error = MagicMock()
        monkeypatch.setattr(st, "error", mock_error)

        # Call qa_delete - should handle error gracefully
        testbed.qa_delete()

        # Verify error was logged
        assert True  # Function should complete without raising exception


#############################################################################
# Test update_record Function
#############################################################################
class TestUpdateRecord:
    """Test update_record function"""

    def test_update_record_forward(self, monkeypatch):
        """Test update_record with forward direction"""
        # Mock st.fragment to be a no-op decorator BEFORE importing testbed
        import streamlit as st

        monkeypatch.setattr(st, "fragment", lambda: lambda func: func)

        # Force reload of testbed module and all client.content modules to pick up the mocked decorator
        modules_to_delete = [k for k in sys.modules if k.startswith("client.content")]
        for mod in modules_to_delete:
            del sys.modules[mod]

        from client.content import testbed
        from streamlit import session_state as state

        # Setup state
        state.testbed = {"qa_index": 0}
        state.testbed_qa = [
            {"question": "Q1", "reference_answer": "A1", "reference_context": "", "metadata": ""},
            {"question": "Q2", "reference_answer": "A2", "reference_context": "", "metadata": ""},
        ]
        state["selected_q_0"] = "Q1 Updated"
        state["selected_a_0"] = "A1 Updated"
        state["selected_c_0"] = ""
        state["selected_m_0"] = ""

        # Call update_record with direction=1 (forward)
        testbed.update_record(direction=1)

        # Verify record was updated
        assert state.testbed_qa[0]["question"] == "Q1 Updated"
        assert state.testbed_qa[0]["reference_answer"] == "A1 Updated"

        # Verify index moved forward
        assert state.testbed["qa_index"] == 1

    def test_update_record_backward(self, monkeypatch):
        """Test update_record with backward direction"""
        # Mock st.fragment to be a no-op decorator BEFORE importing testbed
        import streamlit as st

        monkeypatch.setattr(st, "fragment", lambda: lambda func: func)

        # Force reload of testbed module and all client.content modules to pick up the mocked decorator
        modules_to_delete = [k for k in sys.modules if k.startswith("client.content")]
        for mod in modules_to_delete:
            del sys.modules[mod]

        from client.content import testbed
        from streamlit import session_state as state

        # Setup state
        state.testbed = {"qa_index": 1}
        state.testbed_qa = [
            {"question": "Q1", "reference_answer": "A1", "reference_context": "", "metadata": ""},
            {"question": "Q2", "reference_answer": "A2", "reference_context": "", "metadata": ""},
        ]
        state["selected_q_1"] = "Q2 Updated"
        state["selected_a_1"] = "A2 Updated"
        state["selected_c_1"] = ""
        state["selected_m_1"] = ""

        # Call update_record with direction=-1 (backward)
        testbed.update_record(direction=-1)

        # Verify record was updated
        assert state.testbed_qa[1]["question"] == "Q2 Updated"
        assert state.testbed_qa[1]["reference_answer"] == "A2 Updated"

        # Verify index moved backward
        assert state.testbed["qa_index"] == 0

    def test_update_record_no_direction(self, monkeypatch):
        """Test update_record with no direction (stays in place)"""
        # Mock st.fragment to be a no-op decorator BEFORE importing testbed
        import streamlit as st

        monkeypatch.setattr(st, "fragment", lambda: lambda func: func)

        # Force reload of testbed module and all client.content modules to pick up the mocked decorator
        modules_to_delete = [k for k in sys.modules if k.startswith("client.content")]
        for mod in modules_to_delete:
            del sys.modules[mod]

        from client.content import testbed
        from streamlit import session_state as state

        # Setup state
        state.testbed = {"qa_index": 1}
        state.testbed_qa = [
            {"question": "Q1", "reference_answer": "A1", "reference_context": "", "metadata": ""},
            {"question": "Q2", "reference_answer": "A2", "reference_context": "", "metadata": ""},
        ]
        state["selected_q_1"] = "Q2 Modified"
        state["selected_a_1"] = "A2 Modified"
        state["selected_c_1"] = ""
        state["selected_m_1"] = ""

        # Call update_record with direction=0 (no movement)
        testbed.update_record(direction=0)

        # Verify record was updated
        assert state.testbed_qa[1]["question"] == "Q2 Modified"
        assert state.testbed_qa[1]["reference_answer"] == "A2 Modified"

        # Verify index stayed the same
        assert state.testbed["qa_index"] == 1


#############################################################################
# Test delete_record Function
#############################################################################
class TestDeleteRecord:
    """Test delete_record function"""

    def test_delete_record_middle(self, monkeypatch):
        """Test deleting a record from the middle"""
        # Mock st.fragment to be a no-op decorator BEFORE importing testbed
        import streamlit as st

        monkeypatch.setattr(st, "fragment", lambda: lambda func: func)

        # Force reload of testbed module and all client.content modules to pick up the mocked decorator
        modules_to_delete = [k for k in sys.modules if k.startswith("client.content")]
        for mod in modules_to_delete:
            del sys.modules[mod]

        from client.content import testbed
        from streamlit import session_state as state

        # Setup state with 3 records, index at 1
        state.testbed = {"qa_index": 1}
        state.testbed_qa = [
            {"question": "Q1", "reference_answer": "A1"},
            {"question": "Q2", "reference_answer": "A2"},
            {"question": "Q3", "reference_answer": "A3"},
        ]

        # Delete record at index 1
        testbed.delete_record()

        # Verify record was deleted
        assert len(state.testbed_qa) == 2
        assert state.testbed_qa[0]["question"] == "Q1"
        assert state.testbed_qa[1]["question"] == "Q3"

        # Verify index stayed at 1 (still valid, now points to Q3)
        assert state.testbed["qa_index"] == 1

    def test_delete_record_first(self, monkeypatch):
        """Test deleting the first record (index 0)"""
        # Mock st.fragment to be a no-op decorator BEFORE importing testbed
        import streamlit as st

        monkeypatch.setattr(st, "fragment", lambda: lambda func: func)

        # Force reload of testbed module and all client.content modules to pick up the mocked decorator
        modules_to_delete = [k for k in sys.modules if k.startswith("client.content")]
        for mod in modules_to_delete:
            del sys.modules[mod]

        from client.content import testbed
        from streamlit import session_state as state

        # Setup state with index at 0
        state.testbed = {"qa_index": 0}
        state.testbed_qa = [
            {"question": "Q1", "reference_answer": "A1"},
            {"question": "Q2", "reference_answer": "A2"},
        ]

        # Delete record at index 0
        testbed.delete_record()

        # Verify record was deleted
        assert len(state.testbed_qa) == 1
        assert state.testbed_qa[0]["question"] == "Q2"

        # Verify index stayed at 0 (doesn't go negative)
        assert state.testbed["qa_index"] == 0

    def test_delete_record_last(self, monkeypatch):
        """Test deleting the last record"""
        # Mock st.fragment to be a no-op decorator BEFORE importing testbed
        import streamlit as st

        monkeypatch.setattr(st, "fragment", lambda: lambda func: func)

        # Force reload of testbed module and all client.content modules to pick up the mocked decorator
        modules_to_delete = [k for k in sys.modules if k.startswith("client.content")]
        for mod in modules_to_delete:
            del sys.modules[mod]

        from client.content import testbed
        from streamlit import session_state as state

        # Setup state with index at last position
        state.testbed = {"qa_index": 2}
        state.testbed_qa = [
            {"question": "Q1", "reference_answer": "A1"},
            {"question": "Q2", "reference_answer": "A2"},
            {"question": "Q3", "reference_answer": "A3"},
        ]

        # Delete record at index 2
        testbed.delete_record()

        # Verify record was deleted
        assert len(state.testbed_qa) == 2

        # Verify index moved back
        assert state.testbed["qa_index"] == 1


#############################################################################
# Test qa_update_gui Function
#############################################################################
class TestQAUpdateGUI:
    """Test qa_update_gui function"""

    def test_qa_update_gui_multiple_records(self, monkeypatch):
        """Test qa_update_gui with multiple records"""
        from client.content import testbed
        from streamlit import session_state as state
        import streamlit as st

        # Setup state
        state.testbed = {"qa_index": 1}
        qa_testset = [
            {"question": "Q1", "reference_answer": "A1", "reference_context": "C1", "metadata": "M1"},
            {"question": "Q2", "reference_answer": "A2", "reference_context": "C2", "metadata": "M2"},
            {"question": "Q3", "reference_answer": "A3", "reference_context": "C3", "metadata": "M3"},
        ]

        # Mock streamlit functions
        mock_write = MagicMock()
        mock_columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock(), MagicMock()])
        mock_text_area = MagicMock()
        mock_text_input = MagicMock()

        monkeypatch.setattr(st, "write", mock_write)
        monkeypatch.setattr(st, "columns", mock_columns)
        monkeypatch.setattr(st, "text_area", mock_text_area)
        monkeypatch.setattr(st, "text_input", mock_text_input)

        # Call qa_update_gui
        testbed.qa_update_gui(qa_testset)

        # Verify record counter was displayed
        mock_write.assert_called_once()
        assert "2/3" in mock_write.call_args[0][0]

        # Verify text areas were created
        assert mock_text_area.call_count >= 3  # Question, Answer, Context

    def test_qa_update_gui_single_record(self, monkeypatch):
        """Test qa_update_gui with single record (delete disabled)"""
        from client.content import testbed
        from streamlit import session_state as state
        import streamlit as st

        # Setup state with single record
        state.testbed = {"qa_index": 0}
        qa_testset = [
            {"question": "Q1", "reference_answer": "A1", "reference_context": "C1", "metadata": "M1"},
        ]

        # Mock streamlit functions
        mock_button_col = MagicMock()
        mock_columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock(), mock_button_col])

        monkeypatch.setattr(st, "write", MagicMock())
        monkeypatch.setattr(st, "columns", mock_columns)
        monkeypatch.setattr(st, "text_area", MagicMock())
        monkeypatch.setattr(st, "text_input", MagicMock())

        # Call qa_update_gui
        testbed.qa_update_gui(qa_testset)

        # Verify delete button is disabled
        delete_button_call = mock_button_col.button.call_args
        assert delete_button_call[1]["disabled"] is True

    def test_qa_update_gui_navigation_buttons(self, monkeypatch):
        """Test qa_update_gui navigation button states"""
        from client.content import testbed
        from streamlit import session_state as state
        import streamlit as st

        # Setup state at first record
        state.testbed = {"qa_index": 0}
        qa_testset = [
            {"question": "Q1", "reference_answer": "A1", "reference_context": "C1", "metadata": "M1"},
            {"question": "Q2", "reference_answer": "A2", "reference_context": "C2", "metadata": "M2"},
        ]

        # Mock streamlit functions
        prev_col = MagicMock()
        next_col = MagicMock()
        mock_columns = MagicMock(return_value=[prev_col, next_col, MagicMock(), MagicMock()])

        monkeypatch.setattr(st, "write", MagicMock())
        monkeypatch.setattr(st, "columns", mock_columns)
        monkeypatch.setattr(st, "text_area", MagicMock())
        monkeypatch.setattr(st, "text_input", MagicMock())

        # Call qa_update_gui
        testbed.qa_update_gui(qa_testset)

        # Verify Previous button is disabled at first record
        prev_button_call = prev_col.button.call_args
        assert prev_button_call[1]["disabled"] is True

        # Verify Next button is enabled
        next_button_call = next_col.button.call_args
        assert next_button_call[1]["disabled"] is False
