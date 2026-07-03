"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared mock factories and helpers used by runtime tests.
"""
# spell-checker: disable

import asyncio
import json
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Optional
from unittest.mock import MagicMock

from server.tests.constants import TEST_OLLAMA_MODEL_ID

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse

    from server.app.oci.schemas import OciProfileConfig


@contextmanager
def temporary_oci_configs(
    profiles: "Iterable[OciProfileConfig]",
    client_auth_profile: Optional[str] = None,
) -> Iterator[None]:
    """Install *profiles* in ``settings.oci_configs`` for the test body, then restore."""
    from server.app.core.settings import settings

    saved_oci = settings.oci_configs
    saved_auth = settings.client_settings.oci.auth_profile
    settings.oci_configs = list(profiles)
    if client_auth_profile is not None:
        settings.client_settings.oci.auth_profile = client_auth_profile
    try:
        yield
    finally:
        settings.oci_configs = saved_oci
        settings.client_settings.oci.auth_profile = saved_auth


def ollama_available(model_id: str = TEST_OLLAMA_MODEL_ID) -> bool:
    """Return True if Ollama is reachable and has *model_id* available."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
            payload = json.load(response)
        return any(model.get("name") == model_id for model in payload.get("models", []))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, AttributeError):
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
    model_id=TEST_OLLAMA_MODEL_ID,
    tools_enabled=None,
    chat_history=True,
    auth_profile="DEFAULT",
):
    """Build a mock ClientSettings."""
    cs = MagicMock()
    cs.ll_model.provider = provider
    cs.ll_model.id = model_id
    cs.ll_model.chat_history = chat_history
    cs.tools_enabled = tools_enabled or []
    cs.oci.auth_profile = auth_profile
    cs.model_dump.return_value = {
        "ll_model": {
            "provider": provider,
            "id": model_id,
            "chat_history": chat_history,
        },
        "database": {"alias": "CORE"},
        "oci": {"auth_profile": auth_profile},
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
