"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=too-many-arguments,too-many-positional-arguments

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from server.api.utils import oci as oci_utils
from common.schema import OracleCloudSettings


class TestGetBucketObjectsWithMetadata:
    """Test get_bucket_objects_with_metadata() function"""

    def setup_method(self):
        """Setup test data"""
        self.sample_oci_config = OracleCloudSettings(
            auth_profile="DEFAULT",
            namespace="test-namespace",
            compartment_id="ocid1.compartment.oc1..test",
            region="us-ashburn-1",
        )

    def create_mock_object(self, name, size, etag, time_modified, md5):
        """Create a mock OCI object"""
        mock_obj = MagicMock()
        mock_obj.name = name
        mock_obj.size = size
        mock_obj.etag = etag
        mock_obj.time_modified = time_modified
        mock_obj.md5 = md5
        return mock_obj

    @patch.object(oci_utils, "init_client")
    def test_get_bucket_objects_with_metadata_success(self, mock_init_client):
        """Test successful retrieval of bucket objects with metadata"""
        # Create mock objects
        time1 = datetime(2025, 11, 1, 10, 0, 0)
        time2 = datetime(2025, 11, 2, 10, 0, 0)

        mock_obj1 = self.create_mock_object(
            name="document1.pdf",
            size=1024000,
            etag="etag-123",
            time_modified=time1,
            md5="md5-hash-1"
        )
        mock_obj2 = self.create_mock_object(
            name="document2.txt",
            size=2048,
            etag="etag-456",
            time_modified=time2,
            md5="md5-hash-2"
        )

        # Mock client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data.objects = [mock_obj1, mock_obj2]
        mock_client.list_objects.return_value = mock_response
        mock_init_client.return_value = mock_client

        # Execute
        result = oci_utils.get_bucket_objects_with_metadata("test-bucket", self.sample_oci_config)

        # Verify
        assert len(result) == 2
        assert result[0]["name"] == "document1.pdf"
        assert result[0]["size"] == 1024000
        assert result[0]["etag"] == "etag-123"
        assert result[0]["time_modified"] == time1.isoformat()
        assert result[0]["md5"] == "md5-hash-1"
        assert result[0]["extension"] == "pdf"

        assert result[1]["name"] == "document2.txt"
        assert result[1]["size"] == 2048

        # Verify fields parameter was passed
        call_kwargs = mock_client.list_objects.call_args[1]
        assert "fields" in call_kwargs
        assert "name" in call_kwargs["fields"]
        assert "size" in call_kwargs["fields"]
        assert "etag" in call_kwargs["fields"]

    @patch.object(oci_utils, "init_client")
    def test_get_bucket_objects_filters_unsupported_types(self, mock_init_client):
        """Test that unsupported file types are filtered out"""
        # Create mock objects with various file types
        mock_pdf = self.create_mock_object("doc.pdf", 1000, "etag1", datetime.now(), "md5-1")
        mock_exe = self.create_mock_object("app.exe", 2000, "etag2", datetime.now(), "md5-2")
        mock_txt = self.create_mock_object("file.txt", 3000, "etag3", datetime.now(), "md5-3")
        mock_zip = self.create_mock_object("archive.zip", 4000, "etag4", datetime.now(), "md5-4")

        # Mock client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data.objects = [mock_pdf, mock_exe, mock_txt, mock_zip]
        mock_client.list_objects.return_value = mock_response
        mock_init_client.return_value = mock_client

        # Execute
        result = oci_utils.get_bucket_objects_with_metadata("test-bucket", self.sample_oci_config)

        # Verify only supported types are included
        assert len(result) == 2
        names = [obj["name"] for obj in result]
        assert "doc.pdf" in names
        assert "file.txt" in names
        assert "app.exe" not in names
        assert "archive.zip" not in names

    @patch.object(oci_utils, "init_client")
    def test_get_bucket_objects_empty_bucket(self, mock_init_client):
        """Test handling of empty bucket"""
        # Mock empty bucket
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data.objects = []
        mock_client.list_objects.return_value = mock_response
        mock_init_client.return_value = mock_client

        # Execute
        result = oci_utils.get_bucket_objects_with_metadata("empty-bucket", self.sample_oci_config)

        # Verify
        assert len(result) == 0

    @patch.object(oci_utils, "init_client")
    def test_get_bucket_objects_none_time_modified(self, mock_init_client):
        """Test handling of objects with None time_modified"""
        # Create mock object with None time_modified
        mock_obj = self.create_mock_object(
            name="document.pdf",
            size=1024,
            etag="etag-123",
            time_modified=None,
            md5="md5-hash"
        )

        # Mock client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data.objects = [mock_obj]
        mock_client.list_objects.return_value = mock_response
        mock_init_client.return_value = mock_client

        # Execute
        result = oci_utils.get_bucket_objects_with_metadata("test-bucket", self.sample_oci_config)

        # Verify time_modified is None
        assert len(result) == 1
        assert result[0]["time_modified"] is None


class TestDetectChangedObjects:
    """Test detect_changed_objects() function"""

    def test_detect_all_new_objects(self):
        """Test detection when all objects are new"""
        current_objects = [
            {"name": "file1.pdf", "etag": "etag1", "time_modified": "2025-11-01T10:00:00"},
            {"name": "file2.pdf", "etag": "etag2", "time_modified": "2025-11-02T10:00:00"},
        ]
        processed_objects = {}

        new_objects, modified_objects = oci_utils.detect_changed_objects(current_objects, processed_objects)

        assert len(new_objects) == 2
        assert len(modified_objects) == 0
        assert new_objects[0]["name"] == "file1.pdf"
        assert new_objects[1]["name"] == "file2.pdf"

    def test_detect_modified_objects_by_etag(self):
        """Test detection of modified objects by ETag change"""
        current_objects = [
            {"name": "file1.pdf", "etag": "etag1-new", "time_modified": "2025-11-01T10:00:00"},
            {"name": "file2.pdf", "etag": "etag2", "time_modified": "2025-11-02T10:00:00"},
        ]
        processed_objects = {
            "file1.pdf": {"etag": "etag1-old", "time_modified": "2025-11-01T10:00:00"},
            "file2.pdf": {"etag": "etag2", "time_modified": "2025-11-02T10:00:00"},
        }

        new_objects, modified_objects = oci_utils.detect_changed_objects(current_objects, processed_objects)

        assert len(new_objects) == 0
        assert len(modified_objects) == 1
        assert modified_objects[0]["name"] == "file1.pdf"
        assert modified_objects[0]["etag"] == "etag1-new"

    def test_detect_modified_objects_by_time(self):
        """Test detection of modified objects by modification time change"""
        current_objects = [
            {"name": "file1.pdf", "etag": "etag1", "time_modified": "2025-11-01T12:00:00"},
        ]
        processed_objects = {
            "file1.pdf": {"etag": "etag1", "time_modified": "2025-11-01T10:00:00"},
        }

        new_objects, modified_objects = oci_utils.detect_changed_objects(current_objects, processed_objects)

        assert len(new_objects) == 0
        assert len(modified_objects) == 1
        assert modified_objects[0]["name"] == "file1.pdf"

    def test_detect_no_changes(self):
        """Test detection when no changes exist"""
        current_objects = [
            {"name": "file1.pdf", "etag": "etag1", "time_modified": "2025-11-01T10:00:00"},
            {"name": "file2.pdf", "etag": "etag2", "time_modified": "2025-11-02T10:00:00"},
        ]
        processed_objects = {
            "file1.pdf": {"etag": "etag1", "time_modified": "2025-11-01T10:00:00"},
            "file2.pdf": {"etag": "etag2", "time_modified": "2025-11-02T10:00:00"},
        }

        new_objects, modified_objects = oci_utils.detect_changed_objects(current_objects, processed_objects)

        assert len(new_objects) == 0
        assert len(modified_objects) == 0

    def test_detect_mixed_changes(self):
        """Test detection with mix of new, modified, and unchanged objects"""
        current_objects = [
            {"name": "file1.pdf", "etag": "etag1", "time_modified": "2025-11-01T10:00:00"},  # unchanged
            {"name": "file2.pdf", "etag": "etag2-new", "time_modified": "2025-11-02T10:00:00"},  # modified
            {"name": "file3.pdf", "etag": "etag3", "time_modified": "2025-11-03T10:00:00"},  # new
        ]
        processed_objects = {
            "file1.pdf": {"etag": "etag1", "time_modified": "2025-11-01T10:00:00"},
            "file2.pdf": {"etag": "etag2-old", "time_modified": "2025-11-02T10:00:00"},
        }

        new_objects, modified_objects = oci_utils.detect_changed_objects(current_objects, processed_objects)

        assert len(new_objects) == 1
        assert len(modified_objects) == 1
        assert new_objects[0]["name"] == "file3.pdf"
        assert modified_objects[0]["name"] == "file2.pdf"

    def test_skip_old_format_objects(self):
        """Test that objects with old format (no etag/time_modified) are skipped"""
        current_objects = [
            {"name": "file1.pdf", "etag": "etag1", "time_modified": "2025-11-01T10:00:00"},
        ]
        processed_objects = {
            "file1.pdf": {"etag": None, "time_modified": None},  # Old format
        }

        new_objects, modified_objects = oci_utils.detect_changed_objects(current_objects, processed_objects)

        # Should skip the old format object to avoid duplicates
        assert len(new_objects) == 0
        assert len(modified_objects) == 0
