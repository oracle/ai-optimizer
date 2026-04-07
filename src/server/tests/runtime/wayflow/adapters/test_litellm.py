"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LiteLlmModel WayFlow runtime adapter.
"""
# spell-checker: disable

from typing import Any, Dict, cast
from unittest.mock import MagicMock

from wayflowcore.messagelist import Message, MessageType, TextContent
from wayflowcore.models import LlmGenerationConfig, LlmModelFactory
from wayflowcore.tools import ServerTool
from wayflowcore.tools.tools import ToolRequest, ToolResult

from server.app.runtime.wayflow.adapters.litellm import (
    LiteLlmModel,
    _build_litellm_messages,
    _build_litellm_tools,
)


def _make_litellm_response(content="", tool_calls=None, prompt_tokens=10, completion_tokens=5):
    """Create a mock LiteLLM completion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = tool_calls
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens
    resp.usage = usage
    return resp


def _make_tool_call(name="get_weather", arguments='{"city": "Paris"}', tc_id="call_1"):
    """Create a mock tool call object with function name, arguments, and id."""
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    tc.id = tc_id
    return tc


# ---------------------------------------------------------------------------
# Config & Factory
# ---------------------------------------------------------------------------


class TestLiteLlmModelConfig:
    """Unit tests for LiteLlmModel configuration and factory registration."""

    def test_model_string_combines_provider_and_id(self):
        """Verify litellm_model joins provider and model_id with a slash."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        assert model.litellm_model == "openai/gpt-4o"

    def test_model_string_without_provider(self):
        """Verify litellm_model uses only model_id when provider is empty."""
        model = LiteLlmModel(provider="", model_id="gpt-4o")
        assert model.litellm_model == "gpt-4o"

    def test_config_includes_all_fields(self):
        """Verify config dict contains all expected fields when fully populated."""
        model = LiteLlmModel(
            provider="ollama",
            model_id="qwen3:8b",
            api_key="sk-test",
            api_base="http://localhost:11434",
            generation_config=LlmGenerationConfig.from_dict({"max_tokens": 50}),
        )
        config = model.config
        assert config["model_type"] == "litellm"
        assert config["provider"] == "ollama"
        assert config["model_id"] == "qwen3:8b"
        assert config["api_key"] == "sk-test"
        assert config["api_base"] == "http://localhost:11434"
        assert config["generation_config"]["max_tokens"] == 50
        assert config["supports_structured_generation"] is True
        assert config["supports_tool_calling"] is True

    def test_config_none_fields(self):
        """Verify optional config fields are None when not provided."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        config = model.config
        assert config["api_key"] is None
        assert config["api_base"] is None
        assert config["generation_config"] is None

    def test_factory_roundtrip_preserves_all_fields(self):
        """Verify config export and factory import preserve all model fields."""
        gen_config = LlmGenerationConfig.from_dict({"max_tokens": 100, "temperature": 0.5, "frequency_penalty": 0.7})
        original = LiteLlmModel(
            provider="openai",
            model_id="gpt-4o",
            api_key="sk-test",
            api_base="http://localhost:8000",
            generation_config=gen_config,
        )
        restored = LlmModelFactory.from_config(original.config)
        assert isinstance(restored, LiteLlmModel)
        assert restored.litellm_model == "openai/gpt-4o"
        assert restored.provider == "openai"
        assert restored.api_key == "sk-test"
        assert restored.api_base == "http://localhost:8000"
        assert restored.generation_config is not None
        gen_dict = restored.generation_config.to_dict()
        assert gen_dict["max_tokens"] == 100
        assert gen_dict["temperature"] == 0.5
        assert gen_dict["frequency_penalty"] == 0.7

    def test_extra_kwargs_roundtrip(self):
        """Verify extra_kwargs survive config export and factory import."""
        original = LiteLlmModel(
            provider="openai",
            model_id="gpt-4o",
            extra_kwargs={"seed": 42, "top_k": 10, "custom_header": "x-test"},
        )
        config = original.config
        assert config["extra_kwargs"] == {"seed": 42, "top_k": 10, "custom_header": "x-test"}

        restored = LlmModelFactory.from_config(config)
        assert isinstance(restored, LiteLlmModel)
        assert restored.extra_kwargs == {"seed": 42, "top_k": 10, "custom_header": "x-test"}

    def test_extra_kwargs_empty_roundtrip(self):
        """Verify extra_kwargs defaults to empty dict after roundtrip."""
        original = LiteLlmModel(provider="openai", model_id="gpt-4o")
        config = original.config
        restored = LlmModelFactory.from_config(config)
        assert isinstance(restored, LiteLlmModel)
        assert restored.extra_kwargs == {}

    def test_factory_double_registration_does_not_recurse(self):
        """Calling register_litellm_model_factory() twice must not stack patches."""
        from server.app.runtime.wayflow.adapters.litellm import register_litellm_model_factory

        # Already registered once by conftest; register again
        register_litellm_model_factory()

        # litellm config still works
        litellm_config = LiteLlmModel(provider="openai", model_id="gpt-4o").config
        restored = LlmModelFactory.from_config(litellm_config)
        assert isinstance(restored, LiteLlmModel)

        # non-litellm config still delegates without blowing the stack
        other_config = {
            "model_type": "openaicompatible",
            "model_id": "test-model",
            "base_url": "http://localhost:8000",
        }
        model = LlmModelFactory.from_config(other_config)
        assert model.model_id == "test-model"

    def test_factory_still_handles_other_model_types(self):
        """Verify the factory still delegates non-litellm model types correctly."""
        config = {
            "model_type": "openaicompatible",
            "model_id": "test-model",
            "base_url": "http://localhost:8000",
        }
        model = LlmModelFactory.from_config(config)
        assert model.model_id == "test-model"


# ---------------------------------------------------------------------------
# _build_litellm_messages
# ---------------------------------------------------------------------------


class TestBuildLitellmMessages:
    """Unit tests for _build_litellm_messages."""

    def test_user_message(self):
        """Verify a user message maps to the 'user' role."""
        msg = Message(content="Hello", message_type=MessageType.USER)
        result = _build_litellm_messages([msg])
        assert result == [{"role": "user", "content": "Hello"}]

    def test_assistant_message(self):
        """Verify an agent message maps to the 'assistant' role."""
        msg = Message(content="Hi there", message_type=MessageType.AGENT)
        result = _build_litellm_messages([msg])
        assert result == [{"role": "assistant", "content": "Hi there"}]

    def test_system_message(self):
        """Verify a system message maps to the 'system' role."""
        msg = Message(content="You are helpful.", message_type=MessageType.SYSTEM)
        result = _build_litellm_messages([msg])
        assert result == [{"role": "system", "content": "You are helpful."}]

    def test_message_with_contents_list(self):
        """Verify multiple TextContent items are joined with newlines."""
        msg = Message(
            role="assistant",
            contents=[TextContent(content="Part 1"), TextContent(content=" Part 2")],
        )
        result = _build_litellm_messages([msg])
        assert result[0]["content"] == "Part 1\n Part 2"

    def test_tool_result_message(self):
        """Verify a tool result maps to the 'tool' role with correct tool_call_id."""
        msg = Message(
            message_type=MessageType.TOOL_RESULT,
            tool_result=ToolResult(
                tool_request_id="call_1",
                content="Sunny in Paris",
            ),
        )
        result = _build_litellm_messages([msg])
        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_1"
        assert result[0]["content"] == "Sunny in Paris"

    def test_tool_result_multiple_results(self):
        """Multiple tool results come as separate messages (one ToolResult per Message)."""
        msg1 = Message(
            message_type=MessageType.TOOL_RESULT,
            tool_result=ToolResult(tool_request_id="call_1", content="Result 1"),
        )
        msg2 = Message(
            message_type=MessageType.TOOL_RESULT,
            tool_result=ToolResult(tool_request_id="call_2", content="Result 2"),
        )
        result = _build_litellm_messages([msg1, msg2])
        assert len(result) == 2
        assert result[0]["tool_call_id"] == "call_1"
        assert result[1]["tool_call_id"] == "call_2"

    def test_tool_request_with_text_content(self):
        """Verify tool requests include accompanying text content when present."""
        msg = Message(
            role="assistant",
            tool_requests=[ToolRequest(name="get_weather", args={"city": "Paris"}, tool_request_id="call_1")],
            contents=[TextContent(content="Let me check.")],
        )
        result = _build_litellm_messages([msg])
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Let me check."
        assert result[0]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert result[0]["tool_calls"][0]["id"] == "call_1"

    def test_tool_request_without_text_content(self):
        """Verify tool requests omit the content key when no text is present."""
        msg = Message(
            role="assistant",
            tool_requests=[ToolRequest(name="get_weather", args={"city": "Paris"}, tool_request_id="call_1")],
        )
        result = _build_litellm_messages([msg])
        assert "content" not in result[0]
        assert result[0]["tool_calls"][0]["function"]["name"] == "get_weather"

    def test_tool_request_arguments_serialized_as_json(self):
        """Verify dict arguments are serialized to a JSON string."""
        msg = Message(
            role="assistant",
            tool_requests=[
                ToolRequest(
                    name="search",
                    args={"query": "test", "limit": 5},
                    tool_request_id="call_1",
                )
            ],
        )
        result = _build_litellm_messages([msg])
        args_str = result[0]["tool_calls"][0]["function"]["arguments"]
        import json

        assert json.loads(args_str) == {"query": "test", "limit": 5}

    def test_tool_request_string_arguments_passed_through(self):
        """Verify string arguments are passed through without re-serialization."""
        msg = Message(
            role="assistant",
            tool_requests=[ToolRequest(name="f", args=cast(Dict[str, Any], "raw string"), tool_request_id="call_1")],
        )
        result = _build_litellm_messages([msg])
        assert result[0]["tool_calls"][0]["function"]["arguments"] == "raw string"

    def test_multiple_tool_requests(self):
        """Verify multiple tool requests are included in a single message."""
        msg = Message(
            role="assistant",
            tool_requests=[
                ToolRequest(name="tool_a", args={}, tool_request_id="call_1"),
                ToolRequest(name="tool_b", args={}, tool_request_id="call_2"),
            ],
        )
        result = _build_litellm_messages([msg])
        assert len(result[0]["tool_calls"]) == 2
        assert result[0]["tool_calls"][0]["function"]["name"] == "tool_a"
        assert result[0]["tool_calls"][1]["function"]["name"] == "tool_b"

    def test_full_tool_calling_conversation(self):
        """Realistic multi-turn: user -> assistant+tool_call -> tool_result -> assistant."""
        messages = [
            Message(content="What's the weather?", message_type=MessageType.USER),
            Message(
                role="assistant",
                tool_requests=[ToolRequest(name="get_weather", args={"city": "Paris"}, tool_request_id="call_1")],
            ),
            Message(
                message_type=MessageType.TOOL_RESULT,
                tool_result=ToolResult(tool_request_id="call_1", content="Sunny, 22C"),
            ),
            Message(content="It's sunny and 22C in Paris.", message_type=MessageType.AGENT),
        ]
        result = _build_litellm_messages(messages)
        assert len(result) == 4
        assert result[0] == {"role": "user", "content": "What's the weather?"}
        assert result[1]["role"] == "assistant"
        assert result[1]["tool_calls"][0]["id"] == "call_1"
        assert result[2] == {"role": "tool", "tool_call_id": "call_1", "content": "Sunny, 22C"}
        assert result[3] == {"role": "assistant", "content": "It's sunny and 22C in Paris."}


# ---------------------------------------------------------------------------
# _build_litellm_tools
# ---------------------------------------------------------------------------


class TestBuildLitellmTools:
    """Unit tests for _build_litellm_tools."""

    def test_none_returns_none(self):
        """Verify None input returns None."""
        assert _build_litellm_tools(None) is None

    def test_empty_list_returns_none(self):
        """Verify empty tool list returns None."""
        assert _build_litellm_tools([]) is None

    def test_server_tool_parameters_used(self):
        """Verify tool parameters are correctly mapped to OpenAI function schema."""
        tool = ServerTool(
            name="get_weather",
            description="Get weather for a city",
            parameters={
                "city": {"type": "string", "description": "The city name"},
                "units": {"type": "string", "description": "Temperature units"},
            },
            output={"type": "string"},
            func=lambda city, units="celsius": f"Sunny in {city}",
        )
        result = _build_litellm_tools([tool])
        assert result is not None
        assert len(result) == 1
        func = result[0]["function"]
        assert func["name"] == "get_weather"
        assert func["description"] == "Get weather for a city"
        params = func["parameters"]
        assert params["type"] == "object"
        assert params["properties"]["city"]["type"] == "string"
        assert params["properties"]["city"]["description"] == "The city name"
        assert params["properties"]["units"]["type"] == "string"

    def test_server_tool_required_params(self):
        """Verify params without defaults are marked required and those with defaults are not."""
        tool = ServerTool(
            name="search",
            description="Search",
            parameters={
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            output={"type": "string"},
            func=lambda query, limit=10: query,
        )
        result = _build_litellm_tools([tool])
        assert result is not None
        params = result[0]["function"]["parameters"]
        assert "query" in params["required"]
        assert "limit" not in params["required"]

    def test_falsy_default_not_marked_required(self):
        """Verify params with falsy defaults (0, False, '') are not marked required."""
        tool = ServerTool(
            name="my_tool",
            description="A tool",
            parameters={
                "count": {"type": "integer", "default": 0},
                "verbose": {"type": "boolean", "default": False},
                "name": {"type": "string", "default": ""},
                "query": {"type": "string"},
            },
            output={"type": "string"},
            func=lambda query, count=0, verbose=False, name="": query,
        )
        result = _build_litellm_tools([tool])
        assert result is not None
        params = result[0]["function"]["parameters"]
        assert params["required"] == ["query"]

    def test_title_stripped_from_parameters(self):
        """Verify the 'title' key is removed from parameter properties."""
        tool = ServerTool(
            name="test",
            description="test",
            parameters={"q": {"type": "string", "title": "Q"}},
            output={"type": "string"},
            func=lambda q: q,
        )
        result = _build_litellm_tools([tool])
        assert result is not None
        assert "title" not in result[0]["function"]["parameters"]["properties"]["q"]

    def test_multiple_tools(self):
        """Verify multiple tools are all included in the output list."""
        tool_a = ServerTool(
            name="tool_a",
            description="A",
            parameters={"x": {"type": "string"}},
            output={"type": "string"},
            func=lambda x: x,
        )
        tool_b = ServerTool(
            name="tool_b",
            description="B",
            parameters={"y": {"type": "integer"}},
            output={"type": "string"},
            func=str,
        )
        result = _build_litellm_tools([tool_a, tool_b])
        assert result is not None
        assert len(result) == 2
        assert result[0]["function"]["name"] == "tool_a"
        assert result[1]["function"]["name"] == "tool_b"
        assert "x" in result[0]["function"]["parameters"]["properties"]
        assert "y" in result[1]["function"]["parameters"]["properties"]

    def test_tool_with_no_parameters(self):
        """Verify a tool with empty parameters produces an empty properties object."""
        tool = ServerTool(
            name="ping",
            description="Ping",
            parameters={},
            output={"type": "string"},
            func=lambda: "pong",
        )
        result = _build_litellm_tools([tool])
        assert result is not None
        assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_output_format_is_openai_function_calling(self):
        """Verify output conforms to OpenAI function-calling tool schema."""
        tool = ServerTool(
            name="f",
            description="d",
            parameters={"a": {"type": "string"}},
            output={"type": "string"},
            func=lambda a: a,
        )
        result = _build_litellm_tools([tool])
        assert result is not None
        assert result[0]["type"] == "function"
        assert "function" in result[0]
        assert "name" in result[0]["function"]
        assert "description" in result[0]["function"]
        assert "parameters" in result[0]["function"]


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Unit tests for _parse_response."""

    def test_plain_text_response(self):
        """Verify a plain text response is parsed into TextContent."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        resp = _make_litellm_response(content="Hello world")
        completion = model._parse_response(resp)
        assert completion.message.contents is not None
        assert isinstance(completion.message.contents[0], TextContent)
        assert completion.message.contents[0].content == "Hello world"
        assert completion.message.role == "assistant"
        assert not completion.message.tool_requests

    def test_empty_text_response(self):
        """Verify an empty string response is still parsed into TextContent."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        resp = _make_litellm_response(content="")
        completion = model._parse_response(resp)
        assert completion.message.contents is not None
        assert isinstance(completion.message.contents[0], TextContent)
        assert completion.message.contents[0].content == ""

    def test_token_usage_extracted(self):
        """Verify token usage is correctly extracted from the response."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        resp = _make_litellm_response(content="Hi", prompt_tokens=15, completion_tokens=8)
        completion = model._parse_response(resp)
        assert completion.token_usage is not None
        assert completion.token_usage.input_tokens == 15
        assert completion.token_usage.output_tokens == 8
        assert completion.token_usage.total_tokens == 23

    def test_no_usage(self):
        """Verify token_usage is None when the response has no usage data."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        resp = _make_litellm_response(content="Hi")
        resp.usage = None
        completion = model._parse_response(resp)
        assert completion.token_usage is None

    def test_tool_call_response(self):
        """Verify a tool call response is parsed into a ToolRequest."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        tc = _make_tool_call(name="get_weather", arguments='{"city": "Paris"}', tc_id="call_1")
        resp = _make_litellm_response(tool_calls=[tc])
        completion = model._parse_response(resp)
        assert completion.message.tool_requests is not None
        assert len(completion.message.tool_requests) == 1
        tr = completion.message.tool_requests[0]
        assert tr.name == "get_weather"
        assert tr.args == {"city": "Paris"}
        assert tr.tool_request_id == "call_1"

    def test_tool_call_preserves_text_content(self):
        """Verify text content is preserved alongside tool calls."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        tc = _make_tool_call()
        resp = _make_litellm_response(content="Let me check.", tool_calls=[tc])
        completion = model._parse_response(resp)
        assert completion.message.tool_requests is not None
        assert completion.message.contents is not None
        assert isinstance(completion.message.contents[0], TextContent)
        assert completion.message.contents[0].content == "Let me check."

    def test_tool_call_without_text_has_no_contents(self):
        """Verify contents is empty when tool call has no accompanying text."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        tc = _make_tool_call()
        resp = _make_litellm_response(content="", tool_calls=[tc])
        completion = model._parse_response(resp)
        assert completion.message.tool_requests is not None
        assert not completion.message.contents

    def test_multiple_tool_calls(self):
        """Verify multiple tool calls are parsed into separate ToolRequests."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        tc1 = _make_tool_call(name="tool_a", arguments='{"x": 1}', tc_id="call_1")
        tc2 = _make_tool_call(name="tool_b", arguments='{"y": 2}', tc_id="call_2")
        resp = _make_litellm_response(tool_calls=[tc1, tc2])
        completion = model._parse_response(resp)
        assert completion.message.tool_requests is not None
        assert len(completion.message.tool_requests) == 2
        assert completion.message.tool_requests[0].name == "tool_a"
        assert completion.message.tool_requests[1].name == "tool_b"

    def test_malformed_json_arguments_returned_as_string(self):
        """Verify malformed JSON arguments are returned as a raw string."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        tc = _make_tool_call(arguments="not json")
        resp = _make_litellm_response(tool_calls=[tc])
        completion = model._parse_response(resp)
        assert completion.message.tool_requests is not None
        assert completion.message.tool_requests[0].args == "not json"

    def test_empty_choices_does_not_crash(self):
        """If the API returns an empty choices list, _parse_response must not IndexError."""
        model = LiteLlmModel(provider="openai", model_id="gpt-4o")
        resp = MagicMock()
        resp.choices = []
        resp.usage = None
        completion = model._parse_response(resp)
        assert completion.message is not None
        assert completion.message.content == ""
