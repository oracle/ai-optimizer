"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Chat endpoints — replaces LangGraph-backed ``/completions``, ``/streams``, ``/history``.
"""
# spell-checker:ignore acompletion

import json
import logging
from typing import Annotated
from urllib.parse import urlunparse

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from server.app.api.v1.schemas.chat import (
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    StreamChunkEvent,
    StreamCompletionEvent,
    StreamErrorEvent,
    StreamStatusEvent,
    TokenUsage,
    VsMetadata,
)
from server.app.api.v1.schemas.common import ClientId
from server.app.core.secrets import reveal
from server.app.core.settings import resolve_client, settings
from server.app.runtime.common import LLMConfigurationError, clean_llm_error
from server.app.runtime.langgraph.chat import ChatOrchestrator

LOGGER = logging.getLogger(__name__)

auth = APIRouter(prefix="/chat")

_WILDCARD_CONNECT_HOSTS = {
    "0.0.0.0": "127.0.0.1",
    "::": "::1",
    "0:0:0:0:0:0:0:0": "::1",
}


def _connect_host(host: str | None) -> str:
    raw = (host or "").strip()
    normalized = raw.strip("[]").casefold()
    return _WILDCARD_CONNECT_HOSTS.get(normalized, raw or "127.0.0.1")


def _netloc(host: str, port: int | None) -> str:
    bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{bracketed}:{port}" if port else bracketed


def _internal_mcp_url(
    *,
    server_address: str | None = None,
    server_port: int | None = None,
    server_url_prefix: str | None = None,
    server_ssl: bool | None = None,
) -> str:
    """Return the server-local MCP URL used by chat tool orchestration."""
    scheme = "https" if (settings.server_ssl if server_ssl is None else server_ssl) else "http"
    host = _connect_host(settings.server_address if server_address is None else server_address)
    port = settings.server_port if server_port is None else server_port
    prefix = settings.server_url_prefix if server_url_prefix is None else server_url_prefix
    prefix = prefix.strip().rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = f"/{prefix}"
    return urlunparse((scheme, _netloc(host, port), f"{prefix}/mcp/", "", "", ""))


_orchestrator = ChatOrchestrator(
    server_url=_internal_mcp_url(),
    api_key=lambda: reveal(settings.api_key) or "",
    resolve_client=resolve_client,
)


def get_orchestrator() -> ChatOrchestrator:
    """Return the module-level orchestrator (for use by other endpoints)."""
    return _orchestrator


@auth.post("/completions", response_model=ChatResponse)
async def chat_completions(
    body: ChatRequest,
    client: Annotated[ClientId, Header()] = "server",
):
    """Full (non-streaming) chat completion.

    Routes automatically based on ``settings.client_settings.tools_enabled``.
    """
    question = _last_user_message(body)

    try:
        result = await _orchestrator.execute_chat(
            question=question,
            client=client,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        LOGGER.error("Chat completion failed: %s", exc)
        raise HTTPException(status_code=502, detail=clean_llm_error(exc)) from exc

    content = result.get("result", "") or ""
    if isinstance(content, dict):
        content = json.dumps(content, default=str)

    return ChatResponse(
        role="assistant",
        content=content,
        route=result.get("route"),
        vs_metadata=result.get("vs_metadata"),
        token_usage=result.get("token_usage"),
    )


@auth.post("/streams")
async def chat_stream(
    body: ChatRequest,
    client: Annotated[ClientId, Header()] = "server",
):
    """Streaming chat completion via ``StreamingResponse``.

    Routes automatically based on ``settings.client_settings.tools_enabled``.
    """
    question = _last_user_message(body)

    async def _generate():
        collected = []
        route = None
        vs_metadata = None
        token_usage = None
        try:
            async for event in _orchestrator.execute_chat_stream(
                question=question,
                client=client,
            ):
                etype = event.get("type", "")
                if etype == "stream":
                    chunk = event["content"]
                    collected.append(chunk)
                    yield f"data: {json.dumps(StreamChunkEvent(content=chunk).model_dump())}\n\n"
                elif etype == "_meta":
                    route = event.get("route")
                    vs_metadata = event.get("vs_metadata")
                elif etype == "_token_usage":
                    token_usage = TokenUsage(
                        prompt_tokens=event.get("prompt_tokens", 0),
                        completion_tokens=event.get("completion_tokens", 0),
                        total_tokens=event.get("total_tokens", 0),
                    )
                elif etype == "status":
                    yield f"data: {json.dumps(StreamStatusEvent(content=event['content']).model_dump())}\n\n"
                elif etype == "error":
                    yield f"data: {json.dumps(StreamErrorEvent(content=event.get('content', '')).model_dump())}\n\n"
                    yield "data: [DONE]\n\n"
                    return
        except Exception as exc:
            LOGGER.error("Streaming completion failed: %s", exc)
            yield f"data: {json.dumps(StreamErrorEvent(content=clean_llm_error(exc)).model_dump())}\n\n"
            yield "data: [DONE]\n\n"
            return

        full_content = "".join(collected)

        vs_metadata_obj = VsMetadata.model_validate(vs_metadata) if vs_metadata else None
        completion = StreamCompletionEvent(
            content=full_content,
            route=route,
            vs_metadata=vs_metadata_obj,
            token_usage=token_usage,
        )
        yield f"data: {json.dumps(completion.model_dump(exclude_none=True), default=str)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
    )


@auth.get("/history", response_model=ChatHistoryResponse)
async def chat_history_return(client: Annotated[ClientId, Header()] = "server"):
    """Get conversation history for a client."""
    return ChatHistoryResponse(client=client, messages=_orchestrator.history.get(client))


@auth.patch("/history", response_model=ChatHistoryResponse)
async def chat_history_clean(client: Annotated[ClientId, Header()] = "server"):
    """Clear conversation history for a client."""
    _orchestrator.clear_history(client)
    return ChatHistoryResponse(client=client, messages=[], cleared=True)


def _last_user_message(body: ChatRequest) -> str:
    """Extract the last user message from the request body."""
    for msg in reversed(body.messages):
        if msg.role == "user" and msg.content:
            return msg.content
    raise HTTPException(status_code=400, detail="No user message provided")
