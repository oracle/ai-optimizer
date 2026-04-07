"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the StreamingLiteLlmModel and swap_llm_for_streaming helper.
"""
# spell-checker: disable

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from wayflowcore.flow import Flow as RuntimeFlow
from wayflowcore.messagelist import Message, TextContent
from wayflowcore.models._requesthelpers import StreamChunkType
from wayflowcore.models.llmmodel import LlmCompletion, Prompt
from wayflowcore.steps import FlowExecutionStep, ParallelFlowExecutionStep

from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel
from server.app.runtime.wayflow.adapters.streaming import (
    STREAMING_STEPS,
    StreamingLiteLlmModel,
    swap_llm_for_streaming,
)
from server.app.runtime.wayflow.session import FlowSession
from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS
from server.tests.runtime.shared_helpers import (
    async_iter,
    drain_queue,
    make_stream_chunk,
    make_usage_chunk,
)
from server.tests.runtime.wayflow.helpers import (
    load_test_flow,
    ollama_available,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prompt(text="Hello"):
    """Build a Prompt with a single user message."""
    msg = Message(role="user", contents=[TextContent(content=text)])
    return Prompt(messages=[msg])


# ---------------------------------------------------------------------------
# TestStreamingLiteLlmModel
# ---------------------------------------------------------------------------


class TestStreamingLiteLlmModel:
    """Tests for StreamingLiteLlmModel._generate_impl."""

    async def test_text_chunks_pushed_to_queue(self, litellm_model):
        """Verify text chunks are pushed to queue and full completion returned."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        chunks = [
            make_stream_chunk(content="Hello"),
            make_stream_chunk(content=" world"),
            make_usage_chunk(),
        ]

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            result = await model._generate_impl(_make_prompt())

        assert isinstance(result, LlmCompletion)
        first = result.message.contents[0]
        assert isinstance(first, TextContent) and first.content == "Hello world"

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 2
        assert stream_events[0] == {"type": "stream", "content": "Hello"}
        assert stream_events[1] == {"type": "stream", "content": " world"}

    async def test_token_usage_extracted(self, litellm_model):
        """Verify token usage is extracted from the final chunk."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        chunks = [
            make_stream_chunk(content="Hi"),
            make_usage_chunk(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        ]

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            result = await model._generate_impl(_make_prompt())

        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 20
        assert result.token_usage.output_tokens == 10

        # Verify _token_usage event is pushed to the queue
        usage_events = [e for e in drain_queue(queue) if e["type"] == "_token_usage"]
        assert len(usage_events) == 1
        assert usage_events[0] == {
            "type": "_token_usage",
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        }

    async def test_last_token_usage_set_after_generate(self, litellm_model):
        """Verify last_token_usage is set on the streaming model after _generate_impl."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)
        assert model.last_token_usage is None

        chunks = [
            make_stream_chunk(content="Hi"),
            make_usage_chunk(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        ]

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            await model._generate_impl(_make_prompt())

        assert model.last_token_usage is not None
        assert model.last_token_usage.input_tokens == 20
        assert model.last_token_usage.output_tokens == 10

    async def test_tool_calls_not_pushed_to_queue(self, litellm_model):
        """Verify tool call chunks are accumulated but not pushed to queue."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        tc = MagicMock()
        tc.index = 0
        tc.id = "call_123"
        tc.function = MagicMock()
        tc.function.name = "my_tool"
        tc.function.arguments = '{"x": 1}'

        chunks = [
            make_stream_chunk(tool_calls=[tc]),
            make_usage_chunk(),
        ]

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            result = await model._generate_impl(_make_prompt())

        stream_events = [e for e in drain_queue(queue) if e["type"] == "stream"]
        assert len(stream_events) == 0
        assert result.message.tool_requests is not None
        assert result.message.tool_requests[0].name == "my_tool"

    async def test_empty_content_not_pushed(self, litellm_model):
        """Verify empty content chunks are not pushed to queue."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        chunks = [
            make_stream_chunk(content=""),
            make_stream_chunk(content="data"),
            make_usage_chunk(),
        ]

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            await model._generate_impl(_make_prompt())

        stream_events = [e for e in drain_queue(queue) if e["type"] == "stream"]
        assert len(stream_events) == 1
        assert stream_events[0]["content"] == "data"

    async def test_non_streaming_fallback(self, litellm_model):
        """Verify fallback to non-streaming when provider doesn't support it."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        # Use a plain object (not MagicMock) so isinstance(AsyncIterable) is False
        class FakeResponse:
            """Non-iterable response for fallback testing."""

            def __init__(self):
                msg = MagicMock()
                msg.content = "direct"
                msg.tool_calls = None
                choice = MagicMock()
                choice.message = msg
                self.choices = [choice]
                self.usage = None

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=FakeResponse())
            result = await model._generate_impl(_make_prompt())

        first = result.message.contents[0]
        assert isinstance(first, TextContent) and first.content == "direct"
        assert queue.qsize() == 1
        event = queue.get_nowait()
        assert event == {"type": "stream", "content": "direct"}


# ---------------------------------------------------------------------------
# TestStreamGenerateImpl — WayFlow's streaming path
# ---------------------------------------------------------------------------


class TestStreamGenerateImpl:
    """Tests for StreamingLiteLlmModel._stream_generate_impl."""

    async def test_yields_tuples_and_pushes_to_queue(self, litellm_model):
        """Verify TEXT_CHUNK/END_CHUNK tuples yielded and chunks pushed to queue."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        chunks = [
            make_stream_chunk(content="Hello"),
            make_stream_chunk(content=" world"),
            make_stream_chunk(content="", finish_reason="stop"),
        ]

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            yielded = []
            async for item in model._stream_generate_impl(_make_prompt()):
                yielded.append(item)

        # Should yield START_CHUNK + TEXT_CHUNKs + END_CHUNK at finish
        assert len(yielded) == 4
        assert yielded[0][0] == StreamChunkType.START_CHUNK
        assert yielded[1][0] == StreamChunkType.TEXT_CHUNK
        assert yielded[1][1].contents[0].content == "Hello"
        assert yielded[2][0] == StreamChunkType.TEXT_CHUNK
        assert yielded[2][1].contents[0].content == " world"
        assert yielded[3][0] == StreamChunkType.END_CHUNK
        assert yielded[3][1].contents[0].content == "Hello world"

        # Queue should also have the chunks
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert len(events) == 2
        assert events[0] == {"type": "stream", "content": "Hello"}
        assert events[1] == {"type": "stream", "content": " world"}

    async def test_tool_calls_not_pushed_to_queue(self, litellm_model):
        """Verify tool calls yield END_CHUNK but are not pushed to queue."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        tc = MagicMock()
        tc.index = 0
        tc.id = "call_456"
        tc.function = MagicMock()
        tc.function.name = "my_tool"
        tc.function.arguments = '{"x": 1}'

        chunks = [
            make_stream_chunk(tool_calls=[tc]),
            make_stream_chunk(content="", finish_reason="stop"),
        ]

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=async_iter(chunks))
            yielded = []
            async for item in model._stream_generate_impl(_make_prompt()):
                yielded.append(item)

        assert queue.empty()
        # Should still yield END_CHUNK with tool requests
        end_chunks = [y for y in yielded if y[0] == StreamChunkType.END_CHUNK]
        assert len(end_chunks) == 1
        assert end_chunks[0][1].tool_requests[0].name == "my_tool"

    async def test_non_streaming_fallback(self, litellm_model):
        """Verify fallback enqueues text and yields tuples for non-streaming providers."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        class FakeResponse:
            """Non-iterable response for fallback testing."""

            def __init__(self):
                msg = MagicMock()
                msg.content = "fallback answer"
                msg.tool_calls = None
                choice = MagicMock()
                choice.message = msg
                self.choices = [choice]
                self.usage = None

        with patch("server.app.runtime.wayflow.adapters.litellm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=FakeResponse())
            yielded = []
            async for item in model._stream_generate_impl(_make_prompt()):
                yielded.append(item)

        # Should yield START_CHUNK + TEXT_CHUNK + END_CHUNK
        assert len(yielded) == 3
        assert yielded[0][0] == StreamChunkType.START_CHUNK
        assert yielded[1][0] == StreamChunkType.TEXT_CHUNK
        assert yielded[1][1].contents[0].content == "fallback answer"
        assert yielded[2][0] == StreamChunkType.END_CHUNK

        # Queue should have the full text as a single chunk
        assert queue.qsize() == 1
        event = queue.get_nowait()
        assert event == {"type": "stream", "content": "fallback answer"}


# ---------------------------------------------------------------------------
# TestSwapLlm
# ---------------------------------------------------------------------------


class TestSwapLlm:
    """Tests for swap_llm_for_streaming."""

    def test_replaces_matching_steps(self, litellm_model):
        """Verify matching steps get their LLM swapped to streaming variant."""
        queue: asyncio.Queue = asyncio.Queue()

        step = MagicMock()
        step.llm = litellm_model

        flow = MagicMock()
        flow.steps = {"format_answer": step}

        originals = swap_llm_for_streaming(flow, queue, ["format_answer"])

        assert len(originals) == 1
        assert originals[0] == (step, litellm_model)
        assert isinstance(step.llm, StreamingLiteLlmModel)

    def test_skips_missing_steps(self):
        """Verify nonexistent step names are silently skipped."""
        queue: asyncio.Queue = asyncio.Queue()
        flow = MagicMock()
        flow.steps = {}

        originals = swap_llm_for_streaming(flow, queue, ["nonexistent"])

        assert not originals

    def test_skips_non_litellm_models(self):
        """Verify steps with non-LiteLlmModel LLMs are skipped."""
        queue: asyncio.Queue = asyncio.Queue()

        step = MagicMock()
        step.llm = MagicMock()  # not a LiteLlmModel

        flow = MagicMock()
        flow.steps = {"format_answer": step}

        originals = swap_llm_for_streaming(flow, queue, ["format_answer"])

        assert not originals

    def test_streaming_steps_mapping(self):
        """Verify STREAMING_STEPS contains correct route-to-step mappings."""
        assert "nl2sql" in STREAMING_STEPS
        assert "vecsearch" in STREAMING_STEPS
        assert "combined" not in STREAMING_STEPS  # combined uses Python-level routing
        assert STREAMING_STEPS["nl2sql"] == ["format_answer"]
        assert STREAMING_STEPS["vecsearch"] == ["format_answer"]

    def test_recurses_into_subflows(self, litellm_model):
        """Verify swap recurses into FlowExecutionStep subflows."""
        queue: asyncio.Queue = asyncio.Queue()

        # Build a subflow with a format_answer step
        inner_step = MagicMock()
        inner_step.llm = litellm_model
        inner_flow = MagicMock(spec=RuntimeFlow)
        inner_flow.steps = {"format_answer": inner_step}

        # Wrap it in a FlowExecutionStep
        flow_exec_step = MagicMock(spec=FlowExecutionStep)
        flow_exec_step.flow = inner_flow

        # Top-level flow contains the FlowExecutionStep
        outer_flow = MagicMock(spec=RuntimeFlow)
        outer_flow.steps = {"nl2sql_subflow": flow_exec_step}

        originals = swap_llm_for_streaming(outer_flow, queue, ["format_answer"])

        assert len(originals) == 1
        assert originals[0] == (inner_step, litellm_model)
        assert isinstance(inner_step.llm, StreamingLiteLlmModel)

    def test_skips_parallel_subflows(self, litellm_model):
        """Verify swap skips ParallelFlowExecutionStep to avoid interleaved chunks."""
        queue: asyncio.Queue = asyncio.Queue()

        # Two parallel subflows, each with format_answer
        inner_step_1 = MagicMock()
        inner_step_1.llm = litellm_model
        subflow_1 = MagicMock(spec=RuntimeFlow)
        subflow_1.steps = {"format_answer": inner_step_1}

        inner_step_2 = MagicMock()
        inner_step_2.llm = litellm_model
        subflow_2 = MagicMock(spec=RuntimeFlow)
        subflow_2.steps = {"format_answer": inner_step_2}

        parallel_step = MagicMock(spec=ParallelFlowExecutionStep)
        parallel_step.flows = [subflow_1, subflow_2]

        outer_flow = MagicMock(spec=RuntimeFlow)
        outer_flow.steps = {"both_subflows": parallel_step}

        originals = swap_llm_for_streaming(outer_flow, queue, ["format_answer"])

        # Parallel subflows should NOT be swapped to avoid interleaved chunks
        assert not originals
        assert not isinstance(inner_step_1.llm, StreamingLiteLlmModel)
        assert not isinstance(inner_step_2.llm, StreamingLiteLlmModel)

    def test_duplicate_step_names_all_recorded(self):
        """Both originals recorded when same step name appears in two subflows."""
        queue: asyncio.Queue = asyncio.Queue()

        llm_a = LiteLlmModel(provider="ollama", model_id="model-a", api_base="http://localhost:11434")
        llm_b = LiteLlmModel(provider="ollama", model_id="model-b", api_base="http://localhost:11434")

        step_a = MagicMock()
        step_a.llm = llm_a
        subflow_a = MagicMock(spec=RuntimeFlow)
        subflow_a.steps = {"format_answer": step_a}

        step_b = MagicMock()
        step_b.llm = llm_b
        subflow_b = MagicMock(spec=RuntimeFlow)
        subflow_b.steps = {"format_answer": step_b}

        exec_a = MagicMock(spec=FlowExecutionStep)
        exec_a.flow = subflow_a
        exec_b = MagicMock(spec=FlowExecutionStep)
        exec_b.flow = subflow_b

        outer = MagicMock(spec=RuntimeFlow)
        outer.steps = {"branch_a": exec_a, "branch_b": exec_b}

        originals = swap_llm_for_streaming(outer, queue, ["format_answer"])

        # Both steps should be swapped
        assert isinstance(step_a.llm, StreamingLiteLlmModel)
        assert isinstance(step_b.llm, StreamingLiteLlmModel)

        # Both originals must be recorded (list of tuples, not dict)
        assert len(originals) == 2
        original_llms = [orig for _, orig in originals]
        assert llm_a in original_llms
        assert llm_b in original_llms

    def test_combined_no_longer_in_streaming_steps(self):
        """Verify combined route is not in STREAMING_STEPS (uses Python-level routing)."""
        assert "combined" not in STREAMING_STEPS


# ---------------------------------------------------------------------------
# Integration tests (require running ollama)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not ollama_available(), reason="ollama not running at 127.0.0.1:11434")
class TestStreamingLiteLlmModelIntegration:
    """Integration tests requiring a running ollama instance."""

    async def test_streaming_model_pushes_chunks_to_queue(self, litellm_model):
        """Verify streaming model pushes chunks and assembles full text."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        prompt = _make_prompt("What is 2+2? Reply with just the number.")
        result = await model._generate_impl(prompt)

        # Should have a valid completion
        assert result.message is not None
        assert result.message.contents
        first_content = result.message.contents[0]
        assert isinstance(first_content, TextContent)
        full_text = first_content.content
        assert full_text

        # Should have pushed chunks to the queue (filter out _token_usage events)
        all_events = []
        while not queue.empty():
            all_events.append(queue.get_nowait())
        chunks = [c for c in all_events if c["type"] == "stream"]

        assert len(chunks) >= 1

        # Chunks should assemble to the full text
        assembled = "".join(c["content"] for c in chunks)
        assert assembled == full_text

    async def test_streaming_model_captures_token_usage(self, litellm_model):
        """Verify token usage is captured when provider supports it."""
        queue: asyncio.Queue = asyncio.Queue()
        model = StreamingLiteLlmModel(litellm_model, queue)

        prompt = _make_prompt("Say hello.")
        result = await model._generate_impl(prompt)

        # Not all providers (e.g. Ollama) return usage in streaming mode
        if result.token_usage is not None:
            assert result.token_usage.input_tokens > 0
            assert result.token_usage.output_tokens > 0

    async def test_flow_with_swapped_llm_streams_to_queue(self):
        """Verify a real flow with swapped LLM pushes chunks to queue."""
        flow = load_test_flow(llm_node_name="format_answer")
        queue: asyncio.Queue = asyncio.Queue()

        swap_llm_for_streaming(flow, queue, ["format_answer"])

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        answer = await session.execute("What is 2+2?", "test-thread")

        # Session should return an answer
        assert answer
        assert len(answer) > 0

        # Queue should have received streaming chunks (filter out _token_usage events)
        all_events = []
        while not queue.empty():
            all_events.append(queue.get_nowait())
        chunks = [c for c in all_events if c["type"] == "stream"]

        assert len(chunks) >= 1
        assembled = "".join(c["content"] for c in chunks)
        assert len(assembled) > 0
