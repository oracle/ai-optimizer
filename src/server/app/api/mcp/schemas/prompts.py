"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic schemas for MCP prompt REST endpoints.
"""

from pydantic import BaseModel, Field


class PromptResponse(BaseModel):
    """Prompt configuration returned by the MCP API."""

    name: str = Field(..., description="MCP prompt name")
    description: str = Field(default="", description="Prompt purpose and usage")
    text: str = Field(..., description="Effective prompt text")
