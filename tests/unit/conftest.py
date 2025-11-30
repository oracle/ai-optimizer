"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest configuration for unit tests.

This conftest automatically marks all tests in the test/unit/ directory
with the 'unit' marker, enabling selective test execution:

    pytest -m "unit"           # Run only unit tests
    pytest -m "not unit"       # Skip unit tests
    pytest -m "unit and not slow"  # Fast unit tests only
"""

import pytest


def pytest_collection_modifyitems(items):
    """Automatically add 'unit' marker to all tests in this directory."""
    for item in items:
        # Check if the test is under test/unit/
        if "/test/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
