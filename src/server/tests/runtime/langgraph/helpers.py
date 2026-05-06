"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared mock factories for LangGraph runtime tests.
"""
# spell-checker: disable

import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, LLMResult


def mock_compiled_graph(
    result: Optional[Dict[str, Any]] = None,
    side_effect: Optional[Exception] = None,
    usage_metadata: Optional[Dict[str, int]] = None,
    model_name: str = "test-model",
    stream_chunks: Optional[Sequence[str]] = None,
) -> MagicMock:
    """Mock a compiled LangGraph (CompiledGraph) with ``ainvoke`` and ``astream_events``.

    When *usage_metadata* is provided, both ``ainvoke`` and ``astream_events``
    fire ``on_llm_end`` on every callback present in ``config["callbacks"]`` so
    ``UsageMetadataCallbackHandler``-based aggregation observes a usage record
    without wiring up a real LLM.

    When *stream_chunks* is provided, ``astream_events`` emits one
    ``on_chat_model_stream`` event per chunk in addition to the chain
    start/end events used by ``_astream_graph_to_queue`` to surface the
    final output.

    Parameters
    ----------
    result:
        The dict returned by ``graph.ainvoke()`` and surfaced as the
        ``on_chain_end`` output for ``astream_events``. Defaults to a minimal
        flow-style result with an empty answer.
    side_effect:
        If provided, ``ainvoke`` and ``astream_events`` raise this exception
        instead of returning.
    usage_metadata:
        Optional ``{"input_tokens", "output_tokens", "total_tokens"}`` dict
        delivered to callbacks via a synthetic ``on_llm_end`` event.
    model_name:
        The model name used to key the callback's per-model usage dict.
    stream_chunks:
        Optional content strings emitted as ``on_chat_model_stream`` events
        from ``astream_events``.
    """
    if result is None:
        result = {"outputs": {"answer": "answer"}, "messages": []}

    graph = MagicMock()

    def _fire_usage_callback(callbacks: Sequence[Any]) -> None:
        if not usage_metadata:
            return
        for cb in callbacks or []:
            on_end = getattr(cb, "on_llm_end", None)
            if on_end is None:
                continue
            msg = AIMessage(
                content="",
                usage_metadata=usage_metadata,
                response_metadata={"model_name": model_name},
            )
            on_end(LLMResult(generations=[[ChatGeneration(message=msg)]]))

    if side_effect is not None:
        graph.ainvoke = AsyncMock(side_effect=side_effect)

        async def _failing_astream(*_args, **_kwargs) -> AsyncIterator[Dict[str, Any]]:
            raise side_effect  # type: ignore[misc]
            yield  # pragma: no cover

        graph.astream_events = _failing_astream
    else:

        async def fake_ainvoke(_inputs, config=None, **_kwargs):
            _fire_usage_callback((config or {}).get("callbacks", []) or [])
            return result

        graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)

        async def fake_astream_events(_inputs, config=None, **_kwargs) -> AsyncIterator[Dict[str, Any]]:
            run_id = str(uuid.uuid4())
            yield {"event": "on_chain_start", "name": "MockGraph", "run_id": run_id, "data": {}}
            for content in stream_chunks or ():
                chunk = AIMessageChunk(content=content)
                yield {
                    "event": "on_chat_model_stream",
                    "name": "MockChatModel",
                    "run_id": str(uuid.uuid4()),
                    "data": {"chunk": chunk},
                }
            _fire_usage_callback((config or {}).get("callbacks", []) or [])
            yield {
                "event": "on_chain_end",
                "name": "MockGraph",
                "run_id": run_id,
                "data": {"output": result},
            }

        graph.astream_events = fake_astream_events

    graph.nodes = {}
    return graph


def mock_litellm_response(
    content: str = "",
    usage: Optional[Any] = None,
    tool_calls: Optional[List] = None,
) -> MagicMock:
    """Create a mock litellm ModelResponse."""
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    resp.choices = [choice]
    resp.usage = usage
    return resp


def make_usage(prompt_tokens: int = 10, completion_tokens: int = 5, total_tokens: int = 15) -> MagicMock:
    """Create a mock usage object."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens
    return usage
