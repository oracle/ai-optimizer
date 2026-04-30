"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for _version.py

Tests version string retrieval.
"""


class TestVersion:
    """Tests for __version__ variable."""

    def test_version_fallback_on_package_not_found(self):
        """__version__ falls back to '0.0.0' when the package is not installed."""
        import importlib
        from importlib.metadata import PackageNotFoundError
        from unittest.mock import patch

        import _version as version_module

        with patch("importlib.metadata.version", side_effect=PackageNotFoundError("ai-optimizer")):
            importlib.reload(version_module)
            assert version_module.__version__ == "0.0.0"
        # Restore original state
        importlib.reload(version_module)
