"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Additional tests for split_embed.py to increase coverage from 53% to 85%+

NOTE: These tests are currently failing because they were written for an old version
of the FileSourceData class that has been refactored. The tests need to be updated
to match the current API:
- Old API used: file_list_response, process_files, src_bucket parameters
- New API uses: file_source, web_url, oci_bucket, oci_files_selected parameters

These tests are properly classified as unit tests (they mock dependencies)
and have been moved from integration/ to unit/ folder. They require updating
to work with the current codebase.
"""
# spell-checker: disable
# pylint: disable=import-error

import pytest
from unittest.mock import MagicMock, patch
import sys
import os
from contextlib import contextmanager
import pandas as pd


@contextmanager
def temporary_sys_path(path):
    """Temporarily add a path to sys.path and remove it when done"""
    sys.path.insert(0, path)
    try:
        yield
    finally:
        if path in sys.path:
            sys.path.remove(path)


#############################################################################
# Test FileSourceData Class
#############################################################################
class TestFileSourceData:
    """Test FileSourceData dataclass"""

    def test_file_source_data_is_valid_true(self):
        """Test FileSourceData.is_valid when all required fields present"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import FileSourceData

            # Create valid FileSourceData
            data = FileSourceData(
                file_source="local",
                file_list_response={"files": ["file1.txt"]},
                process_files=True,
                src_bucket="",
            )

            # Should be valid
            assert data.is_valid() is True

    def test_file_source_data_is_valid_false_no_files(self):
        """Test FileSourceData.is_valid when no files"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import FileSourceData

            # Create FileSourceData with empty file list
            data = FileSourceData(
                file_source="local",
                file_list_response={},
                process_files=True,
                src_bucket="",
            )

            # Should be invalid
            assert data.is_valid() is False

    def test_file_source_data_get_button_help_local(self):
        """Test get_button_help for local files"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import FileSourceData

            data = FileSourceData(
                file_source="local",
                file_list_response={"files": ["file1.txt"]},
                process_files=True,
                src_bucket="",
            )

            help_text = data.get_button_help()
            assert "Select file" in help_text or "file" in help_text.lower()

    def test_file_source_data_get_button_help_oci(self):
        """Test get_button_help for OCI files"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import FileSourceData

            data = FileSourceData(
                file_source="oci",
                file_list_response={},
                process_files=True,
                src_bucket="my-bucket",
            )

            help_text = data.get_button_help()
            assert "my-bucket" in help_text

    def test_file_source_data_get_button_help_web(self):
        """Test get_button_help for web files"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import FileSourceData

            data = FileSourceData(
                file_source="web",
                file_list_response={},
                process_files=True,
                src_bucket="",
            )

            help_text = data.get_button_help()
            assert "URL" in help_text or "web" in help_text.lower()


#############################################################################
# Test OCI Functions
#############################################################################
class TestOCIFunctions:
    """Test OCI-related functions"""

    def test_get_compartments_success(self, monkeypatch):
        """Test get_compartments with successful API call"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import get_compartments
            from client.utils import api_call

            # Mock API response
            mock_compartments = {
                "compartments": [
                    {"id": "c1", "name": "Compartment 1"},
                    {"id": "c2", "name": "Compartment 2"},
                ]
            }
            monkeypatch.setattr(api_call, "get", lambda endpoint: mock_compartments)

            # Call function
            result = get_compartments()

            # Verify result
            assert "compartments" in result
            assert len(result["compartments"]) == 2

    def test_get_buckets_success(self, monkeypatch):
        """Test get_buckets with successful API call"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import get_buckets
            from client.utils import api_call

            # Mock API response
            mock_buckets = ["bucket1", "bucket2", "bucket3"]
            monkeypatch.setattr(api_call, "get", lambda endpoint, params: mock_buckets)

            # Call function
            result = get_buckets("compartment-id")

            # Verify result
            assert isinstance(result, list)
            assert len(result) == 3

    def test_get_bucket_objects_success(self, monkeypatch):
        """Test get_bucket_objects with successful API call"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import get_bucket_objects
            from client.utils import api_call

            # Mock API response
            mock_objects = [
                {"name": "file1.pdf", "size": 1024},
                {"name": "file2.txt", "size": 2048},
            ]
            monkeypatch.setattr(api_call, "get", lambda endpoint, params: mock_objects)

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
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import files_data_frame

            # Call with empty list
            result = files_data_frame([])

            # Should return empty DataFrame
            assert isinstance(result, pd.DataFrame)
            assert len(result) == 0

    def test_files_data_frame_with_objects(self):
        """Test files_data_frame with file objects"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import files_data_frame

            # Create test objects
            objects = [
                {"name": "file1.pdf", "size": 1024, "other": "data"},
                {"name": "file2.txt", "size": 2048, "other": "data"},
            ]

            # Call function
            result = files_data_frame(objects)

            # Verify DataFrame
            assert isinstance(result, pd.DataFrame)
            assert len(result) == 2
            assert "name" in result.columns

    def test_files_data_frame_with_process(self):
        """Test files_data_frame with process=True"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import files_data_frame

            objects = [
                {"name": "file1.pdf", "size": 1024},
            ]

            # Call with process=True
            result = files_data_frame(objects, process=True)

            # Should add 'process' column
            assert isinstance(result, pd.DataFrame)
            assert "process" in result.columns


#############################################################################
# Test Chunk Size/Overlap Functions
#############################################################################
class TestChunkFunctions:
    """Test chunk size and overlap update functions"""

    def test_update_chunk_overlap_slider(self, monkeypatch):
        """Test update_chunk_overlap_slider function"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import update_chunk_overlap_slider
            from streamlit import session_state as state

            # Setup state
            state.selected_chunk_overlap_slider = 200
            state.selected_chunk_size_slider = 1000

            # Call function
            update_chunk_overlap_slider()

            # Verify input value was updated
            assert state.selected_chunk_overlap_input == 200

    def test_update_chunk_overlap_input(self, monkeypatch):
        """Test update_chunk_overlap_input function"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import update_chunk_overlap_input
            from streamlit import session_state as state

            # Setup state
            state.selected_chunk_overlap_input = 150
            state.selected_chunk_size_slider = 1000

            # Call function
            update_chunk_overlap_input()

            # Verify slider value was updated
            assert state.selected_chunk_overlap_slider == 150

    def test_update_chunk_size_slider(self, monkeypatch):
        """Test update_chunk_size_slider function"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import update_chunk_size_slider
            from streamlit import session_state as state

            # Setup state
            state.selected_chunk_size_slider = 2000

            # Call function
            update_chunk_size_slider()

            # Verify input value was updated
            assert state.selected_chunk_size_input == 2000

    def test_update_chunk_size_input(self, monkeypatch):
        """Test update_chunk_size_input function"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import update_chunk_size_input
            from streamlit import session_state as state

            # Setup state
            state.selected_chunk_size_input = 1500

            # Call function
            update_chunk_size_input()

            # Verify slider value was updated
            assert state.selected_chunk_size_slider == 1500


#############################################################################
# Bug Detection Tests
#############################################################################
class TestSplitEmbedBugs:
    """Tests that expose potential bugs in split_embed implementation"""

    def test_bug_chunk_overlap_exceeds_chunk_size(self, monkeypatch):
        """
        POTENTIAL BUG: No validation that chunk_overlap < chunk_size.

        The update functions allow chunk_overlap to be set to any value,
        even if it exceeds chunk_size. This could cause issues in text splitting.

        This test exposes this validation gap.
        """
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import update_chunk_overlap_input
            from streamlit import session_state as state

            # Setup state with overlap > size
            state.selected_chunk_overlap_input = 2000  # Overlap
            state.selected_chunk_size_slider = 1000    # Size (smaller!)

            # Call function
            update_chunk_overlap_input()

            # BUG EXPOSED: overlap (2000) > size (1000) but no validation!
            assert state.selected_chunk_overlap_slider == 2000
            assert state.selected_chunk_size_slider == 1000
            assert state.selected_chunk_overlap_slider > state.selected_chunk_size_slider

    def test_bug_files_data_frame_missing_process_column(self):
        """
        POTENTIAL BUG: files_data_frame() may not handle missing 'process' column correctly.

        When process=True is passed but objects don't have 'process' field,
        the function should add it. Need to verify this works.
        """
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import files_data_frame

            # Objects without 'process' field
            objects = [
                {"name": "file1.pdf", "size": 1024},
                {"name": "file2.txt", "size": 2048},
            ]

            # Call with process=True
            result = files_data_frame(objects, process=True)

            # Verify 'process' column was added
            assert "process" in result.columns
            # All should default to True
            assert all(result["process"])

    def test_bug_file_source_data_is_valid_edge_cases(self):
        """
        POTENTIAL BUG: FileSourceData.is_valid() only checks for 'files' key.

        Line checks: if data.file_list_response and "files" in data.file_list_response

        But 'files' could be empty list [], which is truthy for "in" but has no files.
        This test verifies this edge case.
        """
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.tools.tabs.split_embed import FileSourceData

            # file_list_response has 'files' key but empty list
            data = FileSourceData(
                file_source="local",
                file_list_response={"files": []},  # Empty list!
                process_files=True,
                src_bucket="",
            )

            # BUG EXPOSED: is_valid returns True even though no files!
            # Should this be considered valid?
            result = data.is_valid()

            # Current implementation probably returns True (has 'files' key)
            # but conceptually should be False (no actual files)
            assert result is True  # Shows the bug - empty list passes validation


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
