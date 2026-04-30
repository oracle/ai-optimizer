"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic schemas for v1 prompt CRUD endpoints.
"""

from pydantic import BaseModel, Field


class PromptResponse(BaseModel):
    """Prompt returned by v1 endpoints."""

    name: str = Field(..., description="MCP prompt name")
    description: str = Field(default="", description="Prompt purpose and usage")
    text: str = Field(..., description="Effective prompt text")


class PromptUpdate(BaseModel):
    """Request body for updating a prompt's text."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "text": "You are an expert technical writer. Rewrite the user's text "
                "to be clear, concise, and free of jargon.",
            }
        }
    }

    text: str = Field(..., description="New prompt text")
