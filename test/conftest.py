"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for unit tests with real Oracle database.

Re-exports shared database fixtures from test.db_fixtures.
"""

# Re-export shared fixtures for pytest discovery
from test.db_fixtures import (
    TEST_DB_CONFIG,
    db_container,
    db_connection,
    db_transaction,
)

# Expose TEST_CONFIG alias for backwards compatibility
TEST_CONFIG = TEST_DB_CONFIG

__all__ = [
    "TEST_CONFIG",
    "TEST_DB_CONFIG",
    "db_container",
    "db_connection",
    "db_transaction",
]
