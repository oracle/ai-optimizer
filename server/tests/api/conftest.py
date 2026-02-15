"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared helpers for API test modules.
"""

MODULES_TO_RELOAD = (
    "server.app.main",
    "server.app.core.config",
    "server.app.api.deps",
    "server.app.api.v1.router",
    "server.app.api.v1.endpoints.probes",
    "server.app.database",
    "server.app.database.config",
)
