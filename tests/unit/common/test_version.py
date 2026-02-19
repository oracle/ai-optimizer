"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for common/_version.py

Tests version string retrieval.
"""

from common._version import __version__


class TestVersion:
    """Tests for __version__ variable."""

    def test_version_is_string(self):
        """__version__ should be a string."""
        assert isinstance(__version__, str)

    def test_version_is_non_empty(self):
        """__version__ should be non-empty."""
        assert len(__version__) > 0

    def test_version_format(self):
        """__version__ should be a valid version string or fallback."""
        # Version should either be a proper version number or the fallback "0.0.0"
        # Valid versions can be like "1.0.0", "1.0.0.dev1", "1.3.1.dev128+g867d96f69.d20251126"
        assert __version__ == "0.0.0" or "." in __version__

    def test_version_no_leading_whitespace(self):
        """__version__ should not have leading whitespace."""
        assert __version__ == __version__.lstrip()

    def test_version_no_trailing_whitespace(self):
        """__version__ should not have trailing whitespace."""
        assert __version__ == __version__.rstrip()
