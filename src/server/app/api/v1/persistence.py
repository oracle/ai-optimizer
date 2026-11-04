"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Runtime API persistence helpers.
"""

from collections.abc import Awaitable

from server.app.database.config import CoreDatabaseUnavailable


async def persistence_succeeded(operation: Awaitable[bool]) -> bool:
    """Return false when a required CORE write cannot complete."""
    try:
        return await operation
    except CoreDatabaseUnavailable:
        return False
