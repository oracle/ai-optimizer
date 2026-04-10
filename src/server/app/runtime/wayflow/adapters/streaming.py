"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Streaming adapter for LiteLlmModel.

Wraps LiteLlmModel to push text chunks through an asyncio.Queue during
generation while still returning the full LlmCompletion that WayFlow expects.
"""
# spell-checker: ignore litellm llmmodel requesthelpers subflow subflows vecsearch wayflow wayflowcore

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence

from wayflowcore.flow import Flow as RuntimeFlow
from wayflowcore.messagelist import Message, TextContent
from wayflowcore.models._requesthelpers import StreamChunkType
from wayflowcore.models.llmmodel import LlmCompletion, Prompt
from wayflowcore.steps import FlowExecutionStep, ParallelFlowExecutionStep

from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel

LOGGER = logging.getLogger(__name__)


class StreamingLiteLlmModel(LiteLlmModel):
    """LiteLlmModel that pushes text chunks to a queue during generation.

    Overrides ``_generate_impl`` to use streaming internally so that each
    text chunk is pushed to the provided ``asyncio.Queue`` *and* a full
    ``LlmCompletion`` is returned to satisfy WayFlow's execution contract.

    Parameters
    ----------
    base_model:
        The original LiteLlmModel whose configuration is copied.
    queue:
        An asyncio.Queue where ``{"type": "stream", "content": ...}``
        dicts are placed for each text chunk.
    """

    def __init__(self, base_model: LiteLlmModel, queue: asyncio.Queue) -> None:
        super().__init__(
            provider=base_model.provider,
            model_id=base_model.model_id,
        )
        # Overwrite with full state from the base model
        vars(self).update(vars(base_model))
        self._queue = queue
        self.streamed_text = False

    async def _on_stream_text(self, content: str) -> None:
        """Push each text chunk to the queue for SSE consumption."""
        self.streamed_text = True
        await self._queue.put({"type": "stream", "content": content})

    async def _push_token_usage(self, token_usage) -> None:
        """Push token usage to the queue if available."""
        if token_usage is not None:
            self.last_token_usage = token_usage
            await self._queue.put(
                {
                    "type": "_token_usage",
                    "prompt_tokens": token_usage.input_tokens,
                    "completion_tokens": token_usage.output_tokens,
                    "total_tokens": token_usage.total_tokens,
                }
            )

    async def _stream_generate_impl(self, prompt: Prompt):
        """Wrap parent streaming to capture and push token usage.

        WayFlow's agent executor calls ``stream_generate_async`` which
        delegates to this method.  The parent yields
        ``(chunk_type, message, token_usage)`` tuples; we forward them
        and push a ``_token_usage`` event to the queue when done.
        """
        token_usage = None
        async for chunk_type, msg, usage in super()._stream_generate_impl(prompt):
            token_usage = usage
            yield chunk_type, msg, usage
        await self._push_token_usage(token_usage)

    async def _generate_impl(self, prompt: Prompt) -> LlmCompletion:
        """Generate using streaming internally, pushing chunks to the queue.

        Delegates to ``_stream_generate_impl`` (which calls
        ``_on_stream_text`` for each chunk and pushes ``_token_usage``)
        and assembles the final ``LlmCompletion`` from the ``END_CHUNK``.
        """
        message = None
        token_usage = None
        async for chunk_type, msg, usage in self._stream_generate_impl(prompt):
            token_usage = usage
            if chunk_type == StreamChunkType.END_CHUNK:
                message = msg
        if message is None:
            message = Message(role="assistant", contents=[TextContent(content="")])
        return LlmCompletion(message=message, token_usage=token_usage)


def _swap_step(
    step: Any,
    queue: asyncio.Queue,
) -> Optional[LiteLlmModel]:
    """Swap a single step's LLM if it's a LiteLlmModel. Returns the original or None."""
    llm = getattr(step, "llm", None)
    if llm is not None and isinstance(llm, LiteLlmModel):
        original = llm
        step.llm = StreamingLiteLlmModel(llm, queue)
        return original
    return None


def _collect_all_step_dicts(
    flow: RuntimeFlow,
    *,
    include_parallel: bool = True,
) -> List[Dict[str, Any]]:
    """Collect step dicts from a flow and all nested subflows (recursive).

    FlowExecutionStep wraps a single subflow; ParallelFlowExecutionStep
    wraps a list.  Both expose their subflow(s) which have their own
    ``.steps`` dict.

    Parameters
    ----------
    include_parallel:
        When *False*, subflows inside ``ParallelFlowExecutionStep`` are
        skipped.  This prevents swapping LLMs on steps that run
        concurrently (e.g. two ``format_answer`` steps inside the
        combined flow's "both" branch), which would interleave chunks
        from multiple sources into the same queue.
    """
    result: List[Dict[str, Any]] = [flow.steps]
    for step in flow.steps.values():
        if isinstance(step, FlowExecutionStep):
            result.extend(_collect_all_step_dicts(step.flow, include_parallel=include_parallel))
        elif isinstance(step, ParallelFlowExecutionStep) and include_parallel:
            for subflow in step.flows:
                result.extend(_collect_all_step_dicts(subflow, include_parallel=include_parallel))
    return result


def swap_llm_for_streaming(
    flow: RuntimeFlow,
    queue: asyncio.Queue,
    step_names: Sequence[str],
) -> List[tuple[Any, Any]]:
    """Replace LLM models on named steps with streaming variants.

    Searches both top-level steps and steps nested inside subflows
    (``FlowExecutionStep``, ``ParallelFlowExecutionStep``) so that
    streaming works regardless of which branch is taken at runtime.

    Parameters
    ----------
    flow:
        A loaded WayFlow runtime flow.
    queue:
        The asyncio.Queue to push text chunks to.
    step_names:
        Names of steps whose LLM should be swapped.  Matched by name
        across all levels of the flow hierarchy.

    Returns
    -------
    list
        List of ``(step, original_llm)`` tuples for each swapped step,
        allowing per-step restore after streaming completes.
    """
    all_step_dicts = _collect_all_step_dicts(flow, include_parallel=False)
    originals: List[tuple[Any, Any]] = []

    for name in step_names:
        for steps_dict in all_step_dicts:
            step = steps_dict.get(name)
            if step is None:
                continue
            original = _swap_step(step, queue)
            if original is not None:
                originals.append((step, original))

    return originals


# Step names that produce the final user-facing answer, per route.
STREAMING_STEPS: Dict[str, List[str]] = {
    "nl2sql": ["format_answer"],
    "vecsearch": ["format_answer"],
}
