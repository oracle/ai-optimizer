"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LangGraph session wrappers for flow and agent graphs.
"""
# spell-checker: ignore vecsearch langgraph litellm

import logging
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage

from server.app.api.v1.schemas.chat import TokenUsage
from server.app.core.schemas import ClientSettings
from server.app.runtime.common import SessionMetadata, parse_grade_relevant, parse_vs_metadata

LOGGER = logging.getLogger(__name__)


def _aggregate_usage_callback(callback: UsageMetadataCallbackHandler) -> Optional[TokenUsage]:
    """Sum per-model ``usage_metadata`` collected by *callback* into one ``TokenUsage``.

    ``UsageMetadataCallbackHandler.usage_metadata`` is keyed by model name with
    LangChain-canonical fields (``input_tokens`` / ``output_tokens`` /
    ``total_tokens``). Translate back to the LiteLLM-shaped ``TokenUsage``
    schema the rest of the runtime consumes.
    """
    by_model = getattr(callback, "usage_metadata", None) or {}
    prompt = 0
    completion = 0
    total = 0
    for usage in by_model.values():
        prompt += int(usage.get("input_tokens", 0) or 0)
        completion += int(usage.get("output_tokens", 0) or 0)
        total += int(usage.get("total_tokens", 0) or 0)
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

    async def execute(self, query: str, thread_id: str, chat_history: bool = True) -> str:
        """Execute the flow graph and extract the answer."""
        inputs = self.build_inputs(query, thread_id, chat_history=chat_history)
        self.last_metadata = SessionMetadata()
        usage_cb = UsageMetadataCallbackHandler()

        try:
            # LangGraph flow from AgentSpec uses FlowInputSchema:
            # {"inputs": {start_node_id: {input_values}}, "messages": []}
            flow_inputs = {"inputs": inputs, "messages": []}
            result = await self.graph.ainvoke(flow_inputs, config={"callbacks": [usage_cb]})
        except Exception:
            LOGGER.exception("Flow execution failed for query: %s", query)
            raise

        # Extract outputs from the flow result
        answer = ""
        outputs = result.get("outputs", {})
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
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    answer = str(msg.content) if msg.content else ""
                    break

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

    async def chat(self, message: str, chat_history: bool = True) -> str:
        """Send a message and get a response."""
        self.last_metadata = SessionMetadata()
        usage_cb = UsageMetadataCallbackHandler()

        config: Dict[str, Any] = {
            "configurable": {"thread_id": self._thread_id if chat_history else str(uuid.uuid4())},
            "callbacks": [usage_cb],
            "recursion_limit": 25,
        }

        try:
            result = await self.graph.ainvoke(
                {"messages": [HumanMessage(content=message)]},
                config=config,
            )
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

        messages = result.get("messages", [])
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

    async def chat(self, message: str, chat_history: bool = True) -> str:
        """Chat with DB context prepended to the first message."""
        # Prepend DB context to the message so the LLM has it
        augmented = self._db_context + "\n" + message
        return await super().chat(augmented, chat_history=chat_history)
