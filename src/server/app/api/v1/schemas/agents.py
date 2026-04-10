"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Request / response models for agent spec endpoints.
"""

from typing import Optional

from pydantic import BaseModel

from server.app.api.v1.schemas.chat import VsMetadata


class AgentExecuteRequest(BaseModel):
    """Request body for executing an agent pipeline."""

    question: str
    chat_history: list[str] = []


class AgentExecuteResponse(BaseModel):
    """Response from an agent pipeline execution."""

    status: str
    result: Optional[dict] = None
    messages: Optional[list[dict]] = None
    route: Optional[str] = None
    vs_metadata: Optional[VsMetadata] = None


class AgentSpecResponse(BaseModel):
    """Serialized agent spec definition."""

    name: str
    description: str
    spec: dict
