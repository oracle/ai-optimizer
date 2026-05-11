"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared mock factories and helpers used by runtime tests.
"""
# spell-checker: disable

import asyncio
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse


def ollama_available() -> bool:
    """Return True if ollama is reachable at the default endpoint."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434", timeout=2):
            pass
        return True
    except (urllib.error.URLError, OSError):
        return False


# ---------------------------------------------------------------------------
# Mock streaming chunk factories
# ---------------------------------------------------------------------------


def make_stream_chunk(content=None, finish_reason=None, tool_calls=None, usage=None):
    """Build a mock LiteLLM streaming chunk."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls

    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason

    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


def make_usage_chunk(prompt_tokens=10, completion_tokens=5, total_tokens=15):
    """Build a mock streaming chunk carrying only token-usage data."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens
    return make_stream_chunk(content="", finish_reason="stop", usage=usage)


def make_empty_choice_usage_chunk(prompt_tokens=10, completion_tokens=5, total_tokens=15):
    """Build a mock streaming chunk with ``choices=[]`` carrying only usage.

    Mirrors the real terminal chunk OpenAI-compatible providers emit when
    ``stream_options={"include_usage": True}`` is requested: usage is set
    but there is no choice/delta to read.
    """
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens
    chunk = MagicMock()
    chunk.choices = []
    chunk.usage = usage
    return chunk


async def async_iter(items):
    """Yield *items* as an async iterator."""
    for item in items:
        yield item


def drain_queue(queue: asyncio.Queue) -> list:
    """Drain all events from an asyncio.Queue into a list."""
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# ---------------------------------------------------------------------------
# Mock client settings
# ---------------------------------------------------------------------------


def mock_client_settings(
    provider="ollama",
    model_id="qwen3:8b",
    tools_enabled=None,
    chat_history=True,
):
    """Build a mock ClientSettings."""
    cs = MagicMock()
    cs.ll_model.provider = provider
    cs.ll_model.id = model_id
    cs.ll_model.chat_history = chat_history
    cs.tools_enabled = tools_enabled or []
    cs.model_dump.return_value = {
        "ll_model": {
            "provider": provider,
            "id": model_id,
            "chat_history": chat_history,
        },
        "database": {"alias": "CORE"},
        "vector_search": {},
    }
    return cs


# ---------------------------------------------------------------------------
# Mock litellm response
# ---------------------------------------------------------------------------


def mock_litellm_response(content: str, usage: Any = None) -> "ModelResponse":
    """Create a mock litellm response with the given content."""
    from litellm.types.utils import Choices, Message
    from litellm.types.utils import ModelResponse as LiteLLMModelResponse

    return LiteLLMModelResponse(
        choices=[Choices(message=Message(content=content, role="assistant"))],
        usage=usage,
    )
