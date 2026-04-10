"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.core.file_utils shared utilities.
"""
# spell-checker: disable

from pathlib import Path

import pytest
from fastapi import HTTPException

from server.app.core.file_utils import get_temp_directory, safe_filename

# ---------------------------------------------------------------------------
# safe_filename
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_safe_filename_strips_traversal():
    """safe_filename strips directory components from malicious filenames."""
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("normal.pdf") == "normal.pdf"
    assert safe_filename("/absolute/path/file.txt") == "file.txt"


@pytest.mark.unit
@pytest.mark.parametrize("value", ["", ".", ".."])
def test_safe_filename_rejects_invalid(value):
    """safe_filename raises 400 for empty, '.', and '..' names."""
    with pytest.raises(HTTPException) as exc_info:
        safe_filename(value)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_temp_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_temp_directory_sanitizes_inputs():
    """get_temp_directory strips traversal segments from client/function."""
    assert safe_filename("../../tmp/evil") == "evil"
    assert safe_filename("normal") == "normal"


@pytest.mark.unit
def test_get_temp_directory_returns_path():
    """get_temp_directory returns an existing Path."""
    result = get_temp_directory("test_client", "test_func")
    assert isinstance(result, Path)
    assert result.exists()


@pytest.mark.unit
def test_get_temp_directory_unique():
    """get_temp_directory with unique=True returns distinct directories."""
    dir1 = get_temp_directory("test_client", "test_func", unique=True)
    dir2 = get_temp_directory("test_client", "test_func", unique=True)
    assert dir1 != dir2
    assert dir1.exists()
    assert dir2.exists()
