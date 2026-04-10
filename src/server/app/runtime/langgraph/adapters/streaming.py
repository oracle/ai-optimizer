"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Streaming adapter for ChatLiteLLMBridge.

Provides a context-manager that enables streaming on all ChatLiteLLMBridge
calls within the async context, using a task-scoped context variable.
"""
# spell-checker: ignore litellm acompletion langgraph

import asyncio
import contextlib
from typing import AsyncIterator

from server.app.runtime.langgraph.adapters.litellm import _streaming_ctx


@contextlib.asynccontextmanager
async def streaming_context(queue: asyncio.Queue) -> AsyncIterator[dict]:
    """Enable streaming on all ChatLiteLLMBridge calls within this context.

    Sets the ``_streaming_ctx`` context variable so that
    ``ChatLiteLLMBridge._agenerate`` streams internally and pushes content
    chunks to *queue*.  The yielded dict contains a ``streamed_text`` flag
    that is set to ``True`` if any content was pushed.
    """
    ctx = {"queue": queue, "streamed_text": False}
    token = _streaming_ctx.set(ctx)
    try:
        yield ctx
    finally:
        _streaming_ctx.reset(token)
