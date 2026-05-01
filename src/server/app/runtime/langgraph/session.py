"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LangGraph session wrappers for flow and agent graphs.
"""
# spell-checker: ignore vecsearch langgraph litellm

import asyncio
import logging
import uuid
from functools import reduce
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages.ai import add_usage

from server.app.api.v1.schemas.chat import TokenUsage
from server.app.core.schemas import ClientSettings
from server.app.runtime.common import SessionMetadata, parse_grade_relevant, parse_vs_metadata
from server.app.runtime.langgraph.adapters.litellm import extract_response_text

LOGGER = logging.getLogger(__name__)


def _chunk_text(chunk: Any) -> str:
    """Extract plain text from an ``AIMessageChunk.content`` for SSE forwarding."""
    if chunk is None:
        return ""
    return extract_response_text(getattr(chunk, "content", None))


async def _run_graph_with_streaming(
    graph: Any,
    inputs: Any,
    config: Dict[str, Any],
    queue: asyncio.Queue,
) -> tuple[Optional[Dict[str, Any]], bool]:
    """Drive *graph* via ``astream_events`` and forward chat-model chunks to *queue*.

    Captures the top-level chain's final output from its ``on_chain_end``
    event (matched by run_id, so any compiled graph works regardless of name)
    and normalizes chunk content via ``_chunk_text`` so v1 typed-block content
    does not leak through.

    Returns ``(final_output, streamed)``; *streamed* indicates whether any
    non-empty chat-model chunk was forwarded.

    Node errors propagate unchanged — re-running the graph would duplicate
    upstream side effects (retrievers, tool calls). Streaming-setup failures
    for a single LLM call are recovered inside the bridge.
    """
    top_run_id: Optional[str] = None
    final_output: Optional[Dict[str, Any]] = None
    streamed = False
    # ``include_types`` skips dispatch for tool/retriever/prompt event subtrees that
    # this loop doesn't read — measurable on flow graphs with many non-LLM nodes.
    async for event in graph.astream_events(
        inputs, config=config, version="v2", include_types=["chat_model", "chain"],
    ):
        kind = event.get("event")
        if kind == "on_chain_start" and top_run_id is None:
            top_run_id = event.get("run_id")
        elif kind == "on_chain_end" and event.get("run_id") == top_run_id:
            final_output = event.get("data", {}).get("output")
        elif kind == "on_chat_model_stream":
            text = _chunk_text(event.get("data", {}).get("chunk"))
            if text:
                await queue.put({"type": "stream", "content": text})
                streamed = True
    return final_output, streamed


def _aggregate_usage_callback(callback: UsageMetadataCallbackHandler) -> Optional[TokenUsage]:
    """Sum per-model ``usage_metadata`` collected by *callback* into one ``TokenUsage``.

    ``UsageMetadataCallbackHandler`` keys usage by model name and only sums
    within each model. ``add_usage`` from ``langchain_core.messages.ai`` does
    the cross-model fold and preserves any ``input_token_details`` /
    ``output_token_details`` shape, even though the rest of the runtime only
    consumes the three top-level totals today.
    """
    by_model = getattr(callback, "usage_metadata", None) or {}
    if not by_model:
        return None
    totals = reduce(add_usage, by_model.values())
    prompt = int(totals.get("input_tokens", 0) or 0)
    completion = int(totals.get("output_tokens", 0) or 0)
    total = int(totals.get("total_tokens", 0) or 0)
    if not (prompt or completion or total):
        return None
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total or (prompt + completion),
    )


class GraphFlowSession:
    """Wraps a compiled LangGraph flow (from AgentSpec Flow conversion)."""

    def __init__(self, graph: Any, client_settings: ClientSettings) -> None:
        """Initialise with a compiled graph and client settings."""
        self.graph = graph
        ll_model = client_settings.ll_model
        self._model = f"{ll_model.provider}/{ll_model.id}"
        self._history: str = ""
        self.last_metadata = SessionMetadata()

    @property
    def history(self) -> str:
        """Return accumulated chat history string."""
        return self._history

    @history.setter
    def history(self, value: str) -> None:
        """Set the chat history string."""
        self._history = value

    def build_inputs(self, query: str, thread_id: str, chat_history: bool = True) -> Dict[str, Any]:
        """Build the flow input dict."""
        return {
            "query": query,
            "thread_id": thread_id,
            "model": self._model,
            "chat_history": self._history if chat_history else "",
        }

    async def execute(
        self,
        query: str,
        thread_id: str,
        chat_history: bool = True,
        queue: Optional[asyncio.Queue] = None,
    ) -> str:
        """Execute the flow graph and extract the answer.

        When *queue* is provided, the graph is driven via ``astream_events`` and
        chat-model chunks are forwarded to the queue. If no chunks are observed
        but a final answer is produced, the full answer is delivered as a single
        ``stream`` event so callers always see the response.
        """
        inputs = self.build_inputs(query, thread_id, chat_history=chat_history)
        self.last_metadata = SessionMetadata()
        usage_cb = UsageMetadataCallbackHandler()
        # LangGraph flow from AgentSpec uses FlowInputSchema:
        # {"inputs": {start_node_id: {input_values}}, "messages": []}
        flow_inputs = {"inputs": inputs, "messages": []}
        config: Dict[str, Any] = {"callbacks": [usage_cb]}
        streamed = False

        try:
            if queue is None:
                result = await self.graph.ainvoke(flow_inputs, config=config)
            else:
                result, streamed = await _run_graph_with_streaming(self.graph, flow_inputs, config, queue)
        except Exception:
            LOGGER.exception("Flow execution failed for query: %s", query)
            raise

        # Extract outputs from the flow result
        answer = ""
        outputs = (result or {}).get("outputs", {})
        if outputs:
            answer_value = outputs.get("answer")
            answer = str(answer_value) if answer_value is not None else ""

            grade_relevant = parse_grade_relevant(outputs.get("grade_relevant"))
            self.last_metadata.grade_relevant = grade_relevant

            vs_meta = parse_vs_metadata(outputs)
            if vs_meta and grade_relevant == "no":
                vs_meta.documents = []
            self.last_metadata.vs_metadata = vs_meta

        token_usage = _aggregate_usage_callback(usage_cb)
        if token_usage:
            self.last_metadata.token_usage = token_usage

        if not answer:
            # Fall back to last AI message
            messages = (result or {}).get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    answer = str(msg.content) if msg.content else ""
                    break

        if queue is not None and not streamed and answer:
            await queue.put({"type": "stream", "content": answer})

        self._history += f"User: {query}\nAssistant: {answer}\n"
        return answer

class AgentGraphSession:
    """Wraps a compiled LangGraph agent (ReAct agent from AgentSpec)."""

    def __init__(self, graph: Any, conversation_id: Optional[str] = None, checkpointer: Any = None) -> None:
        """Initialise with a compiled agent graph and optional conversation ID."""
        self.graph = graph
        self._thread_id = conversation_id or str(uuid.uuid4())
        self._conversation_messages: List[Any] = []
        self.last_metadata = SessionMetadata()
        self._checkpointer = checkpointer

    @property
    def conversation_messages(self) -> List[Any]:
        """Return accumulated conversation messages."""
        return self._conversation_messages

    @conversation_messages.setter
    def conversation_messages(self, value: List[Any]) -> None:
        """Replace the conversation message list."""
        self._conversation_messages = value

    @property
    def conversation_id(self) -> str:
        """Return the thread/conversation ID."""
        return self._thread_id

    @conversation_id.setter
    def conversation_id(self, value: str) -> None:
        """Set the thread/conversation ID."""
        self._thread_id = value

    @property
    def checkpointer(self) -> Any:
        """Return the checkpointer instance."""
        return self._checkpointer

    async def chat(
        self,
        message: str,
        chat_history: bool = True,
        queue: Optional[asyncio.Queue] = None,
    ) -> str:
        """Send a message and get a response.

        When *queue* is provided, the graph is driven via ``astream_events`` and
        chat-model chunks are forwarded to the queue. If no chunks are observed
        but a final answer is produced, the full answer is delivered as a single
        ``stream`` event.
        """
        self.last_metadata = SessionMetadata()
        usage_cb = UsageMetadataCallbackHandler()

        config: Dict[str, Any] = {
            "configurable": {"thread_id": self._thread_id if chat_history else str(uuid.uuid4())},
            "callbacks": [usage_cb],
            "recursion_limit": 25,
        }
        graph_inputs = {"messages": [HumanMessage(content=message)]}
        streamed = False

        try:
            if queue is None:
                result = await self.graph.ainvoke(graph_inputs, config=config)
            else:
                result, streamed = await _run_graph_with_streaming(self.graph, graph_inputs, config, queue)
        except Exception:
            LOGGER.exception("Agent chat failed for message: %s", message)
            # Clear corrupt checkpoint so retries don't inherit partial tool-call state
            if self._checkpointer is not None:
                thread = config["configurable"]["thread_id"]
                try:
                    self._checkpointer.delete_thread(thread)
                except Exception:
                    LOGGER.debug("Could not clear checkpoint for thread %s", thread)
            raise

        messages = (result or {}).get("messages", [])
        answer = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and not msg.tool_calls:
                answer = str(msg.content) if msg.content else ""
                break

        if chat_history:
            self._conversation_messages.append(HumanMessage(content=message))
            if answer:
                self._conversation_messages.append(AIMessage(content=answer))

        token_usage = _aggregate_usage_callback(usage_cb)
        if token_usage:
            self.last_metadata.token_usage = token_usage

        if queue is not None and not streamed and answer:
            await queue.put({"type": "stream", "content": answer})

        return answer


class NL2SQLGraphSession(AgentGraphSession):
    """NL2SQL agent session with database connection context."""

    def __init__(
        self,
        graph: Any,
        client_settings: ClientSettings,
        thread_id: str = "",
        conversation_id: Optional[str] = None,
        checkpointer: Any = None,
    ) -> None:
        """Initialise with a graph, client settings, and optional thread ID."""
        super().__init__(graph, conversation_id=conversation_id, checkpointer=checkpointer)

        connection_name = client_settings.database.alias
        ll_model = client_settings.ll_model
        model = f"{ll_model.provider}/{ll_model.id}"

        context = "\n\nUse these values when a sqlcl_* tool parameter asks for them:\n"
        context += f"- model: {model}\n"
        if thread_id:
            context += f"- thread_id: {thread_id}\n"
        if connection_name:
            context += f"- connection_name: {connection_name}\n"

        self._db_context = context
        self.conversation_id = thread_id or self._thread_id

    async def chat(
        self,
        message: str,
        chat_history: bool = True,
        queue: Optional[asyncio.Queue] = None,
    ) -> str:
        """Chat with DB context prepended to the first message."""
        # Prepend DB context to the message so the LLM has it
        augmented = self._db_context + "\n" + message
        return await super().chat(augmented, chat_history=chat_history, queue=queue)
