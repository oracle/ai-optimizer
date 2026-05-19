"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Response models for client config endpoint.
"""

from typing import Any

from pydantic import RootModel


class MCPClientConfigResponse(RootModel[dict[str, Any]]):
    """MCP client configuration response (passthrough dict)."""
