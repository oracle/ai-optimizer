"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.oci.bucket.
"""
# spell-checker: disable

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from server.app.core.constants import SUPPORTED_EXTENSIONS
from server.app.oci.bucket import (
    detect_changed_objects,
    download_object,
    flatten_bucket_key,
    get_bucket_object_names,
    get_bucket_objects_with_metadata,
    get_buckets,
    get_compartments,
)
from server.app.oci.schemas import OciProfileConfig

MODULE = "server.app.oci.bucket"

pytestmark = [pytest.mark.unit]


def _make_profile(**overrides) -> OciProfileConfig:
    """Build a test OCI profile."""
    defaults = {
        "auth_profile": "TEST",
        "namespace": "test-namespace",
        "tenancy": "ocid1.tenancy.oc1..test",
        "region": "us-phoenix-1",
    }
    return OciProfileConfig(**{**defaults, **overrides})


def _make_bucket_object(name, size=1024, etag="abc123", time_modified=None, md5="md5hash"):
    """Build a mock bucket object as returned by OCI SDK."""
    obj = MagicMock()
    obj.name = name
    obj.size = size
    obj.etag = etag
    obj.time_modified = time_modified
    obj.md5 = md5
    return obj


# ---------------------------------------------------------------------------
# flatten_bucket_key
# ---------------------------------------------------------------------------


class TestFlattenBucketKey:
    """Test bucket key flattening."""

    def test_simple_filename(self):
        """Simple filename passes through unchanged."""
        assert flatten_bucket_key("file.pdf") == "file.pdf"

    def test_nested_path(self):
        """Slashes are replaced with underscores."""
        assert flatten_bucket_key("folder/subfolder/file.pdf") == "folder_subfolder_file.pdf"

    def test_leading_slash(self):
        """Leading underscore from leading slash is stripped."""
        assert flatten_bucket_key("/folder/file.pdf") == "folder_file.pdf"

    def test_deeply_nested(self):
        """Multiple levels of nesting flatten correctly."""
        assert flatten_bucket_key("a/b/c/d/e.txt") == "a_b_c_d_e.txt"

    def test_no_extension(self):
        """Files without extensions still flatten."""
        assert flatten_bucket_key("folder/README") == "folder_README"


# ---------------------------------------------------------------------------
# get_compartments / get_buckets pagination
# ---------------------------------------------------------------------------


def _make_compartment(compartment_id, name, parent_id):
    """Build a mock OCI compartment."""
    c = MagicMock()
    c.id = compartment_id
    c.name = name
    c.compartment_id = parent_id
    return c


class TestGetCompartmentsPagination:
    """Compartment listing must aggregate across all pages."""

    def test_aggregates_compartments_across_pages(self):
        """Compartments returned across multiple OCI pages all appear in the result."""
        tenancy = "ocid1.tenancy.oc1..test"
        page1 = [_make_compartment(f"ocid1.compartment.oc1..p1c{i}", f"p1c{i}", tenancy) for i in range(100)]
        page2 = [_make_compartment(f"ocid1.compartment.oc1..p2c{i}", f"p2c{i}", tenancy) for i in range(50)]
        aggregated_response = MagicMock(data=page1 + page2)
        mock_client = MagicMock()

        with (
            patch(f"{MODULE}.init_client", return_value=mock_client),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=aggregated_response,
            ) as mock_paginate,
        ):
            result = get_compartments(_make_profile(tenancy=tenancy))

        mock_paginate.assert_called_once()
        assert mock_paginate.call_args.args[0] is mock_client.list_compartments
        assert len(result) == 151
        assert result["(root)"] == tenancy
        assert "p1c0" in result
        assert "p2c49" in result


class TestGetBucketsPagination:
    """Bucket listing must aggregate across all pages."""

    def test_aggregates_buckets_across_pages(self):
        """Buckets returned across multiple OCI pages all appear in the result."""
        def _bucket(name, genai_chunk=False):
            b = MagicMock()
            b.name = name
            b.freeform_tags = {"genai_chunk": "true"} if genai_chunk else {}
            return b

        page1 = [_bucket(f"bucket-p1-{i}") for i in range(100)]
        page2 = [_bucket(f"bucket-p2-{i}") for i in range(25)]
        page2.append(_bucket("hidden-chunks", genai_chunk=True))
        aggregated_response = MagicMock(data=page1 + page2)
        mock_client = MagicMock()

        with (
            patch(f"{MODULE}.init_client", return_value=mock_client),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=aggregated_response,
            ) as mock_paginate,
        ):
            result = get_buckets("ocid1.compartment.oc1..test", _make_profile())

        mock_paginate.assert_called_once()
        assert mock_paginate.call_args.args[0] is mock_client.list_buckets
        assert len(result) == 125
        assert "bucket-p1-0" in result
        assert "bucket-p2-24" in result
        assert "hidden-chunks" not in result


# ---------------------------------------------------------------------------
# get_bucket_object_names pagination
# ---------------------------------------------------------------------------


class TestGetBucketObjectNamesPagination:
    """Object-name listing must aggregate across all pages.

    The single-call ``/v1/embed/oci/store`` endpoint embeds every
    supported object in the bucket when ``objects`` is omitted; a
    single ``list_objects`` page would leave later objects out of
    the resulting vector store.
    """

    def test_aggregates_object_names_across_pages(self):
        """Object names returned across multiple OCI pages all appear in the result."""
        page1 = [_make_bucket_object(f"page1-{i}.pdf") for i in range(100)]
        page2 = [_make_bucket_object(f"page2-{i}.pdf") for i in range(25)]
        aggregated_response = MagicMock()
        aggregated_response.data.objects = page1 + page2
        mock_client = MagicMock()

        with (
            patch(f"{MODULE}.init_client", return_value=mock_client),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=aggregated_response,
            ) as mock_paginate,
        ):
            result = get_bucket_object_names("test-bucket", _make_profile())

        mock_paginate.assert_called_once()
        assert mock_paginate.call_args.args[0] is mock_client.list_objects
        assert len(result) == 125
        assert "page1-0.pdf" in result
        assert "page2-24.pdf" in result


class TestGetBucketObjectsWithMetadataPagination:
    """Metadata listing must aggregate across all pages.

    ``/v1/embed/refresh`` enumerates the bucket via this helper to
    detect new and modified objects; a single ``list_objects`` page
    would treat objects beyond the first page as if they had been
    deleted (or never existed) for change-detection purposes.
    """

    def test_aggregates_metadata_across_pages(self):
        """Objects returned across multiple OCI pages all appear in the result."""
        page1 = [_make_bucket_object(f"page1-{i}.pdf") for i in range(100)]
        page2 = [_make_bucket_object(f"page2-{i}.pdf") for i in range(25)]
        aggregated_response = MagicMock()
        aggregated_response.data.objects = page1 + page2
        mock_client = MagicMock()

        with (
            patch(f"{MODULE}.init_client", return_value=mock_client),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=aggregated_response,
            ) as mock_paginate,
        ):
            result = get_bucket_objects_with_metadata("test-bucket", _make_profile())

        mock_paginate.assert_called_once()
        assert mock_paginate.call_args.args[0] is mock_client.list_objects
        assert len(result) == 125
        names = {r["name"] for r in result}
        assert "page1-0.pdf" in names
        assert "page2-24.pdf" in names


# ---------------------------------------------------------------------------
# get_bucket_objects_with_metadata
# ---------------------------------------------------------------------------


class TestGetBucketObjectsWithMetadata:
    """Test bucket object listing with metadata."""

    def test_returns_supported_extensions_only(self):
        """Only objects with supported extensions are included."""
        objects = [
            _make_bucket_object("doc.pdf"),
            _make_bucket_object("page.html"),
            _make_bucket_object("script.py"),
            _make_bucket_object("archive.zip"),
            _make_bucket_object("notes.txt"),
            _make_bucket_object("image.png"),
        ]
        mock_response = MagicMock()
        mock_response.data.objects = objects

        with (
            patch(f"{MODULE}.init_client", return_value=MagicMock()),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=mock_response,
            ),
        ):
            result = get_bucket_objects_with_metadata("test-bucket", _make_profile())

        names = {r["name"] for r in result}
        assert "doc.pdf" in names
        assert "page.html" in names
        assert "notes.txt" in names
        assert "image.png" in names
        assert "script.py" not in names
        assert "archive.zip" not in names

    def test_returns_correct_metadata_fields(self):
        """Returned dicts have the expected keys and values."""
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        objects = [_make_bucket_object("report.pdf", size=2048, etag="etag1", time_modified=ts, md5="abc")]
        mock_response = MagicMock()
        mock_response.data.objects = objects

        with (
            patch(f"{MODULE}.init_client", return_value=MagicMock()),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=mock_response,
            ),
        ):
            result = get_bucket_objects_with_metadata("test-bucket", _make_profile())

        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "report.pdf"
        assert entry["size"] == 2048
        assert entry["etag"] == "etag1"
        assert entry["time_modified"] == ts.isoformat()
        assert entry["md5"] == "abc"
        assert entry["extension"] == "pdf"

    def test_time_modified_none_handled(self):
        """Objects with time_modified=None produce None in result."""
        objects = [_make_bucket_object("data.csv", time_modified=None)]
        mock_response = MagicMock()
        mock_response.data.objects = objects

        with (
            patch(f"{MODULE}.init_client", return_value=MagicMock()),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=mock_response,
            ),
        ):
            result = get_bucket_objects_with_metadata("test-bucket", _make_profile())

        assert result[0]["time_modified"] is None

    def test_empty_bucket_returns_empty_list(self):
        """Empty bucket returns empty list."""
        mock_response = MagicMock()
        mock_response.data.objects = []

        with (
            patch(f"{MODULE}.init_client", return_value=MagicMock()),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=mock_response,
            ),
        ):
            result = get_bucket_objects_with_metadata("test-bucket", _make_profile())

        assert not result

    def test_service_error_returns_empty_list(self):
        """OCI ServiceError is caught and returns empty list."""
        import oci.exceptions

        with (
            patch(f"{MODULE}.init_client", return_value=MagicMock()),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                side_effect=oci.exceptions.ServiceError(
                    status=404, code="BucketNotFound", headers={}, message="not found",
                ),
            ),
        ):
            result = get_bucket_objects_with_metadata("test-bucket", _make_profile())

        assert not result

    def test_all_supported_extensions_accepted(self):
        """Every extension in SUPPORTED_EXTENSIONS is accepted."""
        objects = [_make_bucket_object(f"file{ext}") for ext in SUPPORTED_EXTENSIONS]
        mock_response = MagicMock()
        mock_response.data.objects = objects

        with (
            patch(f"{MODULE}.init_client", return_value=MagicMock()),
            patch(
                f"{MODULE}.oci.pagination.list_call_get_all_results",
                return_value=mock_response,
            ),
        ):
            result = get_bucket_objects_with_metadata("test-bucket", _make_profile())

        assert len(result) == len(SUPPORTED_EXTENSIONS)


# ---------------------------------------------------------------------------
# detect_changed_objects
# ---------------------------------------------------------------------------


class TestDetectChangedObjects:
    """Test change detection between current and processed objects."""

    def test_new_objects_detected(self):
        """Objects not in processed_objects are returned as new."""
        current = [{"name": "folder/new.pdf", "etag": "e1", "time_modified": "t1"}]
        processed = {}
        new, modified = detect_changed_objects(current, processed)
        assert len(new) == 1
        assert new[0]["name"] == "folder/new.pdf"
        assert not modified

    def test_modified_objects_detected_by_etag(self):
        """Objects with changed etag are returned as modified."""
        current = [{"name": "doc.pdf", "etag": "new-etag", "time_modified": "t1"}]
        processed = {"doc.pdf": {"etag": "old-etag", "time_modified": "t1"}}
        new, modified = detect_changed_objects(current, processed)
        assert not new
        assert len(modified) == 1

    def test_modified_objects_detected_by_time(self):
        """Objects with changed time_modified are returned as modified."""
        current = [{"name": "doc.pdf", "etag": "e1", "time_modified": "new-time"}]
        processed = {"doc.pdf": {"etag": "e1", "time_modified": "old-time"}}
        new, modified = detect_changed_objects(current, processed)
        assert not new
        assert len(modified) == 1

    def test_unchanged_objects_skipped(self):
        """Objects with matching etag and time_modified are skipped."""
        current = [{"name": "doc.pdf", "etag": "e1", "time_modified": "t1"}]
        processed = {"doc.pdf": {"etag": "e1", "time_modified": "t1"}}
        new, modified = detect_changed_objects(current, processed)
        assert not new
        assert not modified

    def test_old_format_metadata_skipped(self):
        """Objects in old metadata format (no etag/time_modified) assumed unchanged."""
        current = [{"name": "doc.pdf", "etag": "e1", "time_modified": "t1"}]
        processed = {"doc.pdf": {"etag": None, "time_modified": None}}
        new, modified = detect_changed_objects(current, processed)
        assert not new
        assert not modified

    def test_empty_current_objects(self):
        """Empty current_objects returns empty tuples."""
        new, modified = detect_changed_objects([], {"doc.pdf": {"etag": "e1", "time_modified": "t1"}})
        assert not new
        assert not modified

    def test_empty_processed_objects(self):
        """Empty processed_objects means all current objects are new."""
        current = [
            {"name": "a.pdf", "etag": "e1", "time_modified": "t1"},
            {"name": "b.pdf", "etag": "e2", "time_modified": "t2"},
        ]
        new, modified = detect_changed_objects(current, {})
        assert len(new) == 2
        assert not modified


# ---------------------------------------------------------------------------
# download_object
# ---------------------------------------------------------------------------


class TestDownloadObject:
    """Test object download from OCI bucket."""

    def test_downloads_and_returns_path(self, tmp_path):
        """Object is downloaded to local directory and path is returned."""
        mock_response = MagicMock()
        mock_response.data.raw.stream.return_value = [b"chunk1", b"chunk2"]
        mock_client = MagicMock()
        mock_client.get_object.return_value = mock_response

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = download_object(str(tmp_path), "report.pdf", "test-bucket", _make_profile())

        assert result == os.path.join(str(tmp_path), "report.pdf")
        with open(result, "rb") as f:
            assert f.read() == b"chunk1chunk2"

    def test_flattens_object_name_in_path(self, tmp_path):
        """Nested object names are flattened in the local file path."""
        mock_response = MagicMock()
        mock_response.data.raw.stream.return_value = [b"data"]
        mock_client = MagicMock()
        mock_client.get_object.return_value = mock_response

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = download_object(str(tmp_path), "folder/report.pdf", "test-bucket", _make_profile())

        assert os.path.basename(result) == "folder_report.pdf"
        assert os.path.exists(result)

    def test_propagates_exception_on_failure(self, tmp_path):
        """Exceptions from OCI SDK are not caught."""
        mock_client = MagicMock()
        mock_client.get_object.side_effect = RuntimeError("network error")

        with (
            patch(f"{MODULE}.init_client", return_value=mock_client),
            pytest.raises(RuntimeError, match="network error"),
        ):
            download_object(str(tmp_path), "file.pdf", "test-bucket", _make_profile())
