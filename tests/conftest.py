"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Root pytest configuration for the test suite.

This conftest.py uses pytest_plugins to automatically load fixtures from:
- tests.shared_fixtures: Factory fixtures (make_database, make_model, etc.)
- tests.db_fixtures: Database container fixtures (db_container, db_connection, etc.)

All fixtures defined in these modules are automatically available to all tests
without needing explicit imports in child conftest.py files.

Constants and helper functions (e.g., TEST_DB_CONFIG, assert_model_list_valid)
still require explicit imports in the test files that use them.
"""

# pytest_plugins automatically loads fixtures from these modules
# This replaces scattered "from tests.shared_fixtures import ..." across conftest files
pytest_plugins = [
    "tests.shared_fixtures",
    "tests.db_fixtures",
]
