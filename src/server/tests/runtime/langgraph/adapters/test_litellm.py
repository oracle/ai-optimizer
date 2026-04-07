"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the ChatLiteLLMBridge LangGraph adapter.
"""
# spell-checker: disable

import json
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from server.app.runtime.langgraph.adapters.litellm import (
    ChatLiteLLMBridge,
    _messages_to_openai,
    _parse_tool_calls,
)
from server.tests.runtime.langgraph.helpers import (
    make_usage,
    mock_litellm_response,
)
from server.tests.runtime.shared_helpers import (
    async_iter,
    make_stream_chunk,
    make_usage_chunk,
)

# ---------------------------------------------------------------------------
# TestChatLiteLLMBridgeInit
# ---------------------------------------------------------------------------


class TestChatLiteLLMBridgeInit:
    """Tests for ChatLiteLLMBridge initialization and properties."""

    def test_llm_type(self):
        """Verify _llm_type returns 'litellm-bridge'."""
        llm = ChatLiteLLMBridge(model="test/model")
        assert llm._llm_type == "litellm-bridge"

    def test_default_field_values(self):
        """Verify default field values."""
        llm = ChatLiteLLMBridge(model="test/model")
        assert llm.api_key is None
        assert llm.api_base is None
        assert llm.max_tokens is None
        assert llm.frequency_penalty is None
        assert llm.presence_penalty is None
        assert llm.last_token_usage is None

    def test_all_field_combinations(self):
        """Verify all fields are settable."""
        llm = ChatLiteLLMBridge(
            model="openai/gpt-4o",
            api_key="sk-test",
            api_base="https://api.example.com",
            max_tokens=100,
            frequency_penalty=0.5,
            presence_penalty=0.3,
        )
        assert llm.model == "openai/gpt-4o"
        assert llm.api_key == "sk-test"
        assert llm.api_base == "https://api.example.com"
        assert llm.max_tokens == 100
        assert llm.frequency_penalty == 0.5
        assert llm.presence_penalty == 0.3


# ---------------------------------------------------------------------------
# TestMessagesToOpenai
# ---------------------------------------------------------------------------


class TestMessagesToOpenai:
    """Tests for _messages_to_openai conversion."""

    def test_system_message(self):
        """Verify SystemMessage maps to system role."""
        result = _messages_to_openai([SystemMessage(content="Be helpful.")])
        assert result == [{"role": "system", "content": "Be helpful."}]

    def test_human_message(self):
        """Verify HumanMessage maps to user role."""
        result = _messages_to_openai([HumanMessage(content="Hello")])
        assert result == [{"role": "user", "content": "Hello"}]

    def test_ai_message(self):
        """Verify AIMessage maps to assistant role."""
        result = _messages_to_openai([AIMessage(content="Hi there")])
        assert result == [{"role": "assistant", "content": "Hi there"}]

    def test_ai_message_empty_content(self):
        """Verify AIMessage with None content becomes empty string."""
        result = _messages_to_openai([AIMessage(content="")])
        assert result[0]["content"] == ""

    def test_tool_message(self):
        """Verify ToolMessage maps to tool role."""
        result = _messages_to_openai([ToolMessage(content="Sunny", tool_call_id="call_1")])
        assert result == [{"role": "tool", "tool_call_id": "call_1", "content": "Sunny"}]

    def test_ai_with_tool_calls(self):
        """Verify AIMessage with tool_calls includes serialized tool_calls."""
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}}],
        )
        result = _messages_to_openai([msg])
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert len(result[0]["tool_calls"]) == 1
        tc = result[0]["tool_calls"][0]
        assert tc["id"] == "call_1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_weather"
        assert json.loads(tc["function"]["arguments"]) == {"city": "Paris"}

    def test_ai_with_dict_args_serialized(self):
        """Verify tool_calls with dict args are serialized to JSON string."""
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "f", "args": {"x": 1}}],
        )
        result = _messages_to_openai([msg])
        assert json.loads(result[0]["tool_calls"][0]["function"]["arguments"]) == {"x": 1}

    def test_full_tool_calling_conversation(self):
        """Realistic multi-turn tool calling conversation."""
        messages = [
            HumanMessage(content="What's the weather?"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}}],
            ),
            ToolMessage(content="Sunny, 22C", tool_call_id="call_1"),
            AIMessage(content="It's sunny and 22C in Paris."),
        ]
        result = _messages_to_openai(messages)
        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[1]["tool_calls"][0]["id"] == "call_1"
        assert result[2]["role"] == "tool"
        assert result[3]["role"] == "assistant"


# ---------------------------------------------------------------------------
# TestParseToolCalls
# ---------------------------------------------------------------------------


class TestParseToolCalls:
    """Tests for _parse_tool_calls."""

    def test_empty_input(self):
        """Verify empty/None returns empty list."""
        assert not _parse_tool_calls(None)
        assert not _parse_tool_calls([])

    def test_object_style(self):
        """Verify object-style tool calls (with attributes)."""
        tc = MagicMock()
        tc.function.name = "get_weather"
        tc.function.arguments = '{"city": "Paris"}'
        tc.id = "call_1"

        result = _parse_tool_calls([tc])
        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert result[0]["args"] == {"city": "Paris"}
        assert result[0]["id"] == "call_1"

    def test_dict_style(self):
        """Verify dict-style tool calls."""
        tc = {"function": {"name": "search", "arguments": '{"q": "test"}'}, "id": "call_2"}
        result = _parse_tool_calls([tc])
        assert result[0]["name"] == "search"
        assert result[0]["args"] == {"q": "test"}

    def test_malformed_args(self):
        """Verify malformed JSON args returns empty dict."""
        tc = MagicMock()
        tc.function.name = "f"
        tc.function.arguments = "not json"
        tc.id = "call_1"
        result = _parse_tool_calls([tc])
        assert result[0]["args"] == {}


# ---------------------------------------------------------------------------
# TestBuildKwargs
# ---------------------------------------------------------------------------


class TestBuildKwargs:
    """Tests for _build_kwargs."""

    def test_model_passthrough(self):
        """Verify model is passed to kwargs."""
        llm = ChatLiteLLMBridge(model="openai/gpt-4o")
        kwargs = llm._build_kwargs([HumanMessage(content="hi")], None)
        assert kwargs["model"] == "openai/gpt-4o"
        assert kwargs["drop_params"] is True

    def test_api_key_and_base_passthrough(self):
        """Verify api_key and api_base are passed through."""
        llm = ChatLiteLLMBridge(model="m", api_key="sk-test", api_base="https://api.example.com")
        kwargs = llm._build_kwargs([HumanMessage(content="hi")], None)
        assert kwargs["api_key"] == "sk-test"
        assert kwargs.get("base_url") == "https://api.example.com"

    def test_stop_passthrough(self):
        """Verify stop sequences are passed through."""
        llm = ChatLiteLLMBridge(model="m")
        kwargs = llm._build_kwargs([HumanMessage(content="hi")], ["STOP"])
        assert kwargs["stop"] == ["STOP"]

    def test_tools_passthrough(self):
        """Verify tools from kwargs are passed through."""
        llm = ChatLiteLLMBridge(model="m")
        tools = [{"type": "function", "function": {"name": "f"}}]
        kwargs = llm._build_kwargs([HumanMessage(content="hi")], None, tools=tools)
        assert kwargs["tools"] == tools

    def test_tool_choice_passthrough(self):
        """Verify tool_choice from kwargs is passed through."""
        llm = ChatLiteLLMBridge(model="m")
        kwargs = llm._build_kwargs([HumanMessage(content="hi")], None, tool_choice="auto")
        assert kwargs["tool_choice"] == "auto"

    def test_optional_params_omitted_when_none(self):
        """Verify optional params are omitted when None."""
        llm = ChatLiteLLMBridge(model="m")
        kwargs = llm._build_kwargs([HumanMessage(content="hi")], None)
        assert "api_key" not in kwargs
        assert "api_base" not in kwargs
        assert "max_tokens" not in kwargs
        assert "stop" not in kwargs

    def test_max_tokens_and_penalties(self):
        """Verify max_tokens and penalty params are included."""
        llm = ChatLiteLLMBridge(model="m", max_tokens=100, frequency_penalty=0.5, presence_penalty=0.3)
        kwargs = llm._build_kwargs([HumanMessage(content="hi")], None)
        assert kwargs["max_tokens"] == 100
        assert kwargs["frequency_penalty"] == 0.5
        assert kwargs["presence_penalty"] == 0.3


# ---------------------------------------------------------------------------
# TestGenerate
# ---------------------------------------------------------------------------


class TestGenerate:
    """Tests for sync _generate."""

    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.completion")
    def test_generate_calls_completion(self, mock_completion):
        """Verify _generate calls litellm.completion and parses response."""
        mock_completion.return_value = mock_litellm_response(content="Hello world", usage=make_usage())
        llm = ChatLiteLLMBridge(model="test/model")
        result = llm._generate([HumanMessage(content="hi")])

        mock_completion.assert_called_once()
        assert result.generations[0].message.content == "Hello world"

    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.completion")
    def test_generate_stores_token_usage(self, mock_completion):
        """Verify token_usage is stored in last_token_usage."""
        mock_completion.return_value = mock_litellm_response(
            content="hi", usage=make_usage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        )
        llm = ChatLiteLLMBridge(model="test/model")
        llm._generate([HumanMessage(content="hi")])

        from server.app.api.v1.schemas.chat import TokenUsage

        assert llm.last_token_usage == TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)

    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.completion")
    def test_generate_with_tool_calls(self, mock_completion):
        """Verify tool calls in response are parsed into AIMessage."""
        tc = MagicMock()
        tc.function.name = "get_weather"
        tc.function.arguments = '{"city": "Paris"}'
        tc.id = "call_1"
        mock_completion.return_value = mock_litellm_response(content="", tool_calls=[tc])

        llm = ChatLiteLLMBridge(model="test/model")
        result = llm._generate([HumanMessage(content="hi")])

        msg = result.generations[0].message
        assert isinstance(msg, AIMessage)
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "get_weather"


# ---------------------------------------------------------------------------
# TestAGenerate
# ---------------------------------------------------------------------------


class TestAGenerate:
    """Tests for async _agenerate."""

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
    async def test_agenerate_calls_acompletion(self, mock_acompletion):
        """Verify _agenerate calls litellm.acompletion."""
        mock_acompletion.return_value = mock_litellm_response(content="async hello", usage=make_usage())
        llm = ChatLiteLLMBridge(model="test/model")
        result = await llm._agenerate([HumanMessage(content="hi")])

        mock_acompletion.assert_awaited_once()
        assert result.generations[0].message.content == "async hello"

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
    async def test_agenerate_with_tool_calls(self, mock_acompletion):
        """Verify tool calls in async response."""
        tc = MagicMock()
        tc.function.name = "search"
        tc.function.arguments = '{"q": "test"}'
        tc.id = "call_2"
        mock_acompletion.return_value = mock_litellm_response(content="", tool_calls=[tc])

        llm = ChatLiteLLMBridge(model="test/model")
        result = await llm._agenerate([HumanMessage(content="hi")])

        msg = result.generations[0].message
        assert isinstance(msg, AIMessage)
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "search"


# ---------------------------------------------------------------------------
# TestExtractUsage
# ---------------------------------------------------------------------------


class TestExtractUsage:
    """Tests for _extract_usage."""

    def test_extract_usage(self):
        """Verify usage extraction from response."""
        from server.app.api.v1.schemas.chat import TokenUsage

        llm = ChatLiteLLMBridge(model="m")
        resp = mock_litellm_response(usage=make_usage(10, 5, 15))
        usage = llm._extract_usage(resp)
        assert usage == TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    def test_none_usage(self):
        """Verify None usage returns None."""
        llm = ChatLiteLLMBridge(model="m")
        resp = mock_litellm_response()
        resp.usage = None
        assert llm._extract_usage(resp) is None

    def test_zero_total_tokens_fallback(self):
        """Verify total_tokens falls back to prompt+completion when 0."""
        llm = ChatLiteLLMBridge(model="m")
        resp = mock_litellm_response(usage=make_usage(10, 5, 0))
        usage = llm._extract_usage(resp)
        assert usage is not None
        assert usage.total_tokens == 15


# ---------------------------------------------------------------------------
# TestStream
# ---------------------------------------------------------------------------


class TestStream:
    """Tests for sync _stream."""

    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.completion")
    def test_stream_yields_chunks(self, mock_completion):
        """Verify _stream yields ChatGenerationChunk."""
        chunks = [
            make_stream_chunk(content="Hello"),
            make_stream_chunk(content=" world"),
        ]
        mock_completion.return_value = iter(chunks)

        llm = ChatLiteLLMBridge(model="test/model")
        results = list(llm._stream([HumanMessage(content="hi")]))

        assert len(results) == 2
        assert results[0].message.content == "Hello"
        assert results[1].message.content == " world"

    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.completion")
    def test_stream_sets_stream_flag(self, mock_completion):
        """Verify stream=True is set in kwargs."""
        mock_completion.return_value = iter([])
        llm = ChatLiteLLMBridge(model="test/model")
        list(llm._stream([HumanMessage(content="hi")]))

        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["stream"] is True


# ---------------------------------------------------------------------------
# TestAStream
# ---------------------------------------------------------------------------


class TestAStream:
    """Tests for async _astream."""

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
    async def test_astream_yields_chunks(self, mock_acompletion):
        """Verify _astream yields ChatGenerationChunk."""
        chunks = [
            make_stream_chunk(content="async "),
            make_stream_chunk(content="stream"),
        ]
        mock_acompletion.return_value = async_iter(chunks)

        llm = ChatLiteLLMBridge(model="test/model")
        results = []
        async for chunk in llm._astream([HumanMessage(content="hi")]):
            results.append(chunk)

        assert len(results) == 2
        assert results[0].message.content == "async "
        assert results[1].message.content == "stream"

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
    async def test_astream_accumulates_usage(self, mock_acompletion):
        """Verify token usage is accumulated from stream chunks."""
        chunks = [
            make_stream_chunk(content="hi"),
            make_usage_chunk(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        ]
        mock_acompletion.return_value = async_iter(chunks)

        llm = ChatLiteLLMBridge(model="test/model")
        async for _ in llm._astream([HumanMessage(content="hi")]):
            pass

        assert llm.last_token_usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
    async def test_astream_no_usage_when_zero(self, mock_acompletion):
        """Verify last_token_usage stays None when no usage in chunks."""
        chunks = [make_stream_chunk(content="hi")]
        mock_acompletion.return_value = async_iter(chunks)

        llm = ChatLiteLLMBridge(model="test/model")
        llm.last_token_usage = None
        async for _ in llm._astream([HumanMessage(content="hi")]):
            pass

        assert llm.last_token_usage is None


# ---------------------------------------------------------------------------
# TestBindTools
# ---------------------------------------------------------------------------


class TestBindTools:
    """Tests for bind_tools."""

    def test_bind_tools_returns_runnable_binding(self):
        """Verify bind_tools returns a RunnableBinding with tools in kwargs."""
        from langchain_core.runnables import RunnableBinding

        llm = ChatLiteLLMBridge(model="test/model")
        tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
        bound = llm.bind_tools(tools)
        assert isinstance(bound, RunnableBinding)
        assert "tools" in bound.kwargs

    def test_bind_tools_converts_pydantic_model(self):
        """Verify Pydantic model is converted to OpenAI tool format."""
        from langchain_core.runnables import RunnableBinding
        from pydantic import BaseModel, Field

        class GetWeather(BaseModel):
            """Get weather for a city."""

            city: str = Field(description="City name")

        llm = ChatLiteLLMBridge(model="test/model")
        bound = cast(RunnableBinding, llm.bind_tools([GetWeather]))
        tool = bound.kwargs["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "GetWeather"

    def test_bind_tools_true_tool_choice_becomes_required(self):
        """Verify bool tool_choice=True becomes 'required'."""
        from langchain_core.runnables import RunnableBinding

        llm = ChatLiteLLMBridge(model="test/model")
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
        bound = cast(RunnableBinding, llm.bind_tools(tools, tool_choice=True))
        assert bound.kwargs["tool_choice"] == "required"

    def test_bind_tools_false_tool_choice_becomes_none(self):
        """Verify bool tool_choice=False becomes 'none' (disables tools)."""
        from langchain_core.runnables import RunnableBinding

        llm = ChatLiteLLMBridge(model="test/model")
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
        bound = cast(RunnableBinding, llm.bind_tools(tools, tool_choice=False))
        assert bound.kwargs["tool_choice"] == "none"

    def test_bind_tools_string_tool_choice_passthrough(self):
        """Verify string tool_choice passes through unchanged."""
        from langchain_core.runnables import RunnableBinding

        llm = ChatLiteLLMBridge(model="test/model")
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
        bound = cast(RunnableBinding, llm.bind_tools(tools, tool_choice="auto"))
        assert bound.kwargs["tool_choice"] == "auto"

    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.completion")
    def test_bound_tools_passed_to_litellm(self, mock_completion):
        """Verify bound tools are passed through to litellm.completion."""
        mock_completion.return_value = mock_litellm_response(content="ok", usage=make_usage())
        llm = ChatLiteLLMBridge(model="test/model")
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
        bound = llm.bind_tools(tools, tool_choice="auto")
        bound.invoke([HumanMessage(content="hi")])

        call_kwargs = mock_completion.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tool_choice"] == "auto"

    @pytest.mark.anyio
    @patch("server.app.runtime.langgraph.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
    async def test_bound_tools_passed_to_litellm_async(self, mock_acompletion):
        """Verify bound tools are passed through to litellm.acompletion."""
        mock_acompletion.return_value = mock_litellm_response(content="ok", usage=make_usage())
        llm = ChatLiteLLMBridge(model="test/model")
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
        bound = llm.bind_tools(tools, tool_choice="auto")
        await bound.ainvoke([HumanMessage(content="hi")])

        call_kwargs = mock_acompletion.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tool_choice"] == "auto"
