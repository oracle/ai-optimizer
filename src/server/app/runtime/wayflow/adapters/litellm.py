"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integrated LiteLLM support for WayFlow.

Combines the runtime model adapter and deserialization plugin so that AgentSpec
LiteLlmConfig components materialize as WayFlow LiteLlmModel instances backed by
litellm.acompletion().
"""
# spell-checker: ignore litellm acompletion ollama llmgenerationconfig llmmodel
# spell-checker: ignore llmmodelfactory requesthelpers tokenusage wayflowcore
# spell-checker: ignore wayflow agentspec pyagentspec pydanticdeserializationplugin

import json
import logging
from collections.abc import AsyncIterable, Mapping
from typing import Any, Dict, List, Optional

import litellm
from pyagentspec.serialization.pydanticdeserializationplugin import (
    PydanticComponentDeserializationPlugin,
)
from wayflowcore.messagelist import Message, MessageType, TextContent
from wayflowcore.models._requesthelpers import (
    StreamChunkType,
    TaggedMessageChunkTypeWithTokenUsage,
)
from wayflowcore.models.llmgenerationconfig import LlmGenerationConfig
from wayflowcore.models.llmmodel import LlmCompletion, LlmModel, Prompt
from wayflowcore.models.llmmodelfactory import LlmModelFactory
from wayflowcore.serialization.plugins import WayflowDeserializationPlugin
from wayflowcore.tokenusage import TokenUsage
from wayflowcore.tools.tools import ToolRequest

from server.app.agentspec.adapters.litellm import (
    LITELLM_COMPONENT_TYPE,
    LITELLM_PLUGIN_TYPES,
)
from server.app.mcp.tools.schemas import get_oci_profile
from server.app.models.litellm_utils import (
    build_oci_litellm_params,
    strip_unsupported_penalties,
)
from server.app.runtime.ollama_tools import (
    contextualize_tool_result,
    is_ollama_model,
    normalize_ollama_provider,
    sanitize_tools,
)

LOGGER = logging.getLogger(__name__)


def _safe_json_loads(s: str) -> Any:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def _build_litellm_messages(messages: List[Message], contextualize_tools: bool = False) -> List[Dict[str, Any]]:
    """Convert WayFlow messages to OpenAI-format dicts for litellm."""
    result = []
    for msg in messages:
        role = msg.role if hasattr(msg, "role") and msg.role else "user"

        # Tool result messages
        if msg.message_type == MessageType.TOOL_RESULT:
            if msg.tool_result is not None:
                content = str(msg.tool_result.content)
                if contextualize_tools:
                    tool_name = getattr(msg.tool_result, "name", None) or msg.tool_result.tool_request_id
                    content = contextualize_tool_result(tool_name, content)
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_result.tool_request_id,
                        "content": content,
                    }
                )
            continue

        # Extract text content
        content = msg.content if hasattr(msg, "content") and msg.content else ""
        if not content and hasattr(msg, "contents") and msg.contents:
            parts = []
            for c in msg.contents:
                if isinstance(c, TextContent):
                    parts.append(c.content or "")
                else:
                    parts.append(str(c))
            content = "".join(parts)

        # Tool request messages (assistant with tool_calls)
        if msg.tool_requests:
            tool_calls = []
            for tr in msg.tool_requests:
                tool_calls.append(
                    {
                        "type": "function",
                        "id": tr.tool_request_id,
                        "function": {
                            "name": tr.name,
                            "arguments": json.dumps(tr.args) if isinstance(tr.args, dict) else str(tr.args),
                        },
                    }
                )
            entry: Dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
            if content:
                entry["content"] = content
            result.append(entry)
            continue

        result.append({"role": role, "content": content})
    return result


def _build_litellm_tools(tools: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
    """Convert WayFlow tools to OpenAI function-calling format for litellm."""
    if not tools:
        return None

    litellm_tools = []
    for tool in tools:
        func_def: Dict[str, Any] = {
            "name": tool.name,
            "description": tool.description or "",
        }
        if hasattr(tool, "parameters") and tool.parameters:
            # ServerTool / MCPTool: parameters is a dict of {name: schema}
            params = tool.parameters
            properties = {}
            required = []
            for param_name, param_schema in params.items():
                prop = dict(param_schema)
                prop.pop("title", None)
                properties[param_name] = prop
                if "default" not in prop:
                    required.append(param_name)
            func_def["parameters"] = {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        elif hasattr(tool, "input_descriptors") and tool.input_descriptors:
            # Property-based tools: input_descriptors is a list of Property objects
            properties = {}
            required = []
            for prop in tool.input_descriptors:
                prop_schema = prop.to_json_schema() if hasattr(prop, "to_json_schema") else {"type": "string"}
                prop_name = prop_schema.pop("title", prop.name if hasattr(prop, "name") else "param")
                properties[prop_name] = prop_schema
                if "default" not in prop_schema:
                    required.append(prop_name)
            func_def["parameters"] = {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        else:
            func_def["parameters"] = {"type": "object", "properties": {}}

        litellm_tools.append({"type": "function", "function": func_def})
    return litellm_tools


def _build_litellm_response_format(response_format: Optional[Any]) -> Optional[Dict[str, Any]]:
    """Convert WayFlow response format (Property) to litellm response_format."""
    if response_format is None:
        return None
    schema = response_format.to_json_schema() if hasattr(response_format, "to_json_schema") else None
    if schema:
        return {"type": "json_schema", "json_schema": {"name": "response", "schema": schema}}
    return None


class LiteLlmModel(LlmModel):
    """WayFlow LlmModel implementation backed by LiteLLM.

    Uses litellm.acompletion() for in-process LLM calls, supporting
    any provider LiteLLM supports (OpenAI, OCI GenAI, Ollama, etc.).

    Parameters
    ----------
    provider:
        LiteLLM provider prefix (e.g., "openai", "ollama", "oci").
    model_id:
        Model name (e.g., "gpt-4o", "llama3-groq-tool-use:8b").
        Combined with provider as "{provider}/{model_id}" for litellm.
    generation_config:
        Default generation parameters (temperature, max_tokens, etc.).
    api_key:
        Optional API key. Can also be set via environment variables.
    api_base:
        Optional base URL override for the provider.
    extra_kwargs:
        Additional kwargs passed to litellm.acompletion() on every call.
    """

    def __init__(
        self,
        provider: str,
        model_id: str,
        generation_config: Optional[LlmGenerationConfig] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        extra_kwargs: Optional[Dict[str, Any]] = None,
        supports_structured_generation: Optional[bool] = True,
        supports_tool_calling: Optional[bool] = True,
        **kwargs,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.api_base = api_base
        self.extra_kwargs = extra_kwargs or {}

        provider = normalize_ollama_provider(provider)
        self.litellm_model = f"{provider}/{model_id}" if provider else model_id
        self.last_token_usage: Optional[TokenUsage] = None
        self._tool_name_map: Dict[str, str] = {}

        super().__init__(
            model_id=model_id,
            generation_config=generation_config,
            supports_structured_generation=supports_structured_generation,
            supports_tool_calling=supports_tool_calling,
            **kwargs,
        )

    @staticmethod
    def _config_to_dict(cfg: Any) -> Dict[str, Any]:
        """Convert a generation config object to a flat dict with non-None values."""
        if hasattr(cfg, "to_dict"):
            raw = cfg.to_dict()
        elif hasattr(cfg, "model_dump"):
            raw = cfg.model_dump()
        elif isinstance(cfg, Mapping):
            raw = dict(cfg)
        else:
            raw = {}
        return {k: v for k, v in raw.items() if v is not None}

    @staticmethod
    def _extract_max_tokens(config_dict: Dict[str, Any]) -> Optional[int]:
        """Pop and return max_tokens (or max_new_tokens) from a config dict."""
        if "max_new_tokens" in config_dict:
            return config_dict.pop("max_new_tokens")
        if "max_tokens" in config_dict:
            return config_dict.pop("max_tokens")
        return None

    def _merge_generation_params(self, prompt: Prompt, kwargs: Dict[str, Any]) -> None:
        """Merge generation config from model defaults and prompt overrides into kwargs."""
        merged_params: Dict[str, Any] = {}
        model_tokens = None
        prompt_tokens = None

        if self.generation_config is not None:
            model_dict = self._config_to_dict(self.generation_config)
            model_tokens = self._extract_max_tokens(model_dict)
            merged_params.update(model_dict)

        if prompt.generation_config is not None:
            prompt_dict = self._config_to_dict(prompt.generation_config)
            prompt_tokens = self._extract_max_tokens(prompt_dict)
            merged_params.update(prompt_dict)

        if prompt_tokens is not None:
            kwargs["max_tokens"] = prompt_tokens
        elif model_tokens is not None:
            kwargs["max_tokens"] = model_tokens

        if not merged_params:
            return

        if "temperature" in merged_params:
            kwargs["temperature"] = merged_params.pop("temperature")
        if "top_p" in merged_params:
            kwargs["top_p"] = merged_params.pop("top_p")
        # Pass remaining params, but never override critical fields
        _critical = {"model", "messages", "stream", "drop_params", "tools", "stream_options"}
        for k, v in merged_params.items():
            if k not in _critical:
                kwargs[k] = v

    def _build_call_kwargs(self, prompt: Prompt, stream: bool = False) -> Dict[str, Any]:
        """Build the kwargs dict for litellm.acompletion()."""
        # Extra kwargs go first so they can't override critical fields
        kwargs: Dict[str, Any] = dict(self.extra_kwargs)

        ollama = is_ollama_model(self.litellm_model)
        kwargs["model"] = self.litellm_model
        kwargs["messages"] = _build_litellm_messages(prompt.messages, contextualize_tools=ollama)
        kwargs["stream"] = stream

        tools = _build_litellm_tools(prompt.tools)
        if tools:
            if ollama:
                tools, self._tool_name_map = sanitize_tools(tools)
            kwargs["tools"] = tools

        # Request usage stats in streaming responses
        if stream:
            kwargs["stream_options"] = {"include_usage": True}

        # Response format
        response_format = _build_litellm_response_format(prompt.response_format)
        if response_format:
            kwargs["response_format"] = response_format

        self._merge_generation_params(prompt, kwargs)

        # Let litellm silently drop params unsupported by the provider
        kwargs["drop_params"] = True

        # Auth / base URL
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["base_url"] = self.api_base

        return kwargs

    def _parse_response(self, response: Any) -> LlmCompletion:
        """Parse a litellm response (OpenAI-compatible) into LlmCompletion."""
        if not response.choices:
            return LlmCompletion(
                message=Message(role="assistant", contents=[TextContent(content="")]),
                token_usage=None,
            )
        choice = response.choices[0]
        resp_message = choice.message

        # Tool calls (may also carry text content)
        content = resp_message.content or ""
        if resp_message.tool_calls:
            name_map = self._tool_name_map
            message = Message(
                tool_requests=[
                    ToolRequest(
                        name=name_map.get(tc.function.name or "", tc.function.name or ""),
                        args=_safe_json_loads(tc.function.arguments),
                        tool_request_id=tc.id,
                    )
                    for tc in resp_message.tool_calls
                ],
                contents=[TextContent(content=content)] if content else None,
                role="assistant",
            )
        else:
            message = Message(
                role="assistant",
                contents=[TextContent(content=content)],
            )

        # Token usage
        token_usage = self._extract_chunk_usage(response)

        return LlmCompletion(message=message, token_usage=token_usage)

    async def _generate_impl(self, prompt: Prompt) -> LlmCompletion:
        kwargs = self._build_call_kwargs(prompt, stream=False)
        LOGGER.debug("LiteLLM call: model=%s", self.litellm_model)
        response = await litellm.acompletion(**kwargs)
        completion = self._parse_response(response)
        self.last_token_usage = completion.token_usage
        return completion

    @staticmethod
    def _extract_chunk_usage(chunk: Any) -> Optional[TokenUsage]:
        """Extract token usage from a response or stream chunk if present."""
        usage = getattr(chunk, "usage", None)
        if not usage:
            return None
        return TokenUsage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            exact_count=True,
        )

    @staticmethod
    def _accumulate_tool_call(accumulated: Dict[int, Dict[str, Any]], tc_chunk: Any) -> None:
        """Accumulate a streamed tool call chunk."""
        idx = tc_chunk.index
        if idx not in accumulated:
            accumulated[idx] = {"id": tc_chunk.id or "", "name": "", "arguments": ""}
        if tc_chunk.id:
            accumulated[idx]["id"] = tc_chunk.id
        if tc_chunk.function:
            if tc_chunk.function.name:
                accumulated[idx]["name"] += tc_chunk.function.name
            if tc_chunk.function.arguments:
                accumulated[idx]["arguments"] += tc_chunk.function.arguments

    def _build_stream_message(
        self,
        accumulated_chunks: List[str],
        accumulated_tool_calls: Dict[int, Dict[str, Any]],
    ) -> Message:
        """Build the final message from accumulated stream data."""
        final_text = "".join(accumulated_chunks)
        name_map = self._tool_name_map
        if accumulated_tool_calls:
            return Message(
                tool_requests=[
                    ToolRequest(
                        name=name_map.get(tc["name"] or "", tc["name"] or ""),
                        args=_safe_json_loads(tc["arguments"]),
                        tool_request_id=tc["id"],
                    )
                    for tc in accumulated_tool_calls.values()
                ],
                contents=[TextContent(content=final_text)] if final_text else None,
                role="assistant",
            )
        return Message(
            role="assistant",
            contents=[TextContent(content=final_text)],
        )

    async def _on_stream_text(self, content: str) -> None:
        """Hook called for each text chunk during streaming. Override to intercept."""

    async def _stream_generate_impl(self, prompt: Prompt) -> AsyncIterable[TaggedMessageChunkTypeWithTokenUsage]:
        kwargs = self._build_call_kwargs(prompt, stream=True)
        LOGGER.debug("LiteLLM streaming call: model=%s", self.litellm_model)

        response = await litellm.acompletion(**kwargs)
        if not isinstance(response, AsyncIterable):
            # Fallback: provider returned a non-streaming response.
            completion = self._parse_response(response)
            contents = completion.message.contents if completion.message else None
            text = contents[0].content if contents and isinstance(contents[0], TextContent) else ""
            yield (
                StreamChunkType.START_CHUNK,
                Message(role="assistant", contents=[TextContent(content="")]),
                completion.token_usage,
            )
            if text:
                await self._on_stream_text(text)
                yield (
                    StreamChunkType.TEXT_CHUNK,
                    Message(role="assistant", contents=[TextContent(content=text)]),
                    completion.token_usage,
                )
            yield StreamChunkType.END_CHUNK, completion.message, completion.token_usage
            return

        accumulated_chunks: List[str] = []
        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
        token_usage = None
        started = False  # Track whether START_CHUNK has been yielded

        async for chunk in response:
            token_usage = self._extract_chunk_usage(chunk) or token_usage

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta is None:
                continue

            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    self._accumulate_tool_call(accumulated_tool_calls, tc_chunk)
            else:
                content_chunk = getattr(delta, "content", None) or ""
                if content_chunk:
                    if not started:
                        started = True
                        yield (
                            StreamChunkType.START_CHUNK,
                            Message(role="assistant", contents=[TextContent(content="")]),
                            token_usage,
                        )
                    accumulated_chunks.append(content_chunk)
                    await self._on_stream_text(content_chunk)
                    yield (
                        StreamChunkType.TEXT_CHUNK,
                        Message(role="assistant", contents=[TextContent(content=content_chunk)]),
                        token_usage,
                    )

        # Yield START_CHUNK if we never got any text chunks (e.g. tool-call-only response).
        # wayflowcore's _stream_message requires START_CHUNK to append a new message;
        # without it, END_CHUNK overwrites the last existing message in the conversation.
        if not started:
            yield (
                StreamChunkType.START_CHUNK,
                Message(role="assistant", contents=[]),
                token_usage,
            )

        # Yield END_CHUNK after the loop so that token usage from the
        # final provider chunk (which may arrive after finish_reason) is
        # included.
        final_msg = self._build_stream_message(accumulated_chunks, accumulated_tool_calls)
        yield StreamChunkType.END_CHUNK, final_msg, token_usage

    @property
    def config(self) -> Dict[str, Any]:
        return {
            "model_type": "litellm",
            "provider": self.provider,
            "model_id": self.model_id,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "supports_structured_generation": self.supports_structured_generation,
            "supports_tool_calling": self.supports_tool_calling,
            "generation_config": (self.generation_config.to_dict() if self.generation_config is not None else None),
            "extra_kwargs": self.extra_kwargs,
        }


_LITELLM_FACTORY_STATE: Dict[str, bool] = {"registered": False}


def register_litellm_model_factory():
    """Register LiteLlmModel with WayFlow's LlmModelFactory.

    Call this once at application startup to enable deserialization
    of LiteLLM model configs from AgentSpec YAML/JSON.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    if _LITELLM_FACTORY_STATE["registered"]:
        return
    _LITELLM_FACTORY_STATE["registered"] = True

    _original_from_config = LlmModelFactory.from_config

    @staticmethod
    def _patched_from_config(model_config: Dict[str, Any]) -> LlmModel:
        if model_config.get("model_type") == "litellm":
            config_copy = model_config.copy()
            config_copy.pop("model_type")
            config_copy.pop("_component_type", None)
            config_copy.pop("_referenced_objects", None)

            gen_config = config_copy.pop("generation_config", None)
            if gen_config is not None:
                gen_config = LlmGenerationConfig.from_dict(gen_config)

            return LiteLlmModel(generation_config=gen_config, **config_copy)
        return _original_from_config(model_config)

    LlmModelFactory.from_config = staticmethod(_patched_from_config)


class LiteLlmWayflowPlugin(WayflowDeserializationPlugin):
    """Converts AgentSpec LiteLlmConfig into WayFlow LiteLlmModel at runtime."""

    @property
    def plugin_name(self) -> str:
        return "litellm"

    @property
    def plugin_version(self) -> str:
        return "1.0.0"

    @property
    def supported_component_types(self) -> List[str]:
        return [LITELLM_COMPONENT_TYPE]

    @property
    def required_agentspec_deserialization_plugins(self) -> list:
        return [PydanticComponentDeserializationPlugin(LITELLM_PLUGIN_TYPES)]

    def convert_to_wayflow(
        self,
        conversion_context: Any,  # noqa: ARG002 — required by WayflowDeserializationPlugin interface
        agentspec_component: Any,
        tool_registry: Any,  # noqa: ARG002
        converted_components: Dict[str, Any],  # noqa: ARG002
    ) -> LiteLlmModel:
        # Build runtime generation config from both AgentSpec LlmGenerationConfig
        # and LiteLlmConfig-specific fields (penalties, max_tokens override).
        params: Dict[str, Any] = {}

        if agentspec_component.default_generation_parameters:
            agentspec_gen = agentspec_component.default_generation_parameters
            params = agentspec_gen.model_dump(exclude_none=True)

        # LiteLlmConfig-level params take precedence
        if agentspec_component.max_tokens is not None:
            params["max_tokens"] = agentspec_component.max_tokens
        model_key = f"{agentspec_component.provider}/{agentspec_component.model_id}"
        freq, pres = strip_unsupported_penalties(
            model_key,
            agentspec_component.frequency_penalty,
            agentspec_component.presence_penalty,
        )
        if freq is not None:
            params["frequency_penalty"] = freq
        else:
            params.pop("frequency_penalty", None)
        if pres is not None:
            params["presence_penalty"] = pres
        else:
            params.pop("presence_penalty", None)

        gen_config = LlmGenerationConfig.from_dict(params) if params else None

        extra_kwargs = {}
        if agentspec_component.provider == "oci":
            oci_profile = get_oci_profile()
            if oci_profile:
                extra_kwargs = build_oci_litellm_params(oci_profile)

        return LiteLlmModel(
            provider=agentspec_component.provider,
            model_id=agentspec_component.model_id,
            generation_config=gen_config,
            api_key=agentspec_component.api_key,
            api_base=agentspec_component.api_base,
            extra_kwargs=extra_kwargs,
            name=agentspec_component.name,
            id=agentspec_component.id,
            description=agentspec_component.description,
        )


def get_litellm_wayflow_plugin() -> LiteLlmWayflowPlugin:
    """Return the WayFlow deserialization plugin for LiteLlmConfig → LiteLlmModel."""
    return LiteLlmWayflowPlugin()
