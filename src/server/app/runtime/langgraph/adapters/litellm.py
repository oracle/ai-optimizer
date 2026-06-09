"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OracleChatLiteLLM — thin subclass of ``langchain_litellm.ChatLiteLLM`` adding the
Oracle-specific behavior upstream does not provide:

- Ollama tool-name sanitization in :meth:`bind_tools` (Ollama's ``/api/chat``
  rejects hyphenated function names; small models also need tool-result
  contextualization). Sanitized names are restored before tool calls reach
  graph callers.
- Streaming-rejection fallback in :meth:`_stream` / :meth:`_astream`. Some
  providers reject ``stream=True`` either eagerly (raised at the
  ``litellm.acompletion`` call) or lazily (raised when the connection
  actually opens during first iteration). When this happens *before* any
  chunk has been yielded, the call transparently downgrades to a single
  non-streaming request so callers don't 5xx.
- Ollama tool-result contextualization in :meth:`_create_message_dicts`,
  plus normalization of list-content tool messages to a string
  (LiteLLM/OpenAI tool messages must carry string content).
"""
# spell-checker: ignore unsanitize ollama acompletion afallback agenerate astream litellm ainvoke qwen

import json
import logging
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Type, Union

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import agenerate_from_stream, generate_from_stream
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_litellm import ChatLiteLLM
from pydantic import BaseModel

from server.app.api.v1.schemas.chat import TokenUsage
from server.app.models.litellm_utils import LiteLlmModelSpec
from server.app.runtime.ollama_tools import (
    contextualize_tool_result,
    is_ollama_model,
    sanitize_tool_name,
    sanitize_tools,
    unsanitize_tool_name,
)

LOGGER = logging.getLogger(__name__)

_OLLAMA_NAME_MAP_KEY = "_ollama_name_map"
_OCI_OPENAI_MAX_COMPLETION_PREFIXES = ("openai.gpt-5", "openai.o")


def _flatten_to_text(content: Any) -> str:
    """Flatten content (string or list of blocks) to a string preserving every block.

    Used for **inbound** content (e.g. LangGraph tool-message payloads being
    forwarded to LiteLLM, which requires string content for ``role: "tool"``).
    Non-text blocks are JSON-serialized so information the caller sent is not
    silently dropped on the wire. Use :func:`extract_response_text` instead
    when reading content *out of* an LLM reply.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    parts.append(json.dumps(block, default=str))
        return "\n".join(parts)
    return str(content) if content is not None else ""


def _is_oci_openai_max_completion_model(model: str) -> bool:
    """Return True for OCI OpenAI models that reject ``max_tokens``."""
    if not model:
        return False
    name = model.lower()
    if not name.startswith("oci/"):
        return False
    model_id = name.split("/", 1)[1]
    return model_id.startswith(_OCI_OPENAI_MAX_COMPLETION_PREFIXES)


def _drop_oci_openai_unsupported_token_limits(params: Dict[str, Any], model: Optional[str] = None) -> Dict[str, Any]:
    """Remove token-limit params LiteLLM currently mistranslates for OCI OpenAI models.

    OCI OpenAI GPT-5/O-series models reject ``max_tokens`` and require
    ``max_completion_tokens``. LiteLLM 1.87.0's OCI adapter only switches to
    OCI ``maxCompletionTokens`` when its local model catalog marks a model as
    reasoning-capable, and that catalog misses newer OCI OpenAI model names.
    Passing ``max_completion_tokens`` is not a safe workaround either: the
    upstream adapter can still translate it to legacy ``maxTokens``.
    """
    if _is_oci_openai_max_completion_model(str(params.get("model") or model or "")):
        params.pop("max_tokens", None)
        params.pop("max_completion_tokens", None)
    return params


def extract_response_text(content: Any) -> str:
    """Extract plain text from an LLM reply's ``content``, dropping non-text blocks.

    Reasoning-capable providers via ``langchain_litellm`` prepend a
    ``{"type": "thinking", "thinking": "..."}`` block to the content list
    before the answer's ``{"type": "text", ...}``. Treat those blocks (and
    any other non-text block — image, audio, etc.) as metadata so callers
    see only the answer text. To surface reasoning to a UI, read it
    separately from the message before calling this.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content) if content is not None else ""


def _unsanitize_tool_calls(result: ChatResult, name_map: Optional[Dict[str, str]]) -> None:
    """Restore original (hyphenated) tool names on AIMessage tool_calls."""
    if not name_map:
        return
    for gen in result.generations:
        msg = gen.message
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tc["name"] = unsanitize_tool_name(tc["name"], name_map)


def _flatten_chunk_content(chunk: ChatGenerationChunk) -> None:
    """Replace list-shaped chunk content with plain text in place.

    Reasoning-capable providers (via upstream's ``_convert_delta_to_message_chunk``)
    inject ``{"type": "thinking", ...}`` blocks into ``chunk.message.content``
    when a delta carries ``reasoning_content``. LangGraph aggregates chunks into
    the final ``AIMessage`` and stores it in chat history, so without flattening
    here the reasoning metadata is carried into subsequent turns and downstream graph nodes.
    Reasoning is preserved on ``additional_kwargs["reasoning_content"]`` by
    upstream — flattening here only affects the user-facing ``content`` field.
    """
    msg = chunk.message
    if isinstance(msg, AIMessageChunk) and not isinstance(msg.content, str):
        msg.content = extract_response_text(msg.content)


def _unsanitize_chunk_tool_calls(chunk: ChatGenerationChunk, name_map: Optional[Dict[str, str]]) -> None:
    """Restore original (hyphenated) tool names on every chunk-side tool-call field.

    ``AIMessageChunk`` has three places that carry tool-call names:

    - ``tool_call_chunks`` — the streaming delta accumulator.
    - ``tool_calls`` — derived from ``tool_call_chunks`` at construction time
      (so post-construction mutation of ``tool_call_chunks`` alone leaves
      ``tool_calls`` with the sanitized name).
    - ``additional_kwargs["tool_calls"]`` — the raw OpenAI dict shape that
      ``langchain_litellm._convert_delta_to_message_chunk`` populates
      verbatim from the provider.

    All three must be patched so consumers reading any of them see the
    original tool name.
    """
    if not name_map:
        return
    msg = chunk.message
    if not isinstance(msg, AIMessageChunk):
        return
    for tc_chunk in msg.tool_call_chunks or ():
        name = tc_chunk.get("name")
        if name:
            tc_chunk["name"] = unsanitize_tool_name(name, name_map)
    for tc in msg.tool_calls or ():
        name = tc.get("name")
        if name:
            tc["name"] = unsanitize_tool_name(name, name_map)
    raw_calls = msg.additional_kwargs.get("tool_calls") if msg.additional_kwargs else None
    for raw in raw_calls or ():
        func = raw.get("function") if isinstance(raw, dict) else None
        if isinstance(func, dict):
            func_name = func.get("name")
            if isinstance(func_name, str):
                func["name"] = unsanitize_tool_name(func_name, name_map)


def _result_as_chunk(result: ChatResult) -> ChatGenerationChunk:
    """Repackage a non-streaming ChatResult as a single ChatGenerationChunk."""
    msg = result.generations[0].message
    if not isinstance(msg, AIMessage):
        return ChatGenerationChunk(message=AIMessageChunk(content=str(getattr(msg, "content", ""))))
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content=msg.content,
            tool_calls=list(msg.tool_calls or []),
            usage_metadata=msg.usage_metadata,
            response_metadata=msg.response_metadata or {},
        ),
    )


class OracleChatLiteLLM(ChatLiteLLM):
    """``ChatLiteLLM`` with Ollama tool-call sanitization and streaming-rejection fallback."""

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]],
        tool_choice: Optional[Union[dict, str, bool]] = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        # Upstream's bind_tools maps True / "any" → "required" but leaves False
        # untouched, sending the literal boolean to LiteLLM where OpenAI-compatible
        # APIs reject it. Map False → "none" so disabling tool use produces a valid request.
        if tool_choice is False:
            tool_choice = "none"

        if not is_ollama_model(self.model):
            return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)

        formatted = [convert_to_openai_tool(tool) for tool in tools]
        sanitized, name_map = sanitize_tools(formatted)
        if isinstance(tool_choice, dict):
            func = tool_choice.get("function", {})
            if "name" in func:
                tool_choice = {**tool_choice, "function": {**func, "name": sanitize_tool_name(func["name"])}}

        bound = super().bind_tools(sanitized, tool_choice=tool_choice, **kwargs)
        # Thread name_map through bind kwargs so _generate / _stream can restore
        # the original (hyphenated) tool names on responses.
        return bound.bind(**{_OLLAMA_NAME_MAP_KEY: name_map})

    def _create_message_dicts(self, messages: List[BaseMessage], stop: Optional[List[str]]) -> Any:
        return super()._create_message_dicts([self._normalize_tool_message(m) for m in messages], stop)

    def _normalize_tool_message(self, msg: BaseMessage) -> BaseMessage:
        """Flatten ToolMessage content to a string; for Ollama, also contextualize.

        OpenAI/LiteLLM tool messages must carry ``content`` as a string —
        LangGraph delivers it as content blocks. Ollama small models additionally
        hallucinate on terse tool results, so we prefix with the tool name.
        """
        if not isinstance(msg, ToolMessage):
            return msg
        flat = _flatten_to_text(msg.content)
        if is_ollama_model(self.model) and msg.name:
            flat = contextualize_tool_result(msg.name, flat)
        return msg.model_copy(update={"content": flat})

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        stream: Optional[bool] = None,
        **kwargs: Any,
    ) -> ChatResult:
        name_map = kwargs.pop(_OLLAMA_NAME_MAP_KEY, None)
        should_stream = stream if stream is not None else self.streaming
        if should_stream:
            stream_iter = self._stream(
                messages,
                stop=stop,
                run_manager=run_manager,
                **{**kwargs, _OLLAMA_NAME_MAP_KEY: name_map},
            )
            return generate_from_stream(stream_iter)
        # Upstream's stream= param only flips the branch decision; params built from
        # _client_params still inherit stream=self.streaming. The helper forces stream=False
        # in params so a streaming-enabled model honors a per-call non-streaming request.
        result = self._fallback_non_streaming(messages, stop, run_manager, kwargs)
        _unsanitize_tool_calls(result, name_map)
        return result

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        stream: Optional[bool] = None,
        **kwargs: Any,
    ) -> ChatResult:
        name_map = kwargs.pop(_OLLAMA_NAME_MAP_KEY, None)
        should_stream = stream if stream is not None else self.streaming
        if should_stream:
            stream_iter = self._astream(
                messages,
                stop=stop,
                run_manager=run_manager,
                **{**kwargs, _OLLAMA_NAME_MAP_KEY: name_map},
            )
            return await agenerate_from_stream(stream_iter)
        result = await self._afallback_non_streaming(messages, stop, run_manager, kwargs)
        _unsanitize_tool_calls(result, name_map)
        return result

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        name_map = kwargs.pop(_OLLAMA_NAME_MAP_KEY, None)
        kwargs = _drop_oci_openai_unsupported_token_limits(dict(kwargs), self.model)
        yielded_any = False
        try:
            for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
                _flatten_chunk_content(chunk)
                _unsanitize_chunk_tool_calls(chunk, name_map)
                yielded_any = True
                yield chunk
        except Exception:
            if yielded_any:
                raise
            LOGGER.warning(
                "Provider rejected streaming for this LLM call; falling back to non-streaming",
                exc_info=True,
            )
            result = self._fallback_non_streaming(messages, stop, run_manager, kwargs)
            _unsanitize_tool_calls(result, name_map)
            yield _result_as_chunk(result)

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        name_map = kwargs.pop(_OLLAMA_NAME_MAP_KEY, None)
        kwargs = _drop_oci_openai_unsupported_token_limits(dict(kwargs), self.model)
        yielded_any = False
        try:
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                _flatten_chunk_content(chunk)
                _unsanitize_chunk_tool_calls(chunk, name_map)
                yielded_any = True
                yield chunk
        except Exception:
            if yielded_any:
                raise
            LOGGER.warning(
                "Provider rejected streaming for this LLM call; falling back to non-streaming",
                exc_info=True,
            )
            result = await self._afallback_non_streaming(messages, stop, run_manager, kwargs)
            _unsanitize_tool_calls(result, name_map)
            yield _result_as_chunk(result)

    def _create_chat_result(self, response: Any) -> ChatResult:
        """Flatten any reasoning-injected list content to plain text after upstream parsing.

        When a reasoning-capable provider (Claude, Qwen, etc.) returns
        ``reasoning_content``, upstream's ``_convert_dict_to_message`` injects
        a ``{"type": "thinking", "thinking": "..."}`` block into ``AIMessage.content``,
        flipping it from string to a list of blocks. LangGraph sessions
        stringify ``msg.content`` to extract the answer for non-streaming
        replies — turning the list into a Python repr that renders the
        reasoning JSON in the user-visible answer.

        We flatten the user-facing ``content`` to plain text here. Upstream
        already preserves the original reasoning text in
        ``additional_kwargs["reasoning_content"]``, so callers that want to
        surface it (e.g. a thinking-display UI) can still read it.
        """
        result = super()._create_chat_result(response)
        for gen in result.generations:
            msg = gen.message
            if isinstance(msg, AIMessage) and not isinstance(msg.content, str):
                msg.content = extract_response_text(msg.content)
        return result

    def _build_non_streaming_params(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]],
        kwargs: Dict[str, Any],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Build (message_dicts, params) for a non-streaming fallback call.

        Forces ``stream=False`` after merging caller kwargs and ``_client_params``.
        Upstream's ``_generate(stream=False, ...)`` only flips the branch
        decision; the params dict it sends to litellm still inherits
        ``stream=self.streaming`` from ``_default_params``, which would re-
        issue the streaming request that just failed. By overriding params
        directly we guarantee the retry hits the provider non-streaming
        regardless of instance-level ``streaming`` or any caller-supplied
        ``stream`` kwarg.
        """
        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {**params, **kwargs, "stream": False}
        return message_dicts, _drop_oci_openai_unsupported_token_limits(params)

    def _fallback_non_streaming(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]],
        run_manager: Optional[CallbackManagerForLLMRun],
        kwargs: Dict[str, Any],
    ) -> ChatResult:
        message_dicts, params = self._build_non_streaming_params(messages, stop, kwargs)
        response = self.completion_with_retry(
            messages=message_dicts,
            run_manager=run_manager,
            **params,
        )
        return self._create_chat_result(response)

    async def _afallback_non_streaming(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]],
        run_manager: Optional[AsyncCallbackManagerForLLMRun],
        kwargs: Dict[str, Any],
    ) -> ChatResult:
        message_dicts, params = self._build_non_streaming_params(messages, stop, kwargs)
        response = await self.acompletion_with_retry(
            messages=message_dicts,
            run_manager=run_manager,
            **params,
        )
        return self._create_chat_result(response)

    @property
    def _client_params(self) -> Dict[str, Any]:
        """Build per-call kwargs for ``litellm.(a)completion`` without mutating module state.

        Five corrections vs. ``ChatLiteLLM._client_params``:

        1. **No global mutation.** Upstream sets ``self.client.api_key`` /
           ``self.client.api_base`` on the litellm module. With concurrent
           requests for different clients this races: one request's client
           settings can replace another's mid-await. We pass these values in
           per-request kwargs and never touch the module.
        2. **base_url over api_base.** LiteLLM's Ollama provider fails
           tool-call parsing when ``api_base`` is passed as a call kwarg;
           ``base_url`` works for all providers — so we always pass
           ``base_url``, never ``api_base``.
        3. **top_p forwarded.** Upstream's ``_default_params`` omits
           ``top_p`` even though it's a documented Pydantic field on the
           class; without this fix configured sampling parameters silently
           disappear (vector-search grading, table selection, rephrasing).
        4. **drop_params=True.** Lets LiteLLM silently drop OpenAI params
           a provider doesn't accept (e.g. Mistral rejects the default
           ``presence_penalty=0.0`` / ``frequency_penalty=0.0`` that
           AgentSpec's ``LanguageModelParameters`` carries through).
        5. **OCI OpenAI token limit suppression.** Some GPT-5/O-series OCI
           OpenAI models reject legacy token limit fields, and current LiteLLM
           versions can mistranslate the replacement field for uncataloged
           model names.
        """
        params = dict(self._default_params)
        params["drop_params"] = True
        if self.top_p is not None:
            params["top_p"] = self.top_p
        if self.api_key:
            params["api_key"] = self.api_key
        if self.api_base:
            params["base_url"] = self.api_base
        return _drop_oci_openai_unsupported_token_limits(params)

    @property
    def _llm_type(self) -> str:
        return "oracle-chat-litellm"


def chat_model_from_spec(
    spec: LiteLlmModelSpec,
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> OracleChatLiteLLM:
    """Build an :class:`OracleChatLiteLLM` from a resolved :class:`LiteLlmModelSpec`.

    *temperature* / *max_tokens* override the spec's values for a single call
    (e.g. classifier needs ``temperature=0.0`` regardless of the user setting).
    OCI auth params + frequency/presence penalties flow through ``model_kwargs``.
    """
    model_kwargs: Dict[str, Any] = dict(spec.oci_params)
    if spec.frequency_penalty is not None:
        model_kwargs["frequency_penalty"] = spec.frequency_penalty
    if spec.presence_penalty is not None:
        model_kwargs["presence_penalty"] = spec.presence_penalty
    return OracleChatLiteLLM(
        model=spec.model_key,
        api_key=spec.api_key,
        api_base=spec.api_base,
        temperature=temperature if temperature is not None else spec.temperature,
        top_p=spec.top_p,
        max_tokens=max_tokens if max_tokens is not None else spec.max_tokens,
        model_kwargs=model_kwargs,
    )


async def ainvoke_text_from_spec(
    spec: LiteLlmModelSpec,
    prompt: str,
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Single-prompt LLM completion via a ``LiteLlmModelSpec``-derived model.

    Callers receive plain text with reasoning/non-text blocks stripped.
    Used by the MCP tools (rephrase, grade, retriever) to consolidate the
    ``chat_model_from_spec → ainvoke → extract_response_text`` pattern.
    """
    llm = chat_model_from_spec(spec, temperature=temperature, max_tokens=max_tokens)
    result = await llm.ainvoke([HumanMessage(content=prompt)])
    return extract_response_text(result.content)


def usage_metadata_to_token_usage(usage_metadata: Optional[Mapping[str, Any]]) -> Optional[TokenUsage]:
    """Convert LangChain ``UsageMetadata`` to the runtime's ``TokenUsage`` schema."""
    if not usage_metadata:
        return None
    prompt = int(usage_metadata.get("input_tokens", 0) or 0)
    completion = int(usage_metadata.get("output_tokens", 0) or 0)
    total = int(usage_metadata.get("total_tokens", 0) or 0)
    if not (prompt or completion or total):
        return None
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total or (prompt + completion),
    )
