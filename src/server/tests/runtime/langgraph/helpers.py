"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared mock factories for LangGraph runtime tests.
"""
# spell-checker: disable

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult


def mock_compiled_graph(
    result: Optional[Dict[str, Any]] = None,
    side_effect: Optional[Exception] = None,
    usage_metadata: Optional[Dict[str, int]] = None,
    model_name: str = "test-model",
) -> MagicMock:
    """Mock a compiled LangGraph (CompiledGraph) with ``ainvoke``.

    When *usage_metadata* is provided, ``ainvoke`` also fires
    ``on_llm_end`` on every callback present in ``config["callbacks"]`` so
    ``UsageMetadataCallbackHandler``-based aggregation observes a usage
    record without wiring up a real LLM.

    Parameters
    ----------
    result:
        The dict returned by ``graph.ainvoke()``.  Defaults to a minimal
        flow-style result with an empty answer.
    side_effect:
        If provided, ``ainvoke`` raises this exception instead of returning.
    usage_metadata:
        Optional ``{"input_tokens", "output_tokens", "total_tokens"}`` dict
        delivered to callbacks via a synthetic ``on_llm_end`` event.
    model_name:
        The model name used to key the callback's per-model usage dict.
    """
    if result is None:
        result = {"outputs": {"answer": "answer"}, "messages": []}

    graph = MagicMock()

    if side_effect is not None:
        graph.ainvoke = AsyncMock(side_effect=side_effect)
    elif usage_metadata is None:
        graph.ainvoke = AsyncMock(return_value=result)
    else:

        async def fake_ainvoke(_inputs, config=None, **_kwargs):
            for cb in (config or {}).get("callbacks", []) or []:
                on_end = getattr(cb, "on_llm_end", None)
                if on_end is None:
                    continue
                msg = AIMessage(
                    content="",
                    usage_metadata=usage_metadata,
                    response_metadata={"model_name": model_name},
                )
                on_end(LLMResult(generations=[[ChatGeneration(message=msg)]]))
            return result

        graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)

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
