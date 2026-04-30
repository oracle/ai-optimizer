"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for LangGraph streaming adapter (context-var approach).
"""
# spell-checker: disable

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage

from server.app.runtime.langgraph.adapters.litellm import (
    ChatLiteLLMBridge,
    _streaming_ctx,
)
from server.app.runtime.langgraph.adapters.streaming import streaming_context
from server.tests.runtime.langgraph.helpers import make_usage
from server.tests.runtime.shared_helpers import (
    async_iter,
    drain_queue,
    make_empty_choice_usage_chunk,
    make_stream_chunk,
)


def _make_bridge():
    """Build a ChatLiteLLMBridge for testing."""
    return ChatLiteLLMBridge(model="test/model", api_key="key", api_base="http://localhost")


def _content_chunks(*texts):
    """Build a list of mock stream chunks with content."""
    return [make_stream_chunk(content=t) for t in texts]


def _tool_call_delta(index=0, tc_id=None, name=None, arguments=None):
    """Build a mock tool call delta."""
    delta = MagicMock()
    delta.index = index
    delta.id = tc_id
    func = MagicMock()
    func.name = name
    func.arguments = arguments
    delta.function = func
    return delta


# ---------------------------------------------------------------------------
# TestStreamingContext
# ---------------------------------------------------------------------------


class TestStreamingContext:
    """Tests for the streaming_context context manager."""

    @pytest.mark.anyio
    async def test_sets_and_clears_context_var(self):
        """Verify context var is set inside and cleared after."""
        queue = asyncio.Queue()
        assert _streaming_ctx.get(None) is None

        async with streaming_context(queue) as ctx:
            assert _streaming_ctx.get(None) is ctx
            assert ctx["queue"] is queue
            assert ctx["streamed_text"] is False

        assert _streaming_ctx.get(None) is None

    @pytest.mark.anyio
    async def test_clears_on_exception(self):
        """Verify context var is cleared even on exception."""
        queue = asyncio.Queue()
        with pytest.raises(RuntimeError):
            async with streaming_context(queue):
                raise RuntimeError("boom")
        assert _streaming_ctx.get(None) is None

    @pytest.mark.anyio
    async def test_streamed_text_flag_reflects_usage(self):
        """Verify streamed_text can be set within context."""
        queue = asyncio.Queue()
        async with streaming_context(queue) as ctx:
            ctx["streamed_text"] = True
        # After exit, flag was True inside
        assert ctx["streamed_text"] is True


# ---------------------------------------------------------------------------
# TestChatLiteLLMBridgeStreaming (_agenerate with context var)
# ---------------------------------------------------------------------------


class TestChatLiteLLMBridgeStreaming:
    """Tests for ChatLiteLLMBridge._agenerate with streaming context."""

    @pytest.mark.anyio
    async def test_streams_content_to_queue(self):
        """Verify content chunks are pushed to queue."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        chunks = _content_chunks("Hello", " world", "!")
        chunks.append(make_stream_chunk(content="", finish_reason="stop"))

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                await bridge._agenerate([HumanMessage(content="hi")])

        events = drain_queue(queue)
        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 3
        assert stream_events[0]["content"] == "Hello"
        assert stream_events[1]["content"] == " world"
        assert stream_events[2]["content"] == "!"

    @pytest.mark.anyio
    async def test_returns_complete_chat_result(self):
        """Verify ChatResult contains full accumulated content."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        chunks = _content_chunks("Hello", " world")
        chunks.append(make_stream_chunk(content="", finish_reason="stop"))

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                result = await bridge._agenerate([HumanMessage(content="hi")])

        assert len(result.generations) == 1
        assert result.generations[0].message.content == "Hello world"

    @pytest.mark.anyio
    async def test_handles_tool_calls(self):
        """Verify tool call deltas are accumulated correctly."""
        bridge = _make_bridge()
        queue = asyncio.Queue()

        tc1 = _tool_call_delta(index=0, tc_id="call_1", name="my_tool", arguments='{"ar')
        chunk1 = make_stream_chunk(content=None, tool_calls=[tc1])
        tc2 = _tool_call_delta(index=0, tc_id=None, name=None, arguments='g": "val"}')
        chunk2 = make_stream_chunk(content=None, tool_calls=[tc2])
        chunk3 = make_stream_chunk(content="", finish_reason="stop")

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter([chunk1, chunk2, chunk3]))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                result = await bridge._agenerate([HumanMessage(content="use tool")])

        msg = result.generations[0].message
        assert isinstance(msg, AIMessage)
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "my_tool"
        assert msg.tool_calls[0]["args"] == {"arg": "val"}
        assert msg.tool_calls[0]["id"] == "call_1"

        # Tool-only responses should NOT push content to queue
        events = drain_queue(queue)
        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 0

    @pytest.mark.anyio
    async def test_per_call_usage_metadata(self):
        """Each streamed call surfaces its own usage_metadata; cross-call summing is the callback's job."""
        bridge = _make_bridge()
        queue = asyncio.Queue()

        usage1 = make_usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        chunks1 = [
            make_stream_chunk(content="first"),
            make_stream_chunk(content="", finish_reason="stop", usage=usage1),
        ]

        usage2 = make_usage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        chunks2 = [
            make_stream_chunk(content="second"),
            make_stream_chunk(content="", finish_reason="stop", usage=usage2),
        ]

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks1))
                result1 = await bridge._agenerate([HumanMessage(content="call1")])

                mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks2))
                result2 = await bridge._agenerate([HumanMessage(content="call2")])

        msg1, msg2 = result1.generations[0].message, result2.generations[0].message
        assert isinstance(msg1, AIMessage) and isinstance(msg2, AIMessage)
        assert msg1.usage_metadata == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        assert msg2.usage_metadata == {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}

    @pytest.mark.anyio
    async def test_sets_streamed_text_flag(self):
        """Verify streamed_text is True after content is streamed."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        chunks = _content_chunks("text")

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue) as ctx:
                await bridge._agenerate([HumanMessage(content="hi")])

        assert ctx["streamed_text"] is True

    @pytest.mark.anyio
    async def test_streamed_invoke_records_usage_via_callback(self):
        """Streaming path also keys usage by model_name; regression for missing response_metadata."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        usage = make_usage(prompt_tokens=12, completion_tokens=4, total_tokens=16)
        chunks = [
            make_stream_chunk(content="hello"),
            make_stream_chunk(content="", finish_reason="stop", usage=usage),
        ]

        callback = UsageMetadataCallbackHandler()
        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                await bridge.ainvoke([HumanMessage(content="hi")], config={"callbacks": [callback]})

        assert callback.usage_metadata, "streaming call dropped usage — model_name likely missing"
        recorded = callback.usage_metadata.get("test/model")
        assert recorded is not None
        assert recorded["input_tokens"] == 12
        assert recorded["output_tokens"] == 4
        assert recorded["total_tokens"] == 16

    @pytest.mark.anyio
    async def test_agenerate_streaming_handles_empty_choice_usage_chunk(self):
        """Verify the cross-cutting streaming path tolerates terminal ``choices=[]`` usage chunks.

        Without empty-choices handling, ``chunk.choices[0]`` raises IndexError inside
        the streaming loop. The broad ``except`` then triggers the non-streaming
        fallback, issuing a *second* ``litellm.acompletion`` call after content was
        already pushed to the queue — duplicate billing and visible duplication.
        """
        bridge = _make_bridge()
        queue = asyncio.Queue()
        chunks = [
            make_stream_chunk(content="hello"),
            make_empty_choice_usage_chunk(prompt_tokens=8, completion_tokens=4, total_tokens=12),
        ]

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_acompletion = AsyncMock(return_value=async_iter(chunks))
            mock_litellm.acompletion = mock_acompletion
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                result = await bridge._agenerate([HumanMessage(content="hi")])

        # Exactly one provider call — no non-streaming fallback duplicate.
        assert mock_acompletion.await_count == 1
        msg = result.generations[0].message
        assert isinstance(msg, AIMessage)
        assert msg.usage_metadata == {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12}

    @pytest.mark.anyio
    async def test_streamed_text_false_after_tool_only(self):
        """Verify streamed_text stays False when only tool calls are returned."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        tc = _tool_call_delta(index=0, tc_id="call_1", name="tool", arguments="{}")
        chunks = [
            make_stream_chunk(content=None, tool_calls=[tc]),
            make_stream_chunk(content="", finish_reason="stop"),
        ]

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue) as ctx:
                await bridge._agenerate([HumanMessage(content="use tool")])

        assert ctx["streamed_text"] is False

    @pytest.mark.anyio
    async def test_fallback_on_stream_setup_error(self):
        """Verify fallback to non-streaming on acompletion error."""
        bridge = _make_bridge()
        queue = asyncio.Queue()

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            # First call (streaming) fails, second call (non-streaming fallback) succeeds
            from langchain_core.messages import HumanMessage

            non_stream_resp = MagicMock()
            non_stream_resp.choices = [MagicMock()]
            non_stream_resp.choices[0].message.content = "fallback"
            non_stream_resp.choices[0].message.tool_calls = None
            non_stream_resp.usage = None

            mock_litellm.acompletion = AsyncMock(side_effect=[Exception("stream fail"), non_stream_resp])

            async with streaming_context(queue):
                result = await bridge._agenerate([HumanMessage(content="hi")])

        assert result.generations[0].message.content == "fallback"

    @pytest.mark.anyio
    async def test_fallback_on_iteration_error(self):
        """Verify fallback to non-streaming on chunk iteration error."""
        bridge = _make_bridge()
        queue = asyncio.Queue()

        async def failing_iter():
            yield make_stream_chunk(content="partial")
            raise RuntimeError("chunk fail")

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            from langchain_core.messages import HumanMessage

            non_stream_resp = MagicMock()
            non_stream_resp.choices = [MagicMock()]
            non_stream_resp.choices[0].message.content = "recovered"
            non_stream_resp.choices[0].message.tool_calls = None
            non_stream_resp.usage = None

            mock_litellm.acompletion = AsyncMock(side_effect=[failing_iter(), non_stream_resp])

            async with streaming_context(queue):
                result = await bridge._agenerate([HumanMessage(content="hi")])

        assert result.generations[0].message.content == "recovered"

    @pytest.mark.anyio
    async def test_no_streaming_without_context(self):
        """Verify _agenerate uses non-streaming path without context var."""
        bridge = _make_bridge()

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            from langchain_core.messages import HumanMessage

            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "normal"
            resp.choices[0].message.tool_calls = None
            resp.usage = None
            mock_litellm.acompletion = AsyncMock(return_value=resp)

            result = await bridge._agenerate([HumanMessage(content="hi")])

        assert result.generations[0].message.content == "normal"
        # Should NOT have set stream=True
        all_kwargs = mock_litellm.acompletion.call_args
        assert "stream" not in (all_kwargs.kwargs if hasattr(all_kwargs, "kwargs") else {})


# ---------------------------------------------------------------------------
# TestChatLiteLLMBridgeSyncStreaming (_generate with context var)
# ---------------------------------------------------------------------------


class TestChatLiteLLMBridgeSyncStreaming:
    """Tests for ChatLiteLLMBridge._generate with streaming context."""

    @pytest.mark.anyio
    async def test_streams_content_to_queue(self):
        """Verify _generate pushes content chunks to queue via put_nowait."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        chunks = _content_chunks("Hello", " world", "!")
        chunks.append(make_stream_chunk(content="", finish_reason="stop"))

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.completion = MagicMock(return_value=iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                bridge._generate([HumanMessage(content="hi")])

        events = drain_queue(queue)
        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 3
        assert stream_events[0]["content"] == "Hello"
        assert stream_events[1]["content"] == " world"
        assert stream_events[2]["content"] == "!"

    @pytest.mark.anyio
    async def test_returns_complete_chat_result(self):
        """Verify ChatResult contains full accumulated content."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        chunks = _content_chunks("Hello", " world")
        chunks.append(make_stream_chunk(content="", finish_reason="stop"))

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.completion = MagicMock(return_value=iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                result = bridge._generate([HumanMessage(content="hi")])

        assert len(result.generations) == 1
        assert result.generations[0].message.content == "Hello world"

    @pytest.mark.anyio
    async def test_handles_tool_calls(self):
        """Verify tool call deltas are accumulated correctly."""
        bridge = _make_bridge()
        queue = asyncio.Queue()

        tc1 = _tool_call_delta(index=0, tc_id="call_1", name="my_tool", arguments='{"ar')
        chunk1 = make_stream_chunk(content=None, tool_calls=[tc1])
        tc2 = _tool_call_delta(index=0, tc_id=None, name=None, arguments='g": "val"}')
        chunk2 = make_stream_chunk(content=None, tool_calls=[tc2])
        chunk3 = make_stream_chunk(content="", finish_reason="stop")

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.completion = MagicMock(return_value=iter([chunk1, chunk2, chunk3]))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                result = bridge._generate([HumanMessage(content="use tool")])

        msg = result.generations[0].message
        assert isinstance(msg, AIMessage)
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "my_tool"
        assert msg.tool_calls[0]["args"] == {"arg": "val"}
        assert msg.tool_calls[0]["id"] == "call_1"

        events = drain_queue(queue)
        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 0

    @pytest.mark.anyio
    async def test_sets_streamed_text_flag(self):
        """Verify streamed_text is True after content is streamed."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        chunks = _content_chunks("text")

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.completion = MagicMock(return_value=iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue) as ctx:
                bridge._generate([HumanMessage(content="hi")])

        assert ctx["streamed_text"] is True

    @pytest.mark.anyio
    async def test_fallback_on_stream_setup_error(self):
        """Verify fallback to non-streaming on completion error."""
        bridge = _make_bridge()
        queue = asyncio.Queue()

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            from langchain_core.messages import HumanMessage

            non_stream_resp = MagicMock()
            non_stream_resp.choices = [MagicMock()]
            non_stream_resp.choices[0].message.content = "fallback"
            non_stream_resp.choices[0].message.tool_calls = None
            non_stream_resp.usage = None

            mock_litellm.completion = MagicMock(side_effect=[Exception("stream fail"), non_stream_resp])

            async with streaming_context(queue):
                result = bridge._generate([HumanMessage(content="hi")])

        assert result.generations[0].message.content == "fallback"

    @pytest.mark.anyio
    async def test_fallback_on_iteration_error(self):
        """Verify fallback to non-streaming on chunk iteration error."""
        bridge = _make_bridge()
        queue = asyncio.Queue()

        def failing_iter():
            yield make_stream_chunk(content="partial")
            raise RuntimeError("chunk fail")

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            from langchain_core.messages import HumanMessage

            non_stream_resp = MagicMock()
            non_stream_resp.choices = [MagicMock()]
            non_stream_resp.choices[0].message.content = "recovered"
            non_stream_resp.choices[0].message.tool_calls = None
            non_stream_resp.usage = None

            mock_litellm.completion = MagicMock(side_effect=[failing_iter(), non_stream_resp])

            async with streaming_context(queue):
                result = bridge._generate([HumanMessage(content="hi")])

        assert result.generations[0].message.content == "recovered"

    @pytest.mark.anyio
    async def test_no_streaming_without_context(self):
        """Verify _generate uses non-streaming path without context var."""
        bridge = _make_bridge()

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            from langchain_core.messages import HumanMessage

            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "normal"
            resp.choices[0].message.tool_calls = None
            resp.usage = None
            mock_litellm.completion = MagicMock(return_value=resp)

            result = bridge._generate([HumanMessage(content="hi")])

        assert result.generations[0].message.content == "normal"
        all_kwargs = mock_litellm.completion.call_args
        assert "stream" not in (all_kwargs.kwargs if hasattr(all_kwargs, "kwargs") else {})

    @pytest.mark.anyio
    async def test_per_call_usage_metadata(self):
        """Each sync streamed call surfaces its own usage_metadata; cross-call summing is the callback's job."""
        bridge = _make_bridge()
        queue = asyncio.Queue()

        usage1 = make_usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        chunks1 = [
            make_stream_chunk(content="first"),
            make_stream_chunk(content="", finish_reason="stop", usage=usage1),
        ]

        usage2 = make_usage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        chunks2 = [
            make_stream_chunk(content="second"),
            make_stream_chunk(content="", finish_reason="stop", usage=usage2),
        ]

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue):
                mock_litellm.completion = MagicMock(return_value=iter(chunks1))
                result1 = bridge._generate([HumanMessage(content="call1")])

                mock_litellm.completion = MagicMock(return_value=iter(chunks2))
                result2 = bridge._generate([HumanMessage(content="call2")])

        msg1, msg2 = result1.generations[0].message, result2.generations[0].message
        assert isinstance(msg1, AIMessage) and isinstance(msg2, AIMessage)
        assert msg1.usage_metadata == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        assert msg2.usage_metadata == {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}


# ---------------------------------------------------------------------------
# TestChatLiteLLMBridgeAstreamWithContext
# ---------------------------------------------------------------------------


class TestChatLiteLLMBridgeAstreamWithContext:
    """Tests for ChatLiteLLMBridge._astream with streaming context."""

    @pytest.mark.anyio
    async def test_astream_pushes_to_queue_with_context(self):
        """Verify _astream pushes content to queue when context var is set."""
        bridge = _make_bridge()
        queue = asyncio.Queue()
        chunks = _content_chunks("Hello", " world")
        chunks.append(make_stream_chunk(content="", finish_reason="stop"))

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            from langchain_core.messages import HumanMessage

            async with streaming_context(queue) as ctx:
                async for _ in bridge._astream([HumanMessage(content="hi")]):
                    pass

        events = drain_queue(queue)
        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 2
        assert stream_events[0]["content"] == "Hello"
        assert stream_events[1]["content"] == " world"
        assert ctx["streamed_text"] is True

    @pytest.mark.anyio
    async def test_astream_no_queue_push_without_context(self):
        """Verify _astream does NOT push to any queue without context."""
        bridge = _make_bridge()
        chunks = _content_chunks("Hello")
        chunks.append(make_stream_chunk(content="", finish_reason="stop"))

        with patch("server.app.runtime.langgraph.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            from langchain_core.messages import HumanMessage

            yielded = []
            async for gen_chunk in bridge._astream([HumanMessage(content="hi")]):
                yielded.append(gen_chunk)

        # Should still yield chunks normally
        assert len(yielded) == 2
        assert yielded[0].message.content == "Hello"
