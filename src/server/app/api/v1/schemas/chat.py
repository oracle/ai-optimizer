"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Request / response models for chat endpoints — no LangChain dependency.
"""

from typing import Literal, Optional

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Shared typed models
# ---------------------------------------------------------------------------


class TokenUsage(BaseModel):
    """Token consumption for a single request."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class VsMetadata(BaseModel):
    """Vector search metadata returned with chat responses."""

    documents: list[dict] = []
    searched_tables: Optional[list[str]] = None
    context_input: Optional[str] = None


class SqlMetadata(BaseModel):
    """SQL execution metadata returned with chat responses."""

    executed_sql: list[str] = []


# ---------------------------------------------------------------------------
# Chat request / response
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """Request body for chat completions."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "model": "openai/gpt-5.4-mini",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Summarize the latest sales report."},
                ],
            }
        }
    }

    model: Optional[str] = None
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    """Response from a chat completion."""

    role: str
    content: str
    route: Optional[str] = None
    vs_metadata: Optional[VsMetadata] = None
    sql_metadata: Optional[SqlMetadata] = None
    token_usage: Optional[TokenUsage] = None


# ---------------------------------------------------------------------------
# SSE streaming event models
# ---------------------------------------------------------------------------


class StreamChunkEvent(BaseModel):
    """SSE chunk event."""

    type: Literal["stream"] = "stream"
    content: str


class StreamStatusEvent(BaseModel):
    """SSE status event."""

    type: Literal["status"] = "status"
    content: str


class StreamErrorEvent(BaseModel):
    """SSE error event."""

    type: Literal["error"] = "error"
    content: str


class StreamCompletionEvent(BaseModel):
    """SSE completion event."""

    type: Literal["completion"] = "completion"
    content: str
    route: Optional[str] = None
    vs_metadata: Optional[VsMetadata] = None
    sql_metadata: Optional[SqlMetadata] = None
    token_usage: Optional[TokenUsage] = None


# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str


class ChatHistoryResponse(BaseModel):
    """Response for chat history endpoints."""

    client: str
    messages: list[dict] = []
    cleared: Optional[bool] = None
