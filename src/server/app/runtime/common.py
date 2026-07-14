"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared runtime utilities used by the LangGraph runtime.
"""
# spell-checker: ignore vecsearch litellm acompletion agentspec genai

import json
import logging
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel

from server.app.agentspec.adapters.mcp import fetch_mcp_prompt
from server.app.api.v1.schemas.chat import SqlMetadata, TokenUsage, VsMetadata
from server.app.core.schemas import TOOL_NL2SQL, TOOL_VECSEARCH
from server.app.mcp.prompts.registry import require_factory_text

LOGGER = logging.getLogger(__name__)


class LLMConfigurationError(Exception):
    """Raised when the LLM provider or model ID is not configured."""


def clean_llm_error(exc: BaseException) -> str:
    """Extract a user-friendly message from an LLM exception.

    LiteLLM exceptions often embed the full traceback in ``str(exc)``.
    This strips the traceback and redundant prefixes so the client sees
    only the meaningful first line.
    """
    msg = str(exc)
    # Strip embedded traceback (litellm concatenates it into the message)
    if "\nTraceback" in msg:
        msg = msg.split("\nTraceback", 1)[0].strip()
    # Strip litellm prefix duplication like "litellm.APIConnectionError: "
    markers = ("AuthenticationError:", "APIConnectionError:", "OpenAIException -")
    marker = next((m for m in markers if m in msg), None)
    if marker:
        msg = msg.rsplit(marker, maxsplit=1)[-1].strip()
    return msg or "An unexpected LLM error occurred."


class HistoryStore:
    """Per-client in-memory conversation message store."""

    def __init__(self) -> None:
        self._store: Dict[str, List[Dict[str, Any]]] = {}

    def get(self, client: str) -> List[Dict[str, Any]]:
        """Return stored conversation messages (copy)."""
        return list(self._store.get(client, []))

    def append(self, client: str, role: str, content: str, **kwargs: Any) -> None:
        """Append a message to the conversation store."""
        entry: Dict[str, Any] = {"role": role, "content": content}
        if kwargs:
            entry.update(kwargs)
        self._store.setdefault(client, []).append(entry)

    def clear(self, client: str) -> None:
        """Clear all messages for *client*."""
        self._store.pop(client, None)


class Route(str, Enum):
    """Top-level dispatch key for which session a client gets per turn."""

    LLM_ONLY = "llm_only"
    NL2SQL = "nl2sql"
    VECSEARCH = "vecsearch"
    COMBINED = "combined"


class ClassifierDecision(str, Enum):
    """``CombinedSession`` per-turn classification of where to route a query."""

    NL2SQL = "nl2sql"
    VECSEARCH = "vecsearch"
    BOTH = "both"


def resolve_route(tools_enabled: List[str]) -> Route:
    """Map tools_enabled to a route key."""
    has_nl2sql = TOOL_NL2SQL in tools_enabled
    has_vs = TOOL_VECSEARCH in tools_enabled
    if has_nl2sql and has_vs:
        return Route.COMBINED
    if has_nl2sql:
        return Route.NL2SQL
    if has_vs:
        return Route.VECSEARCH
    return Route.LLM_ONLY


# Turn labels for the "User: ... Assistant: ..." wire-format history string.
# Shared by the orchestrator producer and the `vs_rephrase.py` consumer.
# Stored without a trailing space so consumers can count occurrences in
# strings that omit the conventional space after the colon.
HISTORY_USER_LABEL = "User:"
HISTORY_ASSISTANT_LABEL = "Assistant:"


def format_history_text(entries: Iterable[Dict[str, Any]]) -> str:
    """Render conversation entries as ``"User: q\\nAssistant: a\\n..."``."""
    parts: list[str] = []
    for e in entries:
        role = e.get("role")
        content = e.get("content", "")
        if role == "user":
            parts.append(f"{HISTORY_USER_LABEL} {content}")
        elif role == "assistant":
            parts.append(f"{HISTORY_ASSISTANT_LABEL} {content}")
    return "\n".join(parts) + ("\n" if parts else "")


# Maps route → MCP prompt name. Populated lazily by each runtime to
# avoid import-time coupling. The text always comes from MCP (or the
# factory entry in mcp/prompts/defaults.py on fetch failure) — never
# from a code-side copy.
ROUTE_PROMPTS: Dict[Route, str] = {}


async def fetch_prompt_with_fallback(server_url: str, api_key: str, prompt_name: str) -> str:
    """Fetch a system prompt from MCP, falling back to the factory entry
    (mcp/prompts/defaults.py) on transport failure."""
    try:
        return await fetch_mcp_prompt(server_url, api_key, prompt_name)
    except Exception:
        LOGGER.warning("Failed to fetch prompt %r from MCP server, using factory default", prompt_name)
        return require_factory_text(prompt_name)


async def fetch_prompt_for_route(route: Route, server_url: str, api_key: str) -> str:
    """Fetch the current prompt text for a given route."""
    prompt_name = ROUTE_PROMPTS.get(route)
    if prompt_name is None:
        raise ValueError(f"No prompt registered for route {route!r}")
    return await fetch_prompt_with_fallback(server_url, api_key, prompt_name)


# ---------------------------------------------------------------------------
# Shared token-usage and grading helpers
# ---------------------------------------------------------------------------


def _sum_token_usage(*usages: Optional[TokenUsage]) -> Optional[TokenUsage]:
    """Sum multiple TokenUsage objects into one."""
    total = TokenUsage()
    found = False
    for u in usages:
        if u:
            found = True
            total.prompt_tokens += u.prompt_tokens
            total.completion_tokens += u.completion_tokens
            total.total_tokens += u.total_tokens
    return total if found else None


def parse_grade_relevant(raw: Any) -> str:
    """Extract the grading decision from a grade_relevant output value.

    The value may be a VectorGradeResponse JSON string (when grade is
    enabled) or a plain default string ``"yes"`` (when grade is disabled).
    Returns ``"yes"`` or ``"no"``.
    """
    if raw is None:
        return "yes"
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return str(parsed.get("relevant", "yes")).lower()
        except (json.JSONDecodeError, TypeError):
            pass
        stripped = raw.strip().lower()
        if stripped in ("yes", "no"):
            return stripped
    return "yes"


# ---------------------------------------------------------------------------
# SessionMetadata — typed metadata produced by session execution
# ---------------------------------------------------------------------------


def _unwrap_content_blocks(value: Any) -> Any:
    """Unwrap LangChain content blocks to extract the inner text payload.

    MCP tool results in the LangGraph runtime arrive as a list of content
    blocks: [{"type": "text", "text": "<actual_json>", "id": "lc_..."}].
    This extracts and parses the text from the first block.
    """
    if not isinstance(value, list) or not value:
        return value
    first = value[0]
    if isinstance(first, dict) and first.get("type") == "text" and "text" in first:
        text = first["text"]
        try:
            return json.loads(text) if isinstance(text, str) else text
        except (json.JSONDecodeError, TypeError):
            return text
    return value


def parse_vs_metadata(outputs: Dict[str, Any]) -> Optional[VsMetadata]:
    """Parse vs_metadata from flow output values.

    The vs_metadata value is the full VectorSearchResponse JSON from the
    retriever MCPTool (serialized as a single output). It already contains
    documents, searched_tables, context_input, etc. A bare list of documents
    is also handled for backward compatibility.

    In the LangGraph runtime, MCP results are wrapped in LangChain content
    blocks ([{"type": "text", "text": "<json>", ...}]). The unwrap step
    detects this pattern and extracts the inner payload.
    """
    vs_meta_raw = outputs.get("vs_metadata")
    if not vs_meta_raw:
        return None
    try:
        parsed = json.loads(vs_meta_raw) if isinstance(vs_meta_raw, str) else vs_meta_raw
        parsed = _unwrap_content_blocks(parsed)
        if isinstance(parsed, list):
            parsed = {"documents": parsed}
        return VsMetadata.model_validate(parsed)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


class SessionMetadata(BaseModel):
    """Typed metadata produced by a session execution."""

    vs_metadata: Optional[VsMetadata] = None
    sql_metadata: Optional[SqlMetadata] = None
    token_usage: Optional[TokenUsage] = None
    grade_relevant: str = "yes"


# ---------------------------------------------------------------------------
# Combined-session prompt names and validators
# ---------------------------------------------------------------------------

COMBINED_PROMPT_NAME = "optimizer_tools-default"
CLASSIFIER_PROMPT_NAME = "optimizer_combined-classify"
SYNTHESIS_PROMPT_NAME = "optimizer_combined-synthesize"

# Required substrings for an admin-supplied classifier prompt — the response
# parser is hardcoded to recognize each ClassifierDecision value, so the
# prompt MUST mention them all (otherwise the LLM has no menu).
_CLASSIFIER_REQUIRED_SUBSTRINGS = (
    "{{query}}",
    ClassifierDecision.NL2SQL.value,
    ClassifierDecision.VECSEARCH.value,
    ClassifierDecision.BOTH.value,
)

# Required str.format slots in an admin-supplied synthesis template.
_SYNTHESIS_REQUIRED_SLOTS = ("{system_prompt}", "{query}", "{sql_answer}", "{search_answer}")

def validate_classifier_prompt(text: str) -> bool:
    """Return False if any decision token or the ``{{query}}`` slot is missing."""
    return all(s in text for s in _CLASSIFIER_REQUIRED_SUBSTRINGS)


def validate_synthesis_template(text: str) -> bool:
    """Return False if a required ``str.format`` slot is missing OR if the
    template raises when formatted with only the four runtime fields —
    ``synthesize()`` runs ``.format()`` outside its try-block, so a stray
    placeholder like ``{extra}`` would crash the synthesis call uncaught."""
    if not all(slot in text for slot in _SYNTHESIS_REQUIRED_SLOTS):
        return False
    try:
        text.format(system_prompt="", query="", sql_answer="", search_answer="")
    except (KeyError, IndexError, ValueError):
        return False
    return True
