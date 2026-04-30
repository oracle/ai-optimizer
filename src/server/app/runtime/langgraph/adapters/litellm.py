"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

ChatLiteLLMBridge — a LangChain BaseChatModel wrapping litellm.acompletion().

Used by the LangGraph runtime to route LLM calls through LiteLLM,
which handles provider-specific formatting (OCI, OpenAI, Ollama, etc.).
"""
# spell-checker: ignore litellm acompletion accum agenerate ollama astream

import json
import logging
import uuid
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Sequence, Union, cast

import litellm
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from litellm import CustomStreamWrapper
from pydantic import Field

from server.app.runtime.common import TokenUsage, extract_response_usage
from server.app.runtime.ollama_tools import (
    contextualize_tool_result,
    is_ollama_model,
    sanitize_tool_name,
    sanitize_tools,
    unsanitize_tool_name,
)

LOGGER = logging.getLogger(__name__)


def _to_usage_metadata(usage: Optional[Union[Dict[str, Any], TokenUsage]]) -> Optional[UsageMetadata]:
    """Convert internal token-usage shapes to LangChain ``AIMessage.usage_metadata``.

    LangChain consumers (callbacks, observability tools) read ``usage_metadata``
    in the canonical ``input_tokens`` / ``output_tokens`` / ``total_tokens`` shape.
    LiteLLM emits ``prompt_tokens`` / ``completion_tokens`` — translate here.
    """
    if usage is None:
        return None
    if isinstance(usage, TokenUsage):
        prompt = usage.prompt_tokens
        completion = usage.completion_tokens
        total = usage.total_tokens
    else:
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0)
    if not (prompt or completion or total):
        return None
    return UsageMetadata(
        input_tokens=prompt,
        output_tokens=completion,
        total_tokens=total or (prompt + completion),
    )


def _flatten_tool_content(content):
    """Flatten LangGraph content blocks to a single string for LiteLLM."""
    if not isinstance(content, list):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict) and "text" in block:
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)
        else:
            parts.append(json.dumps(block, default=str))
    return "\n".join(parts)


def _messages_to_openai(messages: List[BaseMessage], contextualize_tools: bool = False) -> List[Dict[str, Any]]:
    """Convert LangChain messages to OpenAI dict format.

    When *contextualize_tools* is True, tool result content is prefixed
    with the tool name so smaller models (e.g. llama3.1) can understand
    what the result represents instead of hallucinating.
    """
    result = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append({"role": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            entry: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["args"] if isinstance(tc["args"], str) else json.dumps(tc["args"]),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            result.append(entry)
        elif isinstance(msg, ToolMessage):
            content = _flatten_tool_content(msg.content)
            if contextualize_tools and msg.name is not None:
                content = contextualize_tool_result(msg.name, content)
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": content,
                }
            )
        else:
            result.append({"role": "user", "content": str(msg.content)})
    return result


def _parse_tool_calls(raw_tool_calls: Any, name_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Parse litellm tool calls into LangChain format."""
    if not raw_tool_calls:
        return []
    tool_calls = []
    for tc in raw_tool_calls:
        func = tc.function if hasattr(tc, "function") else tc.get("function", {})
        name = func.name if hasattr(func, "name") else func.get("name", "")
        name = unsanitize_tool_name(name, name_map)
        args_str = func.arguments if hasattr(func, "arguments") else func.get("arguments", "{}")
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except (json.JSONDecodeError, TypeError):
            args = {}
        tc_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
        tool_calls.append({"type": "tool_call", "name": name, "args": args, "id": tc_id})
    return tool_calls


def _process_tool_call_delta(tool_call_accum: Dict[int, Dict[str, str]], tc_delta: Any) -> None:
    """Accumulate a single tool-call delta into the accumulator dict."""
    idx = tc_delta.index if hasattr(tc_delta, "index") else 0
    if idx not in tool_call_accum:
        tool_call_accum[idx] = {"id": "", "name": "", "arguments": ""}
    entry = tool_call_accum[idx]
    if hasattr(tc_delta, "id") and tc_delta.id:
        entry["id"] = tc_delta.id
    func = getattr(tc_delta, "function", None)
    if func:
        if hasattr(func, "name") and func.name:
            entry["name"] = func.name
        if hasattr(func, "arguments") and func.arguments:
            entry["arguments"] += func.arguments


def _build_tool_calls_from_accum(
    tool_call_accum: Dict[int, Dict[str, str]],
    name_map: Optional[Dict[str, str]] = None,
) -> list:
    """Convert accumulated tool-call deltas into LangChain tool-call dicts."""
    tool_calls: list = []
    for idx in sorted(tool_call_accum.keys()):
        entry = tool_call_accum[idx]
        name = unsanitize_tool_name(entry["name"], name_map)
        args_str = entry["arguments"]
        try:
            args = json.loads(args_str) if args_str else {}
        except (json.JSONDecodeError, TypeError):
            args = {}
        tc_id = entry["id"] or f"call_{uuid.uuid4().hex[:12]}"
        tool_calls.append({"type": "tool_call", "name": name, "args": args, "id": tc_id})
    return tool_calls


def _accumulate_chunk_usage(usage_accum: Dict[str, int], chunk: Any) -> None:
    """Add token usage from a stream chunk into the running accumulator."""
    chunk_usage = getattr(chunk, "usage", None)
    if chunk_usage:
        for key in usage_accum:
            usage_accum[key] += getattr(chunk_usage, key, 0) or 0


def _process_stream_chunk(
    chunk: Any,
    usage_accum: Dict[str, int],
    tool_call_accum: Dict[int, Dict[str, str]],
) -> Optional[str]:
    """Accumulate usage and tool-call deltas from *chunk*; return its content or ``None`` to skip.

    A return of ``None`` signals "no chunk to yield" — either the terminal
    usage-only chunk (``choices=[]``, emitted when ``stream_options.include_usage``
    is set) or any future delta with no choice payload.
    """
    _accumulate_chunk_usage(usage_accum, chunk)
    if not chunk.choices:
        return None
    delta = chunk.choices[0].delta
    for tc_delta in getattr(delta, "tool_calls", None) or ():
        _process_tool_call_delta(tool_call_accum, tc_delta)
    return getattr(delta, "content", "") or ""


class ChatLiteLLMBridge(BaseChatModel):
    """LangChain BaseChatModel that delegates to litellm.acompletion().

    Supports tool calling via LangChain's default bind_tools mechanism
    (litellm speaks OpenAI tool format natively).
    """

    model: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: Optional[int] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "litellm-bridge"

    def _is_ollama(self) -> bool:
        """Check if this model targets an Ollama provider."""
        return is_ollama_model(self.model)

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], type, Callable, BaseTool]],
        *,
        tool_choice: Optional[Union[dict, str, bool]] = None,
        **kwargs: Any,
    ) -> Runnable:
        """Bind tools to the model for tool calling."""
        formatted_tools = [convert_to_openai_tool(tool) for tool in tools]
        name_map: Dict[str, str] = {}
        if self._is_ollama():
            formatted_tools, name_map = sanitize_tools(formatted_tools)
        if isinstance(tool_choice, bool):
            tool_choice = "required" if tool_choice else "none"
        elif self._is_ollama() and isinstance(tool_choice, dict):
            func = tool_choice.get("function", {})
            if "name" in func:
                tool_choice = {**tool_choice, "function": {**func, "name": sanitize_tool_name(func["name"])}}
        return super().bind(tools=formatted_tools, tool_choice=tool_choice, _ollama_name_map=name_map, **kwargs)

    def _build_kwargs(self, messages: List[BaseMessage], stop: Optional[List[str]], **kwargs: Any) -> Dict[str, Any]:
        """Build kwargs for litellm calls.

        Returns the kwargs dict. Callers should pop ``_ollama_name_map``
        before passing to litellm.
        """
        ollama = self._is_ollama()
        call_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": _messages_to_openai(messages, contextualize_tools=ollama),
            "drop_params": True,
        }
        if self.api_key:
            call_kwargs["api_key"] = self.api_key
        if self.api_base:
            call_kwargs["base_url"] = self.api_base
        if self.max_tokens is not None:
            call_kwargs["max_tokens"] = self.max_tokens
        if self.frequency_penalty is not None:
            call_kwargs["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            call_kwargs["presence_penalty"] = self.presence_penalty
        if stop:
            call_kwargs["stop"] = stop

        if "tools" in kwargs:
            call_kwargs["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            call_kwargs["tool_choice"] = kwargs["tool_choice"]

        call_kwargs["_ollama_name_map"] = kwargs.get("_ollama_name_map", {})

        # Provider-specific params (e.g. OCI auth)
        call_kwargs.update(self.extra_params)

        return call_kwargs

    @staticmethod
    def _extract_usage(response: Any) -> Optional[TokenUsage]:
        """Extract token usage from a litellm response."""
        return extract_response_usage(response)

    def _response_to_chat_result(self, response: Any, name_map: Optional[Dict[str, str]] = None) -> ChatResult:
        """Convert a litellm ModelResponse to a LangChain ChatResult."""
        choice = response.choices[0]
        message = choice.message
        content = message.content or ""
        tool_calls = _parse_tool_calls(getattr(message, "tool_calls", None), name_map=name_map)
        usage = self._extract_usage(response)
        ai_msg = AIMessage(
            content=content,
            tool_calls=tool_calls,
            usage_metadata=_to_usage_metadata(usage),
            # UsageMetadataCallbackHandler keys per-model usage on this name; without it, usage is dropped.
            response_metadata={"model_name": self.model},
        )
        generation = ChatGeneration(message=ai_msg)
        return ChatResult(
            generations=[generation],
            llm_output={"token_usage": usage} if usage else {},
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,  # noqa: ARG002 — required by BaseChatModel
        **kwargs: Any,
    ) -> ChatResult:
        """Sync generation via litellm.completion()."""
        call_kwargs = self._build_kwargs(messages, stop, **kwargs)
        name_map = call_kwargs.pop("_ollama_name_map", None)
        response = litellm.completion(**call_kwargs)
        return self._response_to_chat_result(response, name_map=name_map)

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,  # noqa: ARG002 — required by BaseChatModel
        **kwargs: Any,
    ) -> ChatResult:
        """Async generation via litellm.acompletion()."""
        call_kwargs = self._build_kwargs(messages, stop, **kwargs)
        name_map = call_kwargs.pop("_ollama_name_map", None)
        response = await litellm.acompletion(**call_kwargs)
        return self._response_to_chat_result(response, name_map=name_map)

    def _result_as_chunk(self, result: ChatResult) -> ChatGenerationChunk:
        """Repackage a non-streaming ``ChatResult`` as a single ``ChatGenerationChunk``.

        Used by the streaming methods to deliver the answer when the provider
        rejected ``stream=True`` and the bridge fell back to a single
        non-streaming call. Carries content, tool_calls, usage_metadata, and
        response_metadata through unchanged so callbacks see the same shape
        they would for a normal stream's terminal chunk.
        """
        msg = result.generations[0].message
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        tool_calls = list(getattr(msg, "tool_calls", []) or [])
        usage_metadata = getattr(msg, "usage_metadata", None) if isinstance(msg, AIMessage) else None
        response_metadata = getattr(msg, "response_metadata", {}) or {}
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content=content,
                tool_calls=tool_calls,
                usage_metadata=usage_metadata,
                response_metadata=response_metadata,
            ),
        )

    def _terminal_chunk(
        self,
        usage_accum: Dict[str, int],
        tool_call_accum: Dict[int, Dict[str, str]],
        name_map: Optional[Dict[str, str]],
    ) -> Optional[ChatGenerationChunk]:
        """Build the post-loop chunk carrying aggregated tool calls and usage, or ``None`` if neither."""
        tool_calls = _build_tool_calls_from_accum(tool_call_accum, name_map)
        usage_metadata = _to_usage_metadata(usage_accum) if any(v > 0 for v in usage_accum.values()) else None
        if not (tool_calls or usage_metadata):
            return None
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_calls=tool_calls,
                usage_metadata=usage_metadata,
                response_metadata={"model_name": self.model} if usage_metadata else {},
            ),
        )

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,  # noqa: ARG002 — required by BaseChatModel
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Sync streaming via litellm.completion(stream=True).

        Falls back to a single non-streaming call if the provider rejects
        ``stream=True`` — covers both eager rejection (from the setup call)
        and lazy rejection (raised on first iteration). The fallback window
        closes once any chunk has been yielded; later errors propagate so the
        caller cannot receive duplicate content. The fallback is local to
        this LLM call, so upstream graph nodes (retrievers, tools) do not
        re-execute.
        """
        call_kwargs = self._build_kwargs(messages, stop, **kwargs)
        name_map = call_kwargs.pop("_ollama_name_map", None)
        nonstream_kwargs = dict(call_kwargs)
        call_kwargs["stream"] = True
        # OpenAI-compatible providers only emit usage chunks when explicitly requested.
        call_kwargs["stream_options"] = {"include_usage": True}
        usage_accum: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        tool_call_accum: Dict[int, Dict[str, str]] = {}
        yielded_any = False
        try:
            response = cast(CustomStreamWrapper, litellm.completion(**call_kwargs))
            for chunk in response:
                content = _process_stream_chunk(chunk, usage_accum, tool_call_accum)
                if content is None:
                    continue
                yielded_any = True
                yield ChatGenerationChunk(message=AIMessageChunk(content=content))
        except Exception:
            if yielded_any:
                raise
            LOGGER.warning(
                "Provider rejected streaming for this LLM call; falling back to non-streaming",
                exc_info=True,
            )
            yield self._result_as_chunk(
                self._response_to_chat_result(litellm.completion(**nonstream_kwargs), name_map=name_map),
            )
            return
        terminal = self._terminal_chunk(usage_accum, tool_call_accum, name_map)
        if terminal is not None:
            yield terminal

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,  # noqa: ARG002 — required by BaseChatModel
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Async streaming via litellm.acompletion(stream=True). See ``_stream`` for fallback semantics."""
        call_kwargs = self._build_kwargs(messages, stop, **kwargs)
        name_map = call_kwargs.pop("_ollama_name_map", None)
        nonstream_kwargs = dict(call_kwargs)
        call_kwargs["stream"] = True
        # OpenAI-compatible providers only emit usage chunks when explicitly requested.
        call_kwargs["stream_options"] = {"include_usage": True}
        usage_accum: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        tool_call_accum: Dict[int, Dict[str, str]] = {}
        yielded_any = False
        try:
            response = cast(CustomStreamWrapper, await litellm.acompletion(**call_kwargs))
            async for chunk in response:
                content = _process_stream_chunk(chunk, usage_accum, tool_call_accum)
                if content is None:
                    continue
                yielded_any = True
                yield ChatGenerationChunk(message=AIMessageChunk(content=content))
        except Exception:
            if yielded_any:
                raise
            LOGGER.warning(
                "Provider rejected streaming for this LLM call; falling back to non-streaming",
                exc_info=True,
            )
            yield self._result_as_chunk(
                self._response_to_chat_result(await litellm.acompletion(**nonstream_kwargs), name_map=name_map),
            )
            return
        terminal = self._terminal_chunk(usage_accum, tool_call_accum, name_map)
        if terminal is not None:
            yield terminal
