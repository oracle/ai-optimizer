"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared runtime utilities used by the LangGraph runtime.
"""
# spell-checker: ignore vecsearch litellm acompletion agentspec

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Union

import litellm
from litellm.types.utils import Choices, ModelResponse
from pydantic import BaseModel

from server.app.agentspec.adapters.mcp import fetch_mcp_prompt
from server.app.api.v1.schemas.chat import TokenUsage, VsMetadata
from server.app.core.schemas import TOOL_NL2SQL, TOOL_VECSEARCH

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


def resolve_route(tools_enabled: List[str]) -> str:
    """Map tools_enabled to a route key."""
    has_nl2sql = TOOL_NL2SQL in tools_enabled
    has_vs = TOOL_VECSEARCH in tools_enabled
    if has_nl2sql and has_vs:
        return "combined"
    if has_nl2sql:
        return "nl2sql"
    if has_vs:
        return "vecsearch"
    return "llm_only"


# Maps route → (prompt_name, default_text) for prompt refresh.
# Populated lazily by each runtime to avoid import-time coupling.
ROUTE_PROMPTS: Dict[str, tuple[str, str]] = {}


async def fetch_prompt_with_fallback(
    server_url: str,
    api_key: str,
    prompt_name: str,
    default_prompt: str,
) -> str:
    """Fetch a system prompt from MCP, falling back to a default on failure."""
    try:
        return await fetch_mcp_prompt(server_url, api_key, prompt_name)
    except Exception:
        LOGGER.warning(
            "Failed to fetch prompt '%s' from MCP server, using default",
            prompt_name,
        )
        return default_prompt


async def fetch_prompt_for_route(route: str, server_url: str, api_key: str) -> Optional[str]:
    """Fetch the current prompt text for a given route, or None if unknown."""
    entry = ROUTE_PROMPTS.get(route)
    if entry is None:
        return None
    prompt_name, default_text = entry
    return await fetch_prompt_with_fallback(server_url, api_key, prompt_name, default_text)


# ---------------------------------------------------------------------------
# Shared token-usage and grading helpers
# ---------------------------------------------------------------------------


def extract_response_usage(response: Any) -> Optional[TokenUsage]:
    """Extract token usage from a litellm response, or None."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    total = getattr(usage, "total_tokens", 0) or 0
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total or (prompt + completion),
    )


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
    token_usage: Optional[TokenUsage] = None
    grade_relevant: str = "yes"


# ---------------------------------------------------------------------------
# BaseCombinedSession — shared multi-tool orchestration
# ---------------------------------------------------------------------------

COMBINED_PROMPT_NAME = "optimizer_tools-default"

CLASSIFIER_PROMPT = (
    "You are a query classifier. Analyze what type of information is needed "
    "to answer the user's question.\n\n"
    "Respond with exactly one word:\n"
    "- 'nl2sql' if the answer requires retrieving or computing over actual data "
    "(specific values, aggregations, counts, listings, or current settings)\n"
    "- 'vecsearch' if the answer requires knowledge "
    "(concepts, definitions, explanations, best practices, or procedures)\n"
    "- 'both' if the answer requires comparing actual data against "
    "documented guidelines or recommendations\n\n"
    "Do not include any other text.\n\n"
    "User question: {{query}}"
)

DEFAULT_COMBINED_INSTRUCTION = (
    "You have reference documents and database access. "
    "Use database tools for live/current values, aggregations, counts, or listings. "
    "Use documents for concepts, definitions, or best-practice guidelines. "
    "When comparing current state to recommendations, use both sources and compare. "
    "Answer using only information from these sources."
)

SYNTHESIS_TEMPLATE = (
    "{system_prompt}\n\n"
    "The user asked: {query}\n\n"
    "Database query result:\n{sql_answer}\n\n"
    "Document search result:\n{search_answer}\n\n"
    "Synthesize both results into a single, coherent answer."
)


class BaseCombinedSession:
    """Shared logic for the hybrid VecSearch + NL2SQL combined session.

    Subclasses must keep ``execute()`` and ``execute_streaming()`` which
    wire up the runtime-specific token extraction calls.
    """

    def __init__(
        self,
        vs_session: Any,
        nl2sql_session: Any,
        classifier_model: str,
        system_prompt: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ) -> None:
        self.vs_session = vs_session
        self.nl2sql_session = nl2sql_session
        self._classifier_model = classifier_model
        self._system_prompt = system_prompt
        self._api_key = api_key
        self._api_base = api_base
        self.last_metadata = SessionMetadata()

    def _auth_kwargs(self) -> Dict[str, Any]:
        """Return api_key/api_base kwargs for litellm calls, if configured."""
        kwargs: Dict[str, Any] = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        return kwargs

    @staticmethod
    def _extract_response_usage(response: Any) -> Optional[TokenUsage]:
        """Extract token usage from a litellm response, or None."""
        return extract_response_usage(response)

    async def classify(self, query: str) -> tuple[str, Optional[TokenUsage]]:
        """Classify a query as 'nl2sql', 'vecsearch', or 'both'."""
        prompt = CLASSIFIER_PROMPT.replace("{{query}}", query)
        try:
            response = await litellm.acompletion(
                model=self._classifier_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0,
                drop_params=True,
                **self._auth_kwargs(),
            )
            if not isinstance(response, ModelResponse):
                raise TypeError(f"Expected ModelResponse, got {type(response)}")
            classifier_tu = self._extract_response_usage(response)
            choice = response.choices[0]
            if not isinstance(choice, Choices):
                raise TypeError(f"Expected Choices, got {type(choice)}")
            raw = choice.message.content or ""
            decision = raw.strip().lower().strip("'\".,!")
            if decision in ("nl2sql", "vecsearch", "both"):
                return decision, classifier_tu
            LOGGER.warning("Classifier returned unexpected value %r, defaulting to 'both'", raw)
            return "both", classifier_tu
        except Exception:
            LOGGER.exception("Classification failed, defaulting to 'both'")
            return "both", None

    async def synthesize(self, query: str, vs_answer: str, nl2sql_answer: str) -> tuple[str, Optional[TokenUsage]]:
        """Synthesize answers from both sources into a single response."""
        prompt = SYNTHESIS_TEMPLATE.format(
            system_prompt=self._system_prompt,
            query=query,
            sql_answer=nl2sql_answer,
            search_answer=vs_answer,
        )
        try:
            response = await litellm.acompletion(
                model=self._classifier_model,
                messages=[{"role": "user", "content": prompt}],
                drop_params=True,
                **self._auth_kwargs(),
            )
            if not isinstance(response, ModelResponse):
                raise TypeError(f"Expected ModelResponse, got {type(response)}")
            choice = response.choices[0]
            if not isinstance(choice, Choices):
                raise TypeError(f"Expected Choices, got {type(choice)}")
            return choice.message.content or "", self._extract_response_usage(response)
        except Exception:
            LOGGER.exception("Synthesis failed, returning concatenated answers")
            return f"Database result:\n{nl2sql_answer}\n\nDocument result:\n{vs_answer}", None

    async def _handle_both_results(
        self, query: str, vs_answer: str, nl2sql_answer: str
    ) -> tuple[str, Optional[TokenUsage]]:
        """Post-process the 'both' route: check grade_relevant, optionally synthesize."""
        vs_relevant = self.vs_session.last_metadata.grade_relevant
        synth_tu = None
        self.last_metadata = self.vs_session.last_metadata.model_copy()
        if vs_relevant == "no":
            answer = nl2sql_answer
        else:
            answer, synth_tu = await self.synthesize(query, vs_answer, nl2sql_answer)
        return answer, synth_tu


# ---------------------------------------------------------------------------
# BaseChatOrchestrator
# ---------------------------------------------------------------------------


class BaseChatOrchestrator:
    """Shared chat orchestration logic for the LangGraph runtime.

    Subclasses must set the following type properties (used for isinstance
    dispatch) and implement the hook methods listed below.

    Type properties::

        _agent_session_type    – e.g. AgentGraphSession or AgentChatSession
        _combined_session_type – CombinedSession from the respective runtime
        _flow_session_type     – GraphFlowSession or FlowSession
        _nl2sql_session_type   – NL2SQLGraphSession or NL2SQLAgentSession

    Hook methods::

        _get_agent_token_usage(session) -> dict | None
        _get_or_create_session(client) -> tuple[session, route_str]
        _run_flow_streaming(session, route, question, client, queue, chat_history)
        _run_agent_streaming(session, use_history, question, queue)
    """

    # -- type properties (override in subclasses) ---------------------------

    _agent_session_type: type
    _combined_session_type: type
    _flow_session_type: type
    _nl2sql_session_type: type

    def __init__(
        self,
        server_url: str,
        api_key: Union[str, Callable[[], str]],
        resolve_client: Callable[[str], Any],
    ) -> None:
        self._server_url = server_url
        self._api_key = api_key
        self._resolve_client = resolve_client
        self._session_cache: Dict[tuple, tuple[Any, Dict[str, Any]]] = {}
        self._build_lock = asyncio.Lock()
        self._stream_locks: Dict[tuple, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.history = HistoryStore()

    @property
    def api_key(self) -> str:
        """Return the current API key, invoking the callable if needed."""
        return self._api_key() if callable(self._api_key) else self._api_key

    @staticmethod
    def _validate_llm(cs: Any) -> None:
        """Raise LLMConfigurationError if provider or model ID is missing."""
        if cs.ll_model.provider is None or cs.ll_model.id is None:
            raise LLMConfigurationError("No language model configured. Set a provider and model ID in client settings.")

    @staticmethod
    def _build_identity(cs_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Build a cache-identity dict from settings, excluding chat_history."""
        out = cs_dict.copy()
        ll = out.get("ll_model")
        if isinstance(ll, dict):
            out["ll_model"] = {k: v for k, v in ll.items() if k != "chat_history"}
        return out

    def invalidate_session(self, client: str) -> None:
        """Remove all cached sessions for the given client."""
        keys = [k for k in self._session_cache if k[0] == client]
        for k in keys:
            del self._session_cache[k]
            self._stream_locks.pop(k, None)

    def clear_history(self, client: str) -> None:
        """Clear conversation history and invalidate sessions for a client."""
        self.history.clear(client)
        self.invalidate_session(client)

    # -- hooks (override in subclasses) -------------------------------------

    async def _get_or_create_session(self, client: str) -> tuple[Any, str]:
        raise NotImplementedError

    async def _run_flow_streaming(
        self,
        session: Any,
        route: str,
        question: str,
        client: str,
        queue: asyncio.Queue,
        chat_history: bool = True,
    ) -> None:
        raise NotImplementedError

    async def _run_agent_streaming(
        self,
        session: Any,
        use_history: bool,
        question: str,
        queue: asyncio.Queue,
    ) -> None:
        raise NotImplementedError

    def _get_agent_token_usage(self, session: Any) -> Optional[TokenUsage]:
        raise NotImplementedError

    # -- shared streaming logic ---------------------------------------------

    async def _run_combined_streaming(
        self,
        session: Any,
        use_history: bool,
        question: str,
        client: str,
        queue: asyncio.Queue,
    ) -> None:
        """Run a combined session with streaming, delegating to sub-sessions."""
        await session.execute_streaming(
            query=question,
            thread_id=client,
            chat_history=use_history,
            queue=queue,
            stream_flow=self._run_flow_streaming,
            stream_agent=self._run_agent_streaming,
        )

    def _create_streaming_task(
        self,
        session: Any,
        route: str,
        use_history: bool,
        question: str,
        client: str,
        queue: asyncio.Queue,
    ) -> asyncio.Task:
        """Create an asyncio task for the appropriate streaming handler."""
        if isinstance(session, self._combined_session_type):
            return asyncio.create_task(self._run_combined_streaming(session, use_history, question, client, queue))
        if isinstance(session, self._agent_session_type):
            return asyncio.create_task(self._run_agent_streaming(session, use_history, question, queue))
        return asyncio.create_task(
            self._run_flow_streaming(session, route, question, client, queue, chat_history=use_history)
        )

    @staticmethod
    def _accumulate_token_usage(current: Optional[TokenUsage], event: Dict[str, Any]) -> TokenUsage:
        """Add token counts from an event into the running total."""
        if current is None:
            current = TokenUsage()
        current.prompt_tokens += event.get("prompt_tokens", 0)
        current.completion_tokens += event.get("completion_tokens", 0)
        current.total_tokens += event.get("total_tokens", 0)
        return current

    def _finalize_stream(
        self,
        session: Any,
        question: str,
        client: str,
        collected: list[str],
        token_usage: Optional[TokenUsage],
        route: str,
    ) -> Dict[str, Any]:
        """Persist history and return the final _meta event dict."""
        answer = "".join(collected)
        vs_metadata: Optional[VsMetadata] = None
        if isinstance(session, (self._combined_session_type, self._flow_session_type)):
            vs_metadata = session.last_metadata.vs_metadata
        if isinstance(session, self._agent_session_type) and not isinstance(session, self._nl2sql_session_type):
            token_usage = self._get_agent_token_usage(session) or token_usage
        if answer:
            # Convert to dicts for HistoryStore (consumed by chat/history endpoint)
            vs_meta_dict = vs_metadata.model_dump(exclude_none=True) if vs_metadata else None
            tu_dict = token_usage.model_dump() if token_usage else None
            extras = {k: v for k, v in [("vs_metadata", vs_meta_dict), ("token_usage", tu_dict)] if v}
            self.history.append(client, "user", question)
            self.history.append(client, "assistant", answer, **extras)
        # Return dict for streaming event — endpoint consumes via event.get()
        vs_meta_dict = vs_metadata.model_dump(exclude_none=True) if vs_metadata else None
        return {"type": "_meta", "route": route, "vs_metadata": vs_meta_dict}

    async def execute_chat_stream(
        self,
        question: str,
        client: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute a streaming chat, yielding event dicts as they arrive."""
        session, route = await self._get_or_create_session(client)
        queue: asyncio.Queue = asyncio.Queue()
        collected: list[str] = []
        token_usage: Optional[TokenUsage] = None

        async with self._stream_locks[(client, route)]:
            cs = self._resolve_client(client)
            use_history = cs.ll_model.chat_history
            task = self._create_streaming_task(session, route, use_history, question, client, queue)

            try:
                while True:
                    if task.done() and queue.empty():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    if event.get("type") == "stream":
                        collected.append(event.get("content", ""))
                    elif event.get("type") == "_token_usage":
                        token_usage = self._accumulate_token_usage(token_usage, event)
                    yield event

                exc = task.exception()
                if exc is not None:
                    LOGGER.error("Streaming execution failed: %s", exc)
                    yield {"type": "error", "content": clean_llm_error(exc)}
                    return

            except Exception as exc:
                LOGGER.error("Stream consumer error: %s", exc)
                yield {"type": "error", "content": clean_llm_error(exc)}
                if not task.done():
                    task.cancel()
                return

        yield self._finalize_stream(session, question, client, collected, token_usage, route)
