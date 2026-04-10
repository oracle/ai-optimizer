"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared mock factories for LangGraph runtime tests.
"""
# spell-checker: disable

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

from server.app.runtime.langgraph.adapters.litellm import ChatLiteLLMBridge


def mock_compiled_graph(
    result: Optional[Dict[str, Any]] = None,
    side_effect: Optional[Exception] = None,
) -> MagicMock:
    """Mock a compiled LangGraph (CompiledGraph) with ainvoke.

    Parameters
    ----------
    result:
        The dict returned by ``graph.ainvoke()``.  Defaults to a minimal
        flow-style result with an empty answer.
    side_effect:
        If provided, ``ainvoke`` raises this exception instead of returning.
    """
    if result is None:
        result = {"outputs": {"answer": "answer"}, "messages": []}
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=result, side_effect=side_effect)
    graph.nodes = {}
    return graph


def mock_graph_node(llm) -> MagicMock:
    """Build a mock graph node with a bound runnable containing the given LLM.

    Sets ``node.bound = None`` so ``_extract_llm_instances`` falls through
    to the ``node.runnable`` path.
    """
    node = MagicMock()
    node.bound = None
    node.runnable = MagicMock()
    node.runnable.bound = llm
    node.runnable.graph = None
    return node


def mock_graph_with_llm(
    result: Optional[Dict[str, Any]] = None,
    token_usage: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Mock graph with an extractable ChatLiteLLMBridge node.

    Returns (graph, llm_instance) so tests can inspect token usage.
    """
    if result is None:
        result = {"outputs": {"answer": "answer"}, "messages": []}
    graph = mock_compiled_graph(result=result)

    llm = ChatLiteLLMBridge(model="test/model")
    llm.last_token_usage = token_usage

    graph.nodes = {"llm_node": mock_graph_node(llm)}

    return graph, llm


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
