"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for OracleChatLiteLLM — the thin ``ChatLiteLLM`` subclass that adds
Ollama tool-name sanitization and a streaming-rejection fallback. Upstream
behavior (usage_metadata, response_metadata, tool-call parsing, message
conversion) is owned by ``langchain_litellm.ChatLiteLLM`` and tested there.
"""
# spell-checker: disable

from typing import Any, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import RunnableBinding

from server.app.runtime.langgraph.adapters.litellm import (
    OracleChatLiteLLM,
    _flatten_to_text,
    ainvoke_text_from_spec,
    chat_model_from_spec,
    usage_metadata_to_token_usage,
)
from server.tests.constants import TEST_OLLAMA_MODEL_KEY, TEST_OPENAI_MODEL_KEY


def _stream_chunks(*contents: str) -> Iterator[dict]:
    """Build litellm-style streaming chunks (dicts) with the given content slices."""
    for content in contents:
        yield {
            "choices": [{"delta": {"role": "assistant", "content": content}, "finish_reason": None}],
        }


def _non_streaming_response(content: str, prompt: int = 1, completion: int = 1) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


class TestFlattenToText:
    def test_string_passthrough(self):
        assert _flatten_to_text("hello") == "hello"

    def test_list_of_text_blocks_joined(self):
        assert _flatten_to_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\nb"

    def test_bare_strings_in_list_preserved(self):
        assert _flatten_to_text(["x", "y"]) == "x\ny"

    def test_unknown_block_serialized(self):
        result = _flatten_to_text([{"type": "image", "url": "http://x"}])
        assert "image" in result and "http://x" in result

    def test_none_returns_empty(self):
        assert _flatten_to_text(None) == ""


class TestUsageMetadataToTokenUsage:
    def test_none_returns_none(self):
        assert usage_metadata_to_token_usage(None) is None

    def test_empty_returns_none(self):
        assert usage_metadata_to_token_usage({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}) is None

    def test_full(self):
        result = usage_metadata_to_token_usage({"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
        assert result is not None
        assert result.prompt_tokens == 5
        assert result.completion_tokens == 3
        assert result.total_tokens == 8

    def test_total_falls_back_to_sum(self):
        result = usage_metadata_to_token_usage({"input_tokens": 4, "output_tokens": 2, "total_tokens": 0})
        assert result is not None and result.total_tokens == 6


class TestChatModelFromSpec:
    @staticmethod
    def _spec(**overrides: Any) -> Any:
        spec = MagicMock(name="LiteLlmModelSpec")
        spec.model_key = TEST_OPENAI_MODEL_KEY
        spec.api_key = "sk-test"
        spec.api_base = "https://api.example.com"
        spec.temperature = 0.7
        spec.top_p = 0.95
        spec.max_tokens = 100
        spec.frequency_penalty = 0.5
        spec.presence_penalty = 0.3
        spec.oci_params = {}
        for k, v in overrides.items():
            setattr(spec, k, v)
        return spec

    def test_basic_construction(self):
        llm = chat_model_from_spec(self._spec())
        assert llm.model == TEST_OPENAI_MODEL_KEY
        assert llm.api_key == "sk-test"
        assert llm.api_base == "https://api.example.com"
        assert llm.temperature == 0.7
        assert llm.top_p == 0.95
        assert llm.max_tokens == 100

    def test_penalties_routed_through_model_kwargs(self):
        llm = chat_model_from_spec(self._spec())
        assert llm.model_kwargs.get("frequency_penalty") == 0.5
        assert llm.model_kwargs.get("presence_penalty") == 0.3

    def test_oci_params_routed_through_model_kwargs(self):
        spec = self._spec(oci_params={"oci_region": "us-chicago-1", "oci_compartment_id": "ocid1.x"})
        llm = chat_model_from_spec(spec)
        assert llm.model_kwargs["oci_region"] == "us-chicago-1"
        assert llm.model_kwargs["oci_compartment_id"] == "ocid1.x"

    def test_per_call_overrides_take_precedence(self):
        llm = chat_model_from_spec(self._spec(), temperature=0.0, max_tokens=10)
        assert llm.temperature == 0.0
        assert llm.max_tokens == 10
        assert llm.top_p == 0.95  # spec value preserved when not overridden

    def test_omits_none_penalties(self):
        spec = self._spec(frequency_penalty=None, presence_penalty=None)
        llm = chat_model_from_spec(spec)
        assert "frequency_penalty" not in llm.model_kwargs
        assert "presence_penalty" not in llm.model_kwargs

    def test_reasoning_effort_routed_through_model_kwargs(self):
        # Capability selection happens before construction; this verifies that a
        # supported value reaches LiteLLM unchanged.
        llm = chat_model_from_spec(self._spec(), reasoning_effort="none")
        assert llm.model_kwargs.get("reasoning_effort") == "none"

    def test_omits_reasoning_effort_by_default(self):
        llm = chat_model_from_spec(self._spec())
        assert "reasoning_effort" not in llm.model_kwargs


class TestAinvokeTextFromSpecReasoning:
    """``disable_reasoning`` is how rephrase/grade keep deterministic utility calls
    fast by disabling or minimizing the selected model's reasoning trace."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("model_key", ["openai/o1", "openai/o3"])
    @patch("server.app.runtime.langgraph.adapters.litellm.chat_model_from_spec")
    async def test_disable_reasoning_omits_unsupported_none(self, mock_factory, model_key):
        mock_factory.return_value.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
        spec = MagicMock(model_key=model_key)
        spec.model_key = model_key
        await ainvoke_text_from_spec(spec, "prompt", disable_reasoning=True)
        assert mock_factory.call_args.kwargs["reasoning_effort"] is None

    @pytest.mark.anyio
    @pytest.mark.parametrize("model_key", ["openai/gpt-5.4-mini", "ollama_chat/granite4.1:8b"])
    @patch("server.app.runtime.langgraph.adapters.litellm.chat_model_from_spec")
    async def test_disable_reasoning_passes_none_when_supported(self, mock_factory, model_key):
        mock_factory.return_value.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
        spec = MagicMock(model_key=model_key)
        spec.model_key = model_key
        await ainvoke_text_from_spec(spec, "prompt", disable_reasoning=True)
        assert mock_factory.call_args.kwargs["reasoning_effort"] == "none"

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.chat_model_from_spec")
    async def test_gpt_oss_uses_lowest_supported_reasoning_effort(self, mock_factory):
        mock_factory.return_value.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
        spec = MagicMock(model_key="ollama_chat/gpt-oss:20b")
        spec.model_key = "ollama_chat/gpt-oss:20b"

        await ainvoke_text_from_spec(spec, "prompt", disable_reasoning=True)

        reasoning_effort = mock_factory.call_args.kwargs["reasoning_effort"]
        assert reasoning_effort == "low"
        assert (
            litellm.get_optional_params(
                model="gpt-oss:20b",
                custom_llm_provider="ollama_chat",
                reasoning_effort=reasoning_effort,
                drop_params=True,
            )["think"]
            == "low"
        )

    @pytest.mark.anyio
    async def test_disable_reasoning_uses_litellm_mock_completion(self):
        spec = TestChatModelFromSpec._spec(
            model_key="openai/o3",
            oci_params={"mock_response": "mocked utility response"},
        )

        result = await ainvoke_text_from_spec(spec, "prompt", disable_reasoning=True)

        assert result == "mocked utility response"

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.chat_model_from_spec")
    async def test_default_leaves_reasoning_unset(self, mock_factory):
        mock_factory.return_value.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
        await ainvoke_text_from_spec(MagicMock(), "prompt")
        assert mock_factory.call_args.kwargs["reasoning_effort"] is None


class TestReasoningContentFlattening:
    """Reasoning-capable providers force AIMessage.content to a list of blocks; we flatten it."""

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_stream_flattens_reasoning_blocks_in_chunk_content(self, mock_completion):
        """Streamed chunks with reasoning_content arrive as list content from upstream.

        LangGraph aggregates chunks into the final ``AIMessage`` and stores it in
        chat history; without flattening, hidden reasoning persists across turns
        and downstream graph nodes see it as message content.
        """

        # Upstream injects {"type":"thinking", ...} into chunk.content when a
        # delta carries reasoning_content; emulate that with a delta that has
        # both reasoning_content and text content.
        def stream_with_reasoning():
            yield {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": "the answer",
                            "reasoning_content": "let me think...",
                        },
                        "finish_reason": None,
                    },
                ],
            }

        mock_completion.return_value = stream_with_reasoning()
        llm = OracleChatLiteLLM(model="anthropic/claude-haiku")
        emitted = list(llm._stream([HumanMessage(content="hi")]))

        for chunk in emitted:
            assert isinstance(chunk.message, AIMessageChunk)
            assert isinstance(chunk.message.content, str), (
                "chunk.content must be a flat string — list-shaped reasoning blocks "
                "would persist into LangGraph's aggregated message + chat history"
            )

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.acompletion_with_retry", new_callable=AsyncMock)
    async def test_astream_flattens_reasoning_blocks_in_chunk_content(self, mock_acompletion):
        """Async counterpart of the chunk-flatten test."""

        async def stream_with_reasoning():
            yield {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": "the answer",
                            "reasoning_content": "let me think...",
                        },
                        "finish_reason": None,
                    },
                ],
            }

        mock_acompletion.return_value = stream_with_reasoning()
        llm = OracleChatLiteLLM(model="anthropic/claude-haiku")
        emitted = [chunk async for chunk in llm._astream([HumanMessage(content="hi")])]

        for chunk in emitted:
            assert isinstance(chunk.message, AIMessageChunk)
            assert isinstance(chunk.message.content, str)

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_create_chat_result_flattens_reasoning_content_to_plain_text(self, mock_completion):
        """
        Sessions stringify ``msg.content`` for the answer;
        list content renders the reasoning JSON in the user-visible answer.
        """
        mock_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "the answer",
                        "reasoning_content": "let me think about this carefully",
                    },
                    "finish_reason": "stop",
                },
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }
        llm = OracleChatLiteLLM(model="anthropic/claude-haiku")
        result = llm._generate([HumanMessage(content="hi")])

        msg = result.generations[0].message
        assert isinstance(msg, AIMessage)
        assert isinstance(msg.content, str), "content must be flattened to plain text for session consumers"
        assert msg.content == "the answer"
        # Reasoning is still accessible to callers that want it (e.g. a future thinking-display UI).
        assert msg.additional_kwargs.get("reasoning_content") == "let me think about this carefully"


class TestOracleChatLiteLLMNonOllama:
    """For non-Ollama models, OracleChatLiteLLM defers entirely to upstream."""

    def test_bind_tools_skips_sanitization(self):
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        tool = {"type": "function", "function": {"name": "my-tool", "parameters": {}}}
        bound = llm.bind_tools([tool])
        assert isinstance(bound, RunnableBinding)
        bound_tools = bound.kwargs["tools"]
        assert bound_tools[0]["function"]["name"] == "my-tool"

    def test_bind_tools_maps_false_tool_choice_to_none(self):
        """``tool_choice=False`` must not reach LiteLLM as a literal boolean.

        OpenAI/LiteLLM tool APIs accept ``"none" | "auto" | "required"`` or a
        function dict. Upstream ``ChatLiteLLM.bind_tools`` only normalizes
        ``True`` / ``"any"`` → ``"required"`` and explicitly leaves ``False``
        as-is — so the caller's intent ("disable tool use") would be sent as
        ``tool_choice: false`` and rejected by the provider.
        """
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        tool = {"type": "function", "function": {"name": "my-tool", "parameters": {}}}
        bound = llm.bind_tools([tool], tool_choice=False)
        assert isinstance(bound, RunnableBinding)
        assert bound.kwargs["tool_choice"] == "none"


class TestOracleChatLiteLLMFalseToolChoiceOllama:
    """The Ollama branch must apply the same false-to-none normalization."""

    def test_bind_tools_maps_false_tool_choice_to_none(self):
        llm = OracleChatLiteLLM(model=TEST_OLLAMA_MODEL_KEY)
        tool = {"type": "function", "function": {"name": "sqlcl_list-connections", "parameters": {}}}
        bound = llm.bind_tools([tool], tool_choice=False)
        assert isinstance(bound, RunnableBinding)
        assert bound.kwargs["tool_choice"] == "none"


class TestOracleChatLiteLLMOllama:
    """Ollama models get tool-name sanitization and tool-result contextualization."""

    def test_bind_tools_sanitizes_hyphens(self):
        llm = OracleChatLiteLLM(model=TEST_OLLAMA_MODEL_KEY)
        tool = {"type": "function", "function": {"name": "sqlcl_list-connections", "parameters": {}}}
        bound = llm.bind_tools([tool])
        assert isinstance(bound, RunnableBinding)
        bound_tools = bound.kwargs["tools"]
        assert bound_tools[0]["function"]["name"] == "sqlcl_list_connections"

    def test_bind_tools_threads_name_map_for_unsanitization(self):
        llm = OracleChatLiteLLM(model=TEST_OLLAMA_MODEL_KEY)
        tool = {"type": "function", "function": {"name": "sqlcl_list-connections", "parameters": {}}}
        bound = llm.bind_tools([tool])
        assert isinstance(bound, RunnableBinding)
        name_map = bound.kwargs.get("_ollama_name_map")
        assert name_map == {"sqlcl_list_connections": "sqlcl_list-connections"}

    def test_tool_message_content_flattened_and_contextualized(self):
        llm = OracleChatLiteLLM(model=TEST_OLLAMA_MODEL_KEY)
        tool_msg = ToolMessage(content=[{"type": "text", "text": "42"}], tool_call_id="c1", name="get_count")
        normalized = llm._normalize_tool_message(tool_msg)
        assert isinstance(normalized, ToolMessage)
        # Ollama small models hallucinate on terse tool results → prefix with tool name.
        assert "get_count" in normalized.content
        assert "42" in normalized.content

    def test_tool_message_content_flattened_only_for_non_ollama(self):
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        tool_msg = ToolMessage(content=[{"type": "text", "text": "42"}], tool_call_id="c1", name="get_count")
        normalized = llm._normalize_tool_message(tool_msg)
        assert normalized.content == "42"


class TestClientParamsOverrides:
    """Per-request scoping + patches for upstream parameter omissions."""

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_api_key_scoped_per_request_not_via_global_mutation(self, mock_completion):
        """Concurrent multi-client: api_key must be in kwargs, not on the litellm module.

        Upstream ``ChatLiteLLM._client_params`` mutates ``self.client.api_key`` (the
        litellm module). With concurrent requests for different clients this races —
        one client's auth can overwrite another's mid-await.
        """
        import litellm

        original_api_key = litellm.api_key
        try:
            mock_completion.return_value = _non_streaming_response("ok")
            llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY, api_key="sk-client-A")
            llm._generate([HumanMessage(content="hi")])
            kwargs = mock_completion.call_args.kwargs
            assert kwargs.get("api_key") == "sk-client-A"
            # Critical: the litellm module's api_key must NOT have been mutated.
            assert litellm.api_key == original_api_key, (
                "global litellm.api_key changed during per-request scoping check"
            )
        finally:
            litellm.api_key = original_api_key

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_api_base_passed_as_base_url(self, mock_completion):
        """Ollama tool-call parsing fails when ``api_base`` is a call kwarg; use ``base_url``."""
        mock_completion.return_value = _non_streaming_response("ok")
        llm = OracleChatLiteLLM(model=TEST_OLLAMA_MODEL_KEY, api_base="http://localhost:11434")
        llm._generate([HumanMessage(content="hi")])
        kwargs = mock_completion.call_args.kwargs
        assert kwargs.get("base_url") == "http://localhost:11434"
        assert "api_base" not in kwargs, "api_base must not be passed as a kwarg — breaks Ollama tool calls"

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_top_p_forwarded(self, mock_completion):
        """Upstream's ``_default_params`` omits ``top_p`` even though it's a documented field."""
        mock_completion.return_value = _non_streaming_response("ok")
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY, top_p=0.95)
        llm._generate([HumanMessage(content="hi")])
        kwargs = mock_completion.call_args.kwargs
        assert kwargs.get("top_p") == 0.95

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_generate_with_explicit_stream_false_overrides_instance_streaming(self, mock_completion):
        """Caller-supplied ``stream=False`` must reach litellm even when ``streaming=True`` on the model.

        Upstream's ``_generate(stream=False)`` only flips its branch decision;
        ``params["stream"]`` still inherits ``self.streaming`` and litellm
        receives ``stream=True``, returning a stream object that
        ``_create_chat_result`` cannot parse.
        """
        mock_completion.return_value = _non_streaming_response("ok")
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY, streaming=True)
        llm._generate([HumanMessage(content="hi")], stream=False)
        kwargs = mock_completion.call_args.kwargs
        assert kwargs.get("stream") is False, "explicit stream=False must override self.streaming"

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_drop_params_true_for_provider_compatibility(self, mock_completion):
        """``drop_params=True`` lets LiteLLM silently drop OpenAI params a provider rejects.

        Without this, e.g. Mistral fails on the default ``presence_penalty=0.0`` /
        ``frequency_penalty=0.0`` inherited from ``LanguageModelParameters`` — LiteLLM
        raises ``UnsupportedParamsError`` before the call reaches the provider.
        The previous bridge always set this; the migration must preserve it.
        """
        mock_completion.return_value = _non_streaming_response("ok")
        llm = OracleChatLiteLLM(model="mistral/mistral-large")
        llm._generate([HumanMessage(content="hi")])
        kwargs = mock_completion.call_args.kwargs
        assert kwargs.get("drop_params") is True

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_oci_openai_gpt5_drops_max_tokens(self, mock_completion):
        """OCI OpenAI GPT-5 models reject max_tokens and LiteLLM misroutes max_completion_tokens."""
        mock_completion.return_value = _non_streaming_response("ok")
        llm = OracleChatLiteLLM(model="oci/openai.gpt-5.5", max_tokens=100)
        llm._generate([HumanMessage(content="hi")])
        kwargs = mock_completion.call_args.kwargs
        assert "max_tokens" not in kwargs
        assert "max_completion_tokens" not in kwargs

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_oci_openai_o_series_drops_max_tokens(self, mock_completion):
        """OCI OpenAI O-series models use maxCompletionTokens, but LiteLLM's catalog may miss them."""
        mock_completion.return_value = _non_streaming_response("ok")
        llm = OracleChatLiteLLM(model="oci/openai.o1", max_tokens=100)
        llm._generate([HumanMessage(content="hi")])
        assert "max_tokens" not in mock_completion.call_args.kwargs

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_oci_openai_non_reasoning_keeps_max_tokens(self, mock_completion):
        """The suppression is scoped to GPT-5/O-series, not every OCI OpenAI model."""
        mock_completion.return_value = _non_streaming_response("ok")
        llm = OracleChatLiteLLM(model="oci/openai.gpt-4.1", max_tokens=100)
        llm._generate([HumanMessage(content="hi")])
        assert mock_completion.call_args.kwargs.get("max_tokens") == 100

    def test_oci_openai_gpt5_drops_explicit_fallback_token_kwargs(self):
        """Fallback param merging must not reintroduce per-call token-limit kwargs."""
        llm = OracleChatLiteLLM(model="oci/openai.gpt-5.5", max_tokens=100)
        _, params = llm._build_non_streaming_params(
            [HumanMessage(content="hi")],
            None,
            {"max_completion_tokens": 20, "max_tokens": 10},
        )
        assert "max_tokens" not in params
        assert "max_completion_tokens" not in params


class TestStreamingFallback:
    """OracleChatLiteLLM falls back to non-streaming when the provider rejects stream=True."""

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_stream_falls_back_on_eager_setup_failure(self, mock_completion):
        def fake_completion(**kwargs):
            if kwargs.get("stream"):
                raise RuntimeError("provider does not support streaming")
            return _non_streaming_response("non-streamed answer", prompt=4, completion=2)

        mock_completion.side_effect = fake_completion
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        emitted = list(llm._stream([HumanMessage(content="hi")]))

        ai_messages = [c.message for c in emitted if isinstance(c.message, AIMessageChunk)]
        contents = [m.content for m in ai_messages if isinstance(m.content, str) and m.content]
        assert "non-streamed answer" in "".join(contents)

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_stream_falls_back_on_lazy_iteration_failure(self, mock_completion):
        def lazy_failing_stream():
            raise RuntimeError("provider rejected stream on first read")
            yield  # pragma: no cover

        def fake_completion(**kwargs):
            if kwargs.get("stream"):
                return lazy_failing_stream()
            return _non_streaming_response("non-streamed answer", prompt=4, completion=2)

        mock_completion.side_effect = fake_completion
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        emitted = list(llm._stream([HumanMessage(content="hi")]))

        ai_messages = [c.message for c in emitted if isinstance(c.message, AIMessageChunk)]
        assert "non-streamed answer" in "".join(m.content for m in ai_messages if isinstance(m.content, str))

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_stream_propagates_failure_after_content_yielded(self, mock_completion):
        def stream_then_fail():
            yield from _stream_chunks("partial")
            raise RuntimeError("connection dropped mid-stream")

        mock_completion.return_value = stream_then_fail()
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        with pytest.raises(RuntimeError, match="connection dropped"):
            list(llm._stream([HumanMessage(content="hi")]))

    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.completion_with_retry")
    def test_stream_fallback_overrides_instance_streaming_flag(self, mock_completion):
        """Fallback retry must force ``stream=False`` even when the model has ``streaming=True``.

        Upstream's ``_generate(stream=False)`` only controls the branch
        decision; the params dict it builds from ``_default_params`` still
        carries ``stream=self.streaming``. So a model with instance-level
        streaming would re-issue *another* streaming request inside the
        "fallback" path — exactly the call that just failed.
        """
        call_count = 0

        def fake_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                assert kwargs.get("stream") is True, "first attempt must be streaming"
                raise RuntimeError("provider does not support streaming")
            assert kwargs.get("stream") is False, "fallback retry must force stream=False"
            return _non_streaming_response("ok", prompt=2, completion=1)

        mock_completion.side_effect = fake_completion
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY, streaming=True)
        list(llm._stream([HumanMessage(content="hi")]))
        assert call_count == 2

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.acompletion_with_retry", new_callable=AsyncMock)
    async def test_astream_falls_back_on_eager_setup_failure(self, mock_acompletion):
        async def fake_acompletion(**kwargs):
            if kwargs.get("stream"):
                raise RuntimeError("provider does not support streaming")
            return _non_streaming_response("non-streamed answer", prompt=4, completion=2)

        mock_acompletion.side_effect = fake_acompletion
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        emitted = [chunk async for chunk in llm._astream([HumanMessage(content="hi")])]

        ai_messages = [c.message for c in emitted if isinstance(c.message, AIMessageChunk)]
        assert "non-streamed answer" in "".join(m.content for m in ai_messages if isinstance(m.content, str))

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.acompletion_with_retry", new_callable=AsyncMock)
    async def test_astream_falls_back_on_lazy_iteration_failure(self, mock_acompletion):
        async def lazy_failing_stream():
            raise RuntimeError("provider rejected stream on first read")
            yield  # pragma: no cover

        async def fake_acompletion(**kwargs):
            if kwargs.get("stream"):
                return lazy_failing_stream()
            return _non_streaming_response("non-streamed answer", prompt=4, completion=2)

        mock_acompletion.side_effect = fake_acompletion
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        emitted = [chunk async for chunk in llm._astream([HumanMessage(content="hi")])]

        ai_messages = [c.message for c in emitted if isinstance(c.message, AIMessageChunk)]
        assert "non-streamed answer" in "".join(m.content for m in ai_messages if isinstance(m.content, str))

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.acompletion_with_retry", new_callable=AsyncMock)
    async def test_astream_propagates_failure_after_content_yielded(self, mock_acompletion):
        async def stream_then_fail():
            for chunk in _stream_chunks("partial"):
                yield chunk
            raise RuntimeError("connection dropped mid-stream")

        mock_acompletion.return_value = stream_then_fail()
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY)
        with pytest.raises(RuntimeError, match="connection dropped"):
            [chunk async for chunk in llm._astream([HumanMessage(content="hi")])]

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.acompletion_with_retry", new_callable=AsyncMock)
    async def test_astream_fallback_overrides_instance_streaming_flag(self, mock_acompletion):
        """Async counterpart of the sync fallback-stream-override test."""
        call_count = 0

        async def fake_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                assert kwargs.get("stream") is True, "first attempt must be streaming"
                raise RuntimeError("provider does not support streaming")
            assert kwargs.get("stream") is False, "fallback retry must force stream=False"
            return _non_streaming_response("ok", prompt=2, completion=1)

        mock_acompletion.side_effect = fake_acompletion
        llm = OracleChatLiteLLM(model=TEST_OPENAI_MODEL_KEY, streaming=True)
        [chunk async for chunk in llm._astream([HumanMessage(content="hi")])]
        assert call_count == 2


class TestOllamaToolCallUnsanitization:
    """Tool calls returned from the LLM have their original (hyphenated) names restored."""

    def test_unsanitize_chunk_restores_all_three_tool_call_fields(self):
        """``AIMessageChunk`` derives ``tool_calls`` from ``tool_call_chunks`` at construction.

        Mutating only ``tool_call_chunks`` after the fact leaves the parsed
        ``tool_calls`` (and the raw OpenAI dict in ``additional_kwargs``) with
        the sanitized name — consumers reading the standard ``.tool_calls``
        field would dispatch to the wrong (unregistered) tool name.
        """
        from server.app.runtime.langgraph.adapters.litellm import _unsanitize_chunk_tool_calls

        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "type": "tool_call_chunk",
                        "id": "c1",
                        "name": "sqlcl_list_connections",
                        "args": "{}",
                        "index": 0,
                    },
                ],
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "sqlcl_list_connections", "arguments": "{}"},
                        },
                    ],
                },
            ),
        )

        _unsanitize_chunk_tool_calls(chunk, {"sqlcl_list_connections": "sqlcl_list-connections"})

        msg = chunk.message
        assert isinstance(msg, AIMessageChunk)
        assert msg.tool_call_chunks[0]["name"] == "sqlcl_list-connections"
        assert msg.tool_calls and msg.tool_calls[0]["name"] == "sqlcl_list-connections"
        assert msg.additional_kwargs["tool_calls"][0]["function"]["name"] == "sqlcl_list-connections"

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.ChatLiteLLM.acompletion_with_retry", new_callable=AsyncMock)
    async def test_agenerate_unsanitizes_tool_call_names(self, mock_acompletion):
        # Provider returns the *sanitized* name we sent; bridge restores original on the way back.
        mock_acompletion.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "sqlcl_list_connections", "arguments": "{}"},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                },
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        llm = OracleChatLiteLLM(model=TEST_OLLAMA_MODEL_KEY)
        bound = llm.bind_tools(
            [{"type": "function", "function": {"name": "sqlcl_list-connections", "parameters": {}}}],
        )
        result = await bound.ainvoke([HumanMessage(content="list them")])

        assert isinstance(result, AIMessage)
        assert result.tool_calls
        assert result.tool_calls[0]["name"] == "sqlcl_list-connections"
