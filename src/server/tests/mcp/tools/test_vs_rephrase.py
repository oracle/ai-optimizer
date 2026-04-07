"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.tools.vs_rephrase.
"""
# spell-checker: disable

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, cast

import pytest
from fastmcp.tools.function_tool import FunctionTool
from litellm.exceptions import APIConnectionError

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.mcp.tools import vs_rephrase
from server.app.mcp.tools.schemas import RephrasePrompt


@pytest.mark.anyio
async def test_vs_rephrase_disabled() -> None:
    """When rephrase disabled, prompt should remain unchanged."""
    settings.client_settings.vector_search.rephrase = False

    response = await vs_rephrase._vs_rephrase_impl("Question?", chat_history=["a", "b"])

    assert response.was_rephrased is False
    assert response.rephrased_prompt == "Question?"


@pytest.mark.anyio
async def test_vs_rephrase_success(
    configure_ll_model,
    prompt_config_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful LLM rephrase should update prompt."""
    configure_ll_model(provider="openai", model_id="gpt-rephrase")
    prompt_config_factory("optimizer_vs-rephrase", "Prompt: {prompt}\nHistory: {history}\nQuestion: {question}")
    prompt_config_factory("optimizer_context-default", "Context prompt")

    async def _fake_completion(*_args: Any, **_kwargs: Any):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="New question"))])

    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.acompletion", _fake_completion)

    response = await vs_rephrase._vs_rephrase_impl("Question?", ["one", "two"])

    assert response.was_rephrased is True
    assert response.rephrased_prompt == "New question"


@pytest.mark.anyio
async def test_vs_rephrase_history_insufficient(configure_ll_model, prompt_config_factory, monkeypatch):
    """Insufficient history should skip rephrase."""
    configure_ll_model(provider="openai", model_id="gpt-rephrase")
    prompt_config_factory("optimizer_vs-rephrase", "Prompt {prompt}")
    prompt_config_factory("optimizer_context-default", "Context")

    async def _fake_completion(*_args: Any, **_kwargs: Any):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Ignored"))])

    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.acompletion", _fake_completion)

    response = await vs_rephrase._vs_rephrase_impl("Question?", ["only one"])

    assert response.was_rephrased is False
    assert response.rephrased_prompt == "Question?"


@pytest.mark.anyio
async def test_vs_rephrase_api_error(configure_ll_model, prompt_config_factory, monkeypatch):
    """API errors should return error status with message."""
    configure_ll_model(provider="openai", model_id="gpt-rephrase")
    prompt_config_factory("optimizer_vs-rephrase", "Prompt {prompt}")
    prompt_config_factory("optimizer_context-default", "Context")

    async def _raise(*_args: Any, **_kwargs: Any):
        raise APIConnectionError("down", "openai", "gpt-rephrase")

    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.acompletion", _raise)

    response = await vs_rephrase._vs_rephrase_impl("Question?", ["one", "two"])

    assert response.status == "error"
    assert "API connection failed" in (response.error or "")


@pytest.mark.anyio
async def test_vs_rephrase_generic_error(prompt_config_factory, monkeypatch: pytest.MonkeyPatch):
    """Unexpected errors should surface in response."""
    prompt_config_factory("optimizer_vs-rephrase", "Prompt {prompt}")
    prompt_config_factory("optimizer_context-default", "Context")

    def _bad(*_args: Any, **_kwargs: Any):
        raise RuntimeError("broken")

    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.LiteLlmModelSpec.from_ll_model_settings", _bad)

    response = await vs_rephrase._vs_rephrase_impl("Question?", ["one", "two"])

    assert response.status == "error"
    assert response.error == "broken"


@pytest.mark.anyio
async def test_perform_rephrase_missing_prompt(monkeypatch: pytest.MonkeyPatch):
    """Missing prompt fallback should return original text."""
    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.find_prompt", lambda _: None)
    settings.client_settings.ll_model.provider = "openai"
    settings.client_settings.ll_model.id = "gpt"

    async def _fake_completion(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"choices": [{"message": {"content": "never used"}}]}

    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.acompletion", _fake_completion)

    result = await vs_rephrase._perform_rephrase("Question?", ["one", "two"], "ctx", {})

    assert result == "Question?"


@pytest.mark.anyio
async def test_register_rephrase_tool(monkeypatch: pytest.MonkeyPatch):
    """Registered rephrase tool should call implementation and log info."""

    async def _fake_impl(
        question: str, chat_history: Optional[List[str]], client: str = "CONFIGURED"
    ) -> RephrasePrompt:
        return RephrasePrompt(
            original_prompt=question,
            rephrased_prompt="done",
            was_rephrased=bool(chat_history),
            status="ok",
        )

    monkeypatch.setattr(vs_rephrase, "_vs_rephrase_impl", _fake_impl)

    vs_rephrase.register_rephrase_tool()

    tool = cast(FunctionTool, await mcp.local_provider.get_tool("optimizer_vs-rephrase"))

    class _Ctx:
        """Collects MCP context messages."""

        def __init__(self):
            self.messages: list[str] = []

        async def info(self, message: str) -> None:
            self.messages.append(message)

    ctx = _Ctx()
    response = await tool.fn(thread_id="abc", question="Q", chat_history=["a", "b"], ctx=ctx)

    assert response.status == "ok"
    assert ctx.messages == ["VS Rephrase (Thread ID: abc)"]
