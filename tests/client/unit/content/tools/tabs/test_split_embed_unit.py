# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

import pandas as pd



#############################################################################
# Test FileSourceData Class
#############################################################################
class TestFileSourceData:
    """Test FileSourceData dataclass"""

    def test_file_source_data_is_valid_true(self):
        """Test FileSourceData.is_valid when all required fields present"""
        from client.content.tools.tabs.split_embed import FileSourceData
        from streamlit import session_state as state

        # Test Local source with files in state
        state["local_file_uploader"] = ["file1.txt"]
        data = FileSourceData(file_source="Local")
        assert data.is_valid() is True

        # Test OCI source with valid DataFrame
        df = pd.DataFrame({"Process": [True, False]})
        data_oci = FileSourceData(file_source="OCI", oci_files_selected=df)
        assert data_oci.is_valid() is True

    def test_file_source_data_is_valid_false_no_files(self):
        """Test FileSourceData.is_valid when no files"""
        from client.content.tools.tabs.split_embed import FileSourceData
        from streamlit import session_state as state

        # Test Local source with no files in state
        if "local_file_uploader" in state:
            del state["local_file_uploader"]
        data = FileSourceData(file_source="Local")
        assert data.is_valid() is False

        # Test OCI source with no selected files (all False)
        df = pd.DataFrame({"Process": [False, False]})
        data_oci = FileSourceData(file_source="OCI", oci_files_selected=df)
        assert data_oci.is_valid() is False

    def test_file_source_data_get_button_help_local(self):
        """Test get_button_help for local files"""
        from client.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="Local")
        help_text = data.get_button_help()
        # Check that help text mentions files or local
        assert "file" in help_text.lower() or "local" in help_text.lower()

    def test_file_source_data_get_button_help_oci(self):
        """Test get_button_help for OCI files"""
        from client.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="OCI", oci_bucket="my-bucket")
        help_text = data.get_button_help()
        # Check that help text mentions bucket, split, embed, or documents
        assert any(word in help_text.lower() for word in ["bucket", "split", "embed", "document"])

    def test_file_source_data_get_button_help_web(self):
        """Test get_button_help for web files"""
        from client.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="Web", web_url="https://example.com")
        help_text = data.get_button_help()
        assert "url" in help_text.lower()


#############################################################################
# Test OCI Functions
#############################################################################
class TestOCIFunctions:
    """Test OCI-related functions"""

    def test_get_compartments_success(self, monkeypatch):
        """Test get_compartments with successful API call"""
        from client.content.tools.tabs.split_embed import get_compartments
        from client.utils import api_call
        from streamlit import session_state as state

        # Setup state with OCI config
        state.client_settings = {"oci": {"auth_profile": "DEFAULT"}}

        # Mock API response - returns a flat dict of compartment names to OCIDs
        mock_compartments = {
            "comp1": "ocid1.compartment.oc1..test1",
            "comp2": "ocid1.compartment.oc1..test2"
        }
        monkeypatch.setattr(api_call, "get", lambda endpoint: mock_compartments)

        # Call function
        result = get_compartments()

        # Verify result - should be a flat dict
        assert isinstance(result, dict)
        assert len(result) == 2
        assert "comp1" in result
        assert "comp2" in result

    def test_get_buckets_success(self, monkeypatch):
        """Test get_buckets with successful API call"""
        from client.content.tools.tabs.split_embed import get_buckets
        from client.utils import api_call
        from streamlit import session_state as state

        # Setup state with OCI config
        state.client_settings = {"oci": {"auth_profile": "DEFAULT"}}

        # Mock API response
        mock_buckets = ["bucket1", "bucket2", "bucket3"]
        monkeypatch.setattr(api_call, "get", lambda endpoint: mock_buckets)

        # Call function
        result = get_buckets("compartment-id")

        # Verify result
        assert isinstance(result, list)
        assert len(result) == 3

    def test_get_bucket_objects_success(self, monkeypatch):
        """Test get_bucket_objects with successful API call"""
        from client.content.tools.tabs.split_embed import get_bucket_objects
        from client.utils import api_call
        from streamlit import session_state as state

        # Setup state with OCI config
        state.client_settings = {"oci": {"auth_profile": "DEFAULT"}}

        # Mock API response
        mock_objects = [
            {"name": "file1.pdf", "size": 1024},
            {"name": "file2.txt", "size": 2048},
        ]
        monkeypatch.setattr(api_call, "get", lambda endpoint: mock_objects)

        # Call function
        result = get_bucket_objects("my-bucket")

        # Verify result
        assert isinstance(result, list)
        assert len(result) == 2


#############################################################################
# Test File Data Frame Functions
#############################################################################
class TestFileDataFrame:
    """Test files_data_frame and files_data_editor functions"""

    def test_files_data_frame_empty(self):
        """Test files_data_frame with empty objects"""
        from client.content.tools.tabs.split_embed import files_data_frame

        # Call with empty list
        result = files_data_frame([])

        # Should return empty DataFrame
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_files_data_frame_with_objects(self):
        """Test files_data_frame with file objects"""
        from client.content.tools.tabs.split_embed import files_data_frame

        # Create test objects - function expects list of objects, not dicts
        objects = [
            {"name": "file1.pdf", "size": 1024},
            {"name": "file2.txt", "size": 2048},
        ]

        # Call function
        result = files_data_frame(objects)

        # Verify DataFrame - columns are "File" and "Process" (capital letters)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert "File" in result.columns
        assert "Process" in result.columns

    def test_files_data_frame_with_process(self):
        """Test files_data_frame with process=True"""
        from client.content.tools.tabs.split_embed import files_data_frame

        objects = [
            {"name": "file1.pdf", "size": 1024},
        ]

        # Call with process=True
        result = files_data_frame(objects, process=True)

        # Should add 'Process' column (capital P) with value True
        assert isinstance(result, pd.DataFrame)
        assert "Process" in result.columns
        assert bool(result["Process"][0]) is True


#############################################################################
# Test Chunk Size/Overlap Functions
#############################################################################
class TestChunkFunctions:
    """Test chunk size and overlap update functions"""

    def test_update_chunk_overlap_slider(self):
        """Test update_chunk_overlap_slider function"""
        from client.content.tools.tabs.split_embed import update_chunk_overlap_slider
        from streamlit import session_state as state

        # Setup state - function copies FROM input TO slider
        state.selected_chunk_overlap_input = 200

        # Call function
        update_chunk_overlap_slider()

        # Verify slider value was updated FROM input
        assert state.selected_chunk_overlap_slider == 200

    def test_update_chunk_overlap_input(self):
        """Test update_chunk_overlap_input function"""
        from client.content.tools.tabs.split_embed import update_chunk_overlap_input
        from streamlit import session_state as state

        # Setup state - function copies FROM slider TO input
        state.selected_chunk_overlap_slider = 150

        # Call function
        update_chunk_overlap_input()

        # Verify input value was updated FROM slider
        assert state.selected_chunk_overlap_input == 150

    def test_update_chunk_size_slider(self):
        """Test update_chunk_size_slider function"""
        from client.content.tools.tabs.split_embed import update_chunk_size_slider
        from streamlit import session_state as state

        # Setup state - function copies FROM input TO slider
        state.selected_chunk_size_input = 2000

        # Call function
        update_chunk_size_slider()

        # Verify slider value was updated FROM input
        assert state.selected_chunk_size_slider == 2000

    def test_update_chunk_size_input(self):
        """Test update_chunk_size_input function"""
        from client.content.tools.tabs.split_embed import update_chunk_size_input
        from streamlit import session_state as state

        # Setup state - function copies FROM slider TO input
        state.selected_chunk_size_slider = 1500

        # Call function
        update_chunk_size_input()

        # Verify input value was updated FROM slider
        assert state.selected_chunk_size_input == 1500


#############################################################################
# Edge Case and Validation Tests
#############################################################################
class TestSplitEmbedEdgeCases:
    """Tests for edge cases and validation in split_embed implementation"""

    def test_chunk_overlap_validation(self):
        """
        Test that chunk_overlap should not exceed chunk_size.

        This validates proper chunk configuration to prevent text splitting issues.
        If this test fails, it indicates chunk_overlap is allowed to exceed chunk_size.
        """
        from client.content.tools.tabs.split_embed import update_chunk_overlap_input
        from streamlit import session_state as state

        # Setup state with overlap > size (function copies FROM slider TO input)
        state.selected_chunk_overlap_slider = 2000  # Overlap (will be copied to input)
        state.selected_chunk_size_slider = 1000    # Size (smaller!)

        # Call function
        update_chunk_overlap_input()

        # EXPECTED: overlap should be capped at chunk_size or validation should prevent this
        # If this assertion fails, it exposes lack of validation
        assert state.selected_chunk_overlap_input < state.selected_chunk_size_slider, \
            "Chunk overlap should not exceed chunk size"

    def test_files_data_frame_process_column_added(self):
        """
        Test that files_data_frame() correctly adds Process column when process=True.

        The function should handle objects that don't have a 'process' field
        and add a Process column with the specified default value.
        """
        from client.content.tools.tabs.split_embed import files_data_frame

        # Objects without 'process' field
        objects = [
            {"name": "file1.pdf", "size": 1024},
            {"name": "file2.txt", "size": 2048},
        ]

        # Call with process=True
        result = files_data_frame(objects, process=True)

        # EXPECTED: 'Process' column should be added and all values should be True
        assert "Process" in result.columns, "Process column should be present"
        assert all(result["Process"]), "All Process values should be True when process=True"

    def test_file_source_data_validation_edge_cases(self):
        """
        Test FileSourceData.is_valid() correctly handles edge cases.

        Tests that validation properly identifies invalid configurations
        such as empty file lists or no files selected for processing.
        """
        from client.content.tools.tabs.split_embed import FileSourceData

        # Test OCI with empty DataFrame (no files available)
        df_empty = pd.DataFrame({"Process": []})
        data_oci_empty = FileSourceData(file_source="OCI", oci_files_selected=df_empty)
        result = data_oci_empty.is_valid()
        # EXPECTED: Should be False when no files are available
        assert result is False, "is_valid() should return False for empty file list"

        # Test OCI with DataFrame where no files are selected for processing
        df_all_false = pd.DataFrame({"Process": [False, False]})
        data_oci_false = FileSourceData(file_source="OCI", oci_files_selected=df_all_false)
        result = data_oci_false.is_valid()
        # EXPECTED: Should be False when no files are selected (all Process=False)
        assert result is False, "is_valid() should return False when no files are selected for processing"


#############################################################################
# Test Validation Logic
#############################################################################
class TestValidationLogic:
    """Test validation logic functions"""

    def test_vector_store_alias_validation_logic(self):
        """Test vector store alias validation regex logic directly"""
        import re

        # Test the regex pattern used in the source code
        pattern = r"^[A-Za-z][A-Za-z0-9_]*$"

        # Valid aliases
        assert re.match(pattern, "valid_alias")
        assert re.match(pattern, "Valid123")
        assert re.match(pattern, "test_alias_with_underscores")
        assert re.match(pattern, "A")

        # Invalid aliases
        assert not re.match(pattern, "123invalid")  # starts with number
        assert not re.match(pattern, "invalid-alias")  # contains hyphen
        assert not re.match(pattern, "_invalid")  # starts with underscore
        assert not re.match(pattern, "invalid alias")  # contains space
        assert not re.match(pattern, "")  # empty string

    def test_chunk_overlap_calculation_logic(self):
        """Test chunk overlap calculation logic directly"""
        import math

        # Test the calculation used in the source code
        chunk_size = 1000
        chunk_overlap_pct = 20
        expected_overlap = math.ceil((chunk_overlap_pct / 100) * chunk_size)

        assert expected_overlap == 200

        # Test edge cases
        assert math.ceil((0 / 100) * 1000) == 0  # 0% overlap
        assert math.ceil((100 / 100) * 1000) == 1000  # 100% overlap
        assert math.ceil((15 / 100) * 500) == 75  # 15% of 500
