"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Ollama tool-calling helpers shared by the LangGraph and WayFlow adapters.

Ollama's /api/chat native tool calling fails on hyphenated function names
(e.g. ``sqlcl_list-connections``).  These helpers sanitize names to
underscores before sending and restore the originals on the way back.

Small Ollama models (e.g. llama3.1 8B) also hallucinate when tool results
are terse single-word values.  ``contextualize_tool_result`` prefixes
the result so the model understands what it represents.
"""

import copy
from typing import Any, Dict, List, Optional, Tuple


def is_ollama_model(model: str) -> bool:
    """Return True if *model* targets an Ollama provider."""
    return model.startswith("ollama/") or model.startswith("ollama_chat/")


def sanitize_tool_name(name: str) -> str:
    """Replace hyphens with underscores in a tool function name."""
    return name.replace("-", "_")


def unsanitize_tool_name(name: str, name_map: Optional[Dict[str, str]]) -> str:
    """Restore the original hyphenated tool name from a sanitized version."""
    if name_map and name in name_map:
        return name_map[name]
    return name


def sanitize_tools(tools: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Sanitize hyphenated function names in OpenAI-format tool definitions.

    Returns ``(sanitized_tools, name_map)`` where *name_map* maps each
    sanitized name back to its original so callers can restore them.
    """
    sanitized: List[Dict[str, Any]] = []
    name_map: Dict[str, str] = {}
    for tool in tools:
        tool = copy.deepcopy(tool)  # noqa: PLW2901
        original = tool["function"]["name"]
        clean = sanitize_tool_name(original)
        if clean != original:
            tool["function"]["name"] = clean
            name_map[clean] = original
        sanitized.append(tool)
    return sanitized, name_map


def contextualize_tool_result(tool_name: str, content: str) -> str:
    """Prefix a tool result with the tool name for small-model clarity."""
    return f"Result of {tool_name}: {content}"


def normalize_ollama_provider(provider: str, model_type: str = "ll") -> str:
    """Normalize ``ollama`` to ``ollama_chat`` for LLM models.

    Embedding models stay on ``ollama/`` (they use ``/api/embed``).
    """
    if provider == "ollama" and model_type == "ll":
        return "ollama_chat"
    return provider
