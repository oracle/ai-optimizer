"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Response models for probe endpoints.
"""

from pydantic import BaseModel


class MCPHealthResponse(BaseModel):
    """Response for the MCP health probe."""

    status: str
    name: str
    version: str
    available_tools: list[str]
