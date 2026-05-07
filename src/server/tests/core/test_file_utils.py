"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.core.file_utils shared utilities.
"""
# spell-checker: disable

from pathlib import Path

import pytest

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
    """safe_filename raises ValueError for empty, '.', and '..' names.

    Endpoints translate the ValueError to ``HTTPException(400)``; this
    keeps the helper framework-agnostic.
    """
    with pytest.raises(ValueError):
        safe_filename(value)


# ---------------------------------------------------------------------------
# The `temp_directory / safe_filename(name)` composition must keep saved files
# under temp_directory for path-like client input. These assertions protect
# call sites that join upload-provided filenames into staging directories.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        "../../../up/file",
        "/abs/launch.py",
        "/abs/server/main.py",
        "../../../../home/user/.ssh/authorized_keys",
        "..\\..\\windows\\system32\\drivers\\etc\\hosts",
        "subdir/../sibling.sh",
    ],
)
def test_safe_filename_confines_path_to_temp_directory(tmp_path, payload):
    """safe_filename keeps the resolved path inside the intended temp_directory."""
    temp_directory = tmp_path / "client" / "embedding"
    temp_directory.mkdir(parents=True)
    resolved = (temp_directory / safe_filename(payload)).resolve()
    assert resolved.is_relative_to(temp_directory.resolve()), (
        f"Payload {payload!r} escaped temp_directory: {resolved}"
    )


# ---------------------------------------------------------------------------
# get_temp_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_temp_directory_sanitizes_inputs():
    """get_temp_directory strips path segments from client/function."""
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
