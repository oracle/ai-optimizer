"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared fixtures for API tests.
"""
# spell-checker: disable

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.mcp.prompts.registry import register_mcp_prompt
from server.app.mcp.prompts.schemas import PromptConfig


def _create_mock_pool(conn: AsyncMock) -> MagicMock:
    """Return a MagicMock that behaves like an async pool with .acquire()."""
    cursor = AsyncMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    cursor.description = None
    cursor.fetchall = AsyncMock(return_value=[])
    cursor.setinputsizes = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    conn._cursor = cursor  # expose for tests that need to tweak behaviour

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.fixture
def populate_prompts():
    """Inject test PromptConfig entries into settings and register with MCP."""
    original = settings.prompt_configs
    settings.prompt_configs = [
        PromptConfig(
            name="test_prompt-one",
            title="Test Prompt One",
            description="First test prompt",
            tags=["test"],
            text="Hello, world!",
        ),
        PromptConfig(
            name="test_prompt-two",
            title="Test Prompt Two",
            description="Second test prompt (customized)",
            tags=["test", "custom"],
            text="Custom text here",
        ),
    ]
    for pc in settings.prompt_configs:
        register_mcp_prompt(pc)
    yield
    for pc in settings.prompt_configs:
        with contextlib.suppress(KeyError):
            mcp.local_provider.remove_prompt(pc.name)
    settings.prompt_configs = original
