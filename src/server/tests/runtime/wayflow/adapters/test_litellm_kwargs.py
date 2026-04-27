"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for LiteLlmModel call kwargs, streaming, and integration.
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

import pytest
from wayflowcore.messagelist import Message, MessageType, TextContent
from wayflowcore.models import LlmGenerationConfig, Prompt
from wayflowcore.models._requesthelpers import StreamChunkType
from wayflowcore.tools import ServerTool

from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel
from server.tests.runtime.shared_helpers import make_stream_chunk
from server.tests.runtime.wayflow.helpers import ollama_available

# ---------------------------------------------------------------------------
# _build_call_kwargs
# ---------------------------------------------------------------------------


class TestBuildCallKwargs:
    """Unit tests for _build_call_kwargs."""

    def _simple_prompt(self):
        """Return a minimal single-message prompt for testing."""
        return Prompt(messages=[Message(content="Hi", message_type=MessageType.USER)])

    def test_basic_fields(self):
        """Verify basic call kwargs include model, stream, and drop_params."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["model"] == "openai/gpt-4o"
        assert kwargs["stream"] is False
        assert kwargs["drop_params"] is True
        assert len(kwargs["messages"]) == 1

    def test_stream_includes_usage_option(self):
        """Verify streaming mode adds stream_options with include_usage."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        kwargs = model._build_call_kwargs(self._simple_prompt(), stream=True)
        assert kwargs["stream"] is True
        assert kwargs["stream_options"] == {"include_usage": True}

    def test_api_key_forwarded(self):
        """Verify api_key is included in call kwargs when set."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", api_key="sk-test")
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["api_key"] == "sk-test"

    def test_api_base_forwarded(self):
        """Verify api_base is included in call kwargs when set."""
        model = LiteLlmModel(provider="ollama", model_id="qwen3:8b", api_base="http://localhost:11434")
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["base_url"] == "http://localhost:11434"

    def test_no_api_key_when_none(self):
        """Verify api_key is omitted from call kwargs when not set."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert "api_key" not in kwargs

    def test_no_api_base_when_none(self):
        """Verify api_base is omitted from call kwargs when not set."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert "api_base" not in kwargs

    def test_generation_config_applied(self):
        """Verify generation config params are forwarded to call kwargs."""
        gen = LlmGenerationConfig.from_dict({"max_tokens": 100, "temperature": 0.5, "top_p": 0.9})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=gen)
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["max_tokens"] == 100
        assert kwargs["temperature"] == 0.5
        assert kwargs["top_p"] == 0.9

    def test_penalty_params_forwarded(self):
        """Verify frequency and presence penalty params are forwarded."""
        gen = LlmGenerationConfig.from_dict({"frequency_penalty": 0.7, "presence_penalty": 0.3})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=gen)
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["frequency_penalty"] == 0.7
        assert kwargs["presence_penalty"] == 0.3

    def test_prompt_gen_config_overrides_model(self):
        """Verify prompt-level generation config overrides model-level config."""
        model_gen = LlmGenerationConfig.from_dict({"temperature": 0.5, "max_tokens": 100})
        prompt_gen = LlmGenerationConfig.from_dict({"temperature": 0.9, "max_tokens": 200})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=model_gen)
        prompt = Prompt(
            messages=[Message(content="Hi", message_type=MessageType.USER)],
            generation_config=prompt_gen,
        )
        kwargs = model._build_call_kwargs(prompt)
        assert kwargs["temperature"] == 0.9
        assert kwargs["max_tokens"] == 200

    def test_prompt_max_new_tokens_overrides_model_max_tokens(self):
        """Verify prompt max_new_tokens takes precedence over model max_tokens."""
        model_gen = LlmGenerationConfig.from_dict({"max_tokens": 150})
        prompt_gen = LlmGenerationConfig.from_dict({"max_new_tokens": 75})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=model_gen)
        prompt = Prompt(
            messages=[Message(content="Hi", message_type=MessageType.USER)],
            generation_config=prompt_gen,
        )
        kwargs = model._build_call_kwargs(prompt)
        assert kwargs["max_tokens"] == 75

    def test_tools_forwarded(self):
        """Verify tools from the prompt are included in call kwargs."""
        tool = ServerTool(
            name="greet",
            description="Say hello",
            parameters={"name": {"type": "string"}},
            output={"type": "string"},
            func=lambda name: name,
        )
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        prompt = Prompt(
            messages=[Message(content="Hi", message_type=MessageType.USER)],
            tools=[tool],
        )
        kwargs = model._build_call_kwargs(prompt)
        assert "tools" in kwargs
        assert kwargs["tools"][0]["function"]["name"] == "greet"
        assert "name" in kwargs["tools"][0]["function"]["parameters"]["properties"]

    def test_no_tools_key_when_no_tools(self):
        """Verify 'tools' key is absent when no tools are provided."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert "tools" not in kwargs

    def test_extra_kwargs_applied(self):
        """Verify extra_kwargs are merged into call kwargs."""
        model = LiteLlmModel(
            provider="openai",
            model_id="gpt-4o",
            extra_kwargs={"seed": 42, "user": "test-user"},
        )
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["seed"] == 42
        assert kwargs["user"] == "test-user"

    def test_max_new_tokens_mapped_to_max_tokens(self):
        """Verify max_new_tokens is mapped to max_tokens in call kwargs."""
        gen = LlmGenerationConfig.from_dict({"max_new_tokens": 50})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=gen)
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["max_tokens"] == 50
        assert "max_new_tokens" not in kwargs

    def test_prompt_gen_config_layers_on_model_defaults(self):
        """A sparse prompt generation_config must layer on top of model defaults, not replace them."""
        model_gen = LlmGenerationConfig.from_dict({"temperature": 0.3, "top_p": 0.9, "stop": ["END"]})
        prompt_gen = LlmGenerationConfig.from_dict({"max_tokens": 200})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=model_gen)
        prompt = Prompt(
            messages=[Message(content="Hi", message_type=MessageType.USER)],
            generation_config=prompt_gen,
        )
        kwargs = model._build_call_kwargs(prompt)
        assert kwargs["max_tokens"] == 200
        assert kwargs["temperature"] == 0.3
        assert kwargs["top_p"] == 0.9
        assert kwargs["stop"] == ["END"]

    def test_stop_sequences_forwarded_to_litellm(self):
        """Stop sequences in runtime generation_config must reach litellm call kwargs."""
        gen = LlmGenerationConfig.from_dict({"stop": ["\n\n", "END"]})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=gen)
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["stop"] == ["\n\n", "END"]


class TestBuildCallKwargsSafety:
    """Tests for _build_call_kwargs override protection and safety invariants."""

    def _simple_prompt(self):
        """Return a minimal single-message prompt for testing."""
        return Prompt(messages=[Message(content="Hi", message_type=MessageType.USER)])

    def test_extra_kwargs_cannot_override_model(self):
        """extra_kwargs must not silently replace the model string."""
        model = LiteLlmModel(
            provider="openai",
            model_id="gpt-4o",
            extra_kwargs={"model": "override-model"},
        )
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["model"] == "openai/gpt-4o"

    def test_extra_kwargs_cannot_override_drop_params(self):
        """Verify extra_kwargs cannot override the drop_params safety flag."""
        model = LiteLlmModel(
            provider="openai",
            model_id="gpt-4o",
            extra_kwargs={"drop_params": False},
        )
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["drop_params"] is True

    def test_extra_kwargs_cannot_override_messages(self):
        """Verify extra_kwargs cannot override the messages list."""
        model = LiteLlmModel(
            provider="openai",
            model_id="gpt-4o",
            extra_kwargs={"messages": [{"role": "user", "content": "injected"}]},
        )
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["messages"] != [{"role": "user", "content": "injected"}]

    def test_gen_config_residual_keys_cannot_override_model(self):
        """Residual keys in generation_config must not override critical fields like model."""
        gen = LlmGenerationConfig.from_dict({"temperature": 0.5, "model": "override-model"})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=gen)
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["model"] == "openai/gpt-4o"

    def test_gen_config_residual_keys_cannot_override_stream(self):
        """Residual keys in generation_config must not override the stream flag."""
        gen = LlmGenerationConfig.from_dict({"temperature": 0.5, "stream": True})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=gen)
        kwargs = model._build_call_kwargs(self._simple_prompt(), stream=False)
        assert kwargs["stream"] is False

    def test_gen_config_residual_keys_cannot_override_drop_params(self):
        """Residual keys in generation_config must not override drop_params."""
        gen = LlmGenerationConfig.from_dict({"temperature": 0.5, "drop_params": False})
        model = LiteLlmModel(provider="openai", model_id="gpt-4o", generation_config=gen)
        kwargs = model._build_call_kwargs(self._simple_prompt())
        assert kwargs["drop_params"] is True


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class TestStreamGenerate:
    """Unit tests for _stream_generate_impl using mocked litellm."""

    async def test_text_streaming_emits_chunks_and_end(self):
        """Verify text streaming emits TEXT_CHUNK and END_CHUNK with assembled content."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        chunks = [
            make_stream_chunk(content="Hello"),
            make_stream_chunk(content=" world"),
            make_stream_chunk(content=None, finish_reason="stop"),
        ]

        async def mock_aiter():
            for c in chunks:
                yield c

        with patch("litellm.acompletion", return_value=mock_aiter()):
            prompt = Prompt(messages=[Message(content="Hi", message_type=MessageType.USER)])
            collected = []
            async for chunk_type, msg, _ in model._stream_generate_impl(prompt):
                collected.append((chunk_type, msg))

        text_chunks = [(t, m) for t, m in collected if t == StreamChunkType.TEXT_CHUNK]
        end_chunks = [(t, m) for t, m in collected if t == StreamChunkType.END_CHUNK]
        assert len(text_chunks) == 2
        assert text_chunks[0][1].contents is not None
        assert isinstance(text_chunks[0][1].contents[0], TextContent)
        assert text_chunks[0][1].contents[0].content == "Hello"
        assert text_chunks[1][1].contents is not None
        assert isinstance(text_chunks[1][1].contents[0], TextContent)
        assert text_chunks[1][1].contents[0].content == " world"
        assert len(end_chunks) == 1
        assert end_chunks[0][1].contents is not None
        assert isinstance(end_chunks[0][1].contents[0], TextContent)
        assert end_chunks[0][1].contents[0].content == "Hello world"

    async def test_tool_call_streaming_emits_end_chunk(self):
        """Verify streamed tool calls produce an END_CHUNK with assembled ToolRequests."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")

        tc1 = MagicMock()
        tc1.index, tc1.id, tc1.function.name, tc1.function.arguments = 0, "call_1", "get_weather", ""
        tc2 = MagicMock()
        tc2.index, tc2.id, tc2.function.name, tc2.function.arguments = 0, None, None, '{"city":'
        tc3 = MagicMock()
        tc3.index, tc3.id, tc3.function.name, tc3.function.arguments = 0, None, None, ' "Paris"}'

        chunks = [
            make_stream_chunk(tool_calls=[tc1]),
            make_stream_chunk(tool_calls=[tc2]),
            make_stream_chunk(tool_calls=[tc3], finish_reason="tool_calls"),
        ]

        async def mock_aiter():
            for c in chunks:
                yield c

        with patch("litellm.acompletion", return_value=mock_aiter()):
            prompt = Prompt(messages=[Message(content="Weather?", message_type=MessageType.USER)])
            collected = []
            async for chunk_type, msg, _ in model._stream_generate_impl(prompt):
                collected.append((chunk_type, msg))

        text_chunks = [t for t, m in collected if t == StreamChunkType.TEXT_CHUNK]
        end_chunks = [(t, m) for t, m in collected if t == StreamChunkType.END_CHUNK]
        assert len(text_chunks) == 0
        assert len(end_chunks) == 1
        final = end_chunks[0][1]
        assert final.tool_requests is not None
        assert len(final.tool_requests) == 1
        assert final.tool_requests[0].name == "get_weather"
        assert final.tool_requests[0].args == {"city": "Paris"}
        assert final.tool_requests[0].tool_request_id == "call_1"

    async def test_multiple_parallel_tool_calls_streaming(self):
        """Verify parallel tool calls in a single chunk are both captured."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")

        tc_a = MagicMock()
        tc_a.index, tc_a.id, tc_a.function.name, tc_a.function.arguments = 0, "call_1", "tool_a", '{"x": 1}'
        tc_b = MagicMock()
        tc_b.index, tc_b.id, tc_b.function.name, tc_b.function.arguments = 1, "call_2", "tool_b", '{"y": 2}'

        chunks = [
            make_stream_chunk(tool_calls=[tc_a, tc_b], finish_reason="tool_calls"),
        ]

        async def mock_aiter():
            for c in chunks:
                yield c

        with patch("litellm.acompletion", return_value=mock_aiter()):
            prompt = Prompt(messages=[Message(content="Do both", message_type=MessageType.USER)])
            collected = []
            async for chunk_type, msg, _ in model._stream_generate_impl(prompt):
                collected.append((chunk_type, msg))

        end_chunks = [m for t, m in collected if t == StreamChunkType.END_CHUNK]
        assert len(end_chunks) == 1
        trs = end_chunks[0].tool_requests
        assert trs is not None
        assert len(trs) == 2
        names = {tr.name for tr in trs}
        assert names == {"tool_a", "tool_b"}

    async def test_streaming_tool_call_preserves_text_content(self):
        """When the LLM streams text then tool calls, the END_CHUNK must include both."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")

        tc = MagicMock()
        tc.index, tc.id, tc.function.name, tc.function.arguments = 0, "call_1", "get_weather", '{"city": "Paris"}'

        chunks = [
            make_stream_chunk(content="Let me check. "),
            make_stream_chunk(tool_calls=[tc], finish_reason="tool_calls"),
        ]

        async def mock_aiter():
            for c in chunks:
                yield c

        with patch("litellm.acompletion", return_value=mock_aiter()):
            prompt = Prompt(messages=[Message(content="Weather?", message_type=MessageType.USER)])
            collected = []
            async for chunk_type, msg, _ in model._stream_generate_impl(prompt):
                collected.append((chunk_type, msg))

        end_chunks = [m for t, m in collected if t == StreamChunkType.END_CHUNK]
        assert len(end_chunks) == 1
        final = end_chunks[0]
        # Must have tool requests
        assert final.tool_requests is not None
        assert len(final.tool_requests) == 1
        assert final.tool_requests[0].name == "get_weather"
        # Must also preserve the text content
        assert final.contents is not None
        assert isinstance(final.contents[0], TextContent)
        assert final.contents[0].content == "Let me check. "

    async def test_streaming_token_usage_captured(self):
        """Verify token usage is captured from the final streaming chunk."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")

        usage_mock = MagicMock()
        usage_mock.prompt_tokens = 10
        usage_mock.completion_tokens = 5
        usage_mock.total_tokens = 15

        chunks = [
            make_stream_chunk(content="Hi"),
            make_stream_chunk(content=None, finish_reason="stop", usage=usage_mock),
        ]

        async def mock_aiter():
            for c in chunks:
                yield c

        with patch("litellm.acompletion", return_value=mock_aiter()):
            prompt = Prompt(messages=[Message(content="Hi", message_type=MessageType.USER)])
            last_usage = None
            async for _, _msg, token_usage in model._stream_generate_impl(prompt):
                if token_usage is not None:
                    last_usage = token_usage

        assert last_usage is not None
        assert last_usage.input_tokens == 10
        assert last_usage.output_tokens == 5

    async def test_generate_sets_last_token_usage(self):
        """Verify _generate_impl stores token_usage in last_token_usage."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        assert model.last_token_usage is None

        usage_mock = MagicMock()
        usage_mock.prompt_tokens = 20
        usage_mock.completion_tokens = 10
        usage_mock.total_tokens = 30

        response = MagicMock()
        choice = MagicMock()
        choice.message.content = "Hello"
        choice.message.tool_calls = None
        response.choices = [choice]
        response.usage = usage_mock

        with patch("litellm.acompletion", return_value=response):
            prompt = Prompt(messages=[Message(content="Hi", message_type=MessageType.USER)])
            await model._generate_impl(prompt)

        assert model.last_token_usage is not None
        assert model.last_token_usage.input_tokens == 20
        assert model.last_token_usage.output_tokens == 10

    async def test_empty_choices_chunk_skipped(self):
        """Chunks with empty choices (e.g. usage-only) should not crash."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")

        normal = make_stream_chunk(content="Hi", finish_reason="stop")
        empty = MagicMock()
        empty.choices = []
        empty.usage = None

        chunks = [normal, empty]

        async def mock_aiter():
            for c in chunks:
                yield c

        with patch("litellm.acompletion", return_value=mock_aiter()):
            prompt = Prompt(messages=[Message(content="Hi", message_type=MessageType.USER)])
            collected = []
            async for chunk_type, _, _usage in model._stream_generate_impl(prompt):
                collected.append(chunk_type)

        assert StreamChunkType.END_CHUNK in collected


# ---------------------------------------------------------------------------
# Integration tests (require running ollama)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not ollama_available(), reason="ollama not running at 127.0.0.1:11434")
class TestLiteLlmModelGenerate:
    """Integration tests requiring a running ollama instance."""

    async def test_generate_text_response(self, litellm_model):
        """Verify a simple text generation returns content and token usage."""
        prompt = Prompt(
            messages=[
                Message(
                    content="What is 2+2? Reply with just the number.",
                    message_type=MessageType.USER,
                )
            ]
        )
        completion = await litellm_model.generate_async(prompt)
        assert completion.message is not None
        assert completion.message.contents
        assert isinstance(completion.message.contents[0], TextContent)
        assert "4" in completion.message.contents[0].content
        assert completion.token_usage is not None
        assert completion.token_usage.input_tokens > 0
        assert completion.token_usage.output_tokens > 0

    async def test_generate_with_tool_calling(self, litellm_model):
        """Verify the model invokes a tool and returns a valid ToolRequest."""
        tool = ServerTool(
            name="get_weather",
            description="Get the current weather for a city",
            parameters={"city": {"type": "string", "description": "The city name"}},
            output={"type": "string"},
            func=lambda city: f"Sunny in {city}",
        )
        prompt = Prompt(
            messages=[
                Message(
                    content="What is the weather in Paris?",
                    message_type=MessageType.USER,
                )
            ],
            tools=[tool],
        )
        completion = await litellm_model._generate_impl(prompt)
        assert completion.message.tool_requests is not None
        assert len(completion.message.tool_requests) > 0
        tr = completion.message.tool_requests[0]
        assert tr.name == "get_weather"
        assert "city" in tr.args
        assert "paris" in tr.args["city"].lower()

    async def test_stream_generate(self, litellm_model):
        """Verify streaming produces chunks that assemble into the final message."""
        prompt = Prompt(
            messages=[
                Message(
                    content="Say hello in French. Reply with one word only.",
                    message_type=MessageType.USER,
                )
            ]
        )
        chunks = []
        final_message = None
        async for chunk_type, chunk, _ in litellm_model._stream_generate_impl(prompt):
            if chunk_type == StreamChunkType.TEXT_CHUNK:
                assert chunk.contents is not None
                assert isinstance(chunk.contents[0], TextContent)
                chunks.append(chunk.contents[0].content)
            elif chunk_type == StreamChunkType.END_CHUNK:
                final_message = chunk

        assert len(chunks) > 0
        assert final_message is not None
        assert final_message.contents is not None
        assert isinstance(final_message.contents[0], TextContent)
        assert final_message.contents[0].content
        assembled = "".join(chunks)
        assert assembled == final_message.contents[0].content

    async def test_multi_turn_conversation(self, litellm_model):
        """Verify the model recalls context from earlier turns in a conversation."""
        messages = [
            Message(content="My name is Alice.", message_type=MessageType.USER),
            Message(
                content="Hello Alice! Nice to meet you.",
                message_type=MessageType.AGENT,
            ),
            Message(
                content="What is my name? Reply with just the name.",
                message_type=MessageType.USER,
            ),
        ]
        prompt = Prompt(messages=messages)
        completion = await litellm_model._generate_impl(prompt)
        assert completion.message.contents is not None
        assert isinstance(completion.message.contents[0], TextContent)
        assert "Alice" in completion.message.contents[0].content
