"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest configuration for integration tests.

This conftest automatically marks all tests in the test/integration/ directory
with the 'integration' marker, enabling selective test execution:

    pytest -m "integration"           # Run only integration tests
    pytest -m "not integration"       # Skip integration tests
    pytest -m "integration and not db"  # Integration tests without DB
"""

import pytest


def pytest_collection_modifyitems(items):
    """Automatically add 'integration' marker to all tests in this directory."""
    for item in items:
        # Check if the test is under test/integration/
        if "/test/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
