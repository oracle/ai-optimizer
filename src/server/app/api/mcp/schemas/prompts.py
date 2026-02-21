"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic schemas for MCP prompt REST endpoints.
"""

from pydantic import BaseModel, Field


class PromptResponse(BaseModel):
    """Prompt configuration returned by the API."""

    name: str = Field(..., description="MCP prompt name")
    title: str = Field(..., description="Human-readable title")
    description: str = Field(default="", description="Prompt purpose and usage")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    text: str = Field(..., description="Effective prompt text")
    customized: bool = Field(default=False, description="True when user has overridden the default text")


class PromptUpdate(BaseModel):
    """Request body for updating a prompt's text."""

    text: str = Field(..., description="New prompt text")
