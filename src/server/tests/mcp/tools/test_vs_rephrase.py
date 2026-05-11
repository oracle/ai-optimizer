"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.tools.vs_rephrase.
"""
# spell-checker: disable

from typing import Any, List, Optional, cast
from unittest.mock import MagicMock

import pytest
from fastmcp.tools.function_tool import FunctionTool
from litellm.exceptions import APIConnectionError

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.mcp.tools import vs_rephrase
from server.app.mcp.tools.schemas import RephrasePrompt

_DUMMY_SPEC = MagicMock(name="LiteLlmModelSpec")  # opaque under ainvoke_text_from_spec patch


def _patch_llm_with_response(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    async def _fake(*_args, **_kwargs) -> str:
        return content

    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.ainvoke_text_from_spec", _fake)


def _patch_llm_with_error(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    async def _fake(*_args, **_kwargs) -> str:
        raise exc

    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.ainvoke_text_from_spec", _fake)


async def test_vs_rephrase_disabled() -> None:
    """When rephrase disabled, prompt should remain unchanged."""
    settings.client_settings.vector_search.rephrase = False

    response = await vs_rephrase._vs_rephrase_impl("Question?", chat_history=["a", "b"])

    assert response.was_rephrased is False
    assert response.rephrased_prompt == "Question?"


async def test_vs_rephrase_success(
    configure_ll_model,
    prompt_config_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful LLM rephrase should update prompt."""
    configure_ll_model(provider="openai", model_id="gpt-rephrase")
    prompt_config_factory("optimizer_vs-rephrase", "Prompt: {prompt}\nHistory: {history}\nQuestion: {question}")
    prompt_config_factory("optimizer_context-default", "Context prompt")
    _patch_llm_with_response(monkeypatch, "New question")

    response = await vs_rephrase._vs_rephrase_impl("Question?", ["one", "two"])

    assert response.was_rephrased is True
    assert response.rephrased_prompt == "New question"


async def test_vs_rephrase_history_insufficient(configure_ll_model, prompt_config_factory, monkeypatch):
    """Insufficient history should skip rephrase."""
    configure_ll_model(provider="openai", model_id="gpt-rephrase")
    prompt_config_factory("optimizer_vs-rephrase", "Prompt {prompt}")
    prompt_config_factory("optimizer_context-default", "Context")
    _patch_llm_with_response(monkeypatch, "Ignored")

    response = await vs_rephrase._vs_rephrase_impl("Question?", ["only one"])

    assert response.was_rephrased is False
    assert response.rephrased_prompt == "Question?"


async def test_vs_rephrase_api_error(configure_ll_model, prompt_config_factory, monkeypatch):
    """API errors should return error status with message."""
    configure_ll_model(provider="openai", model_id="gpt-rephrase")
    prompt_config_factory("optimizer_vs-rephrase", "Prompt {prompt}")
    prompt_config_factory("optimizer_context-default", "Context")
    _patch_llm_with_error(monkeypatch, APIConnectionError("down", "openai", "gpt-rephrase"))

    response = await vs_rephrase._vs_rephrase_impl("Question?", ["one", "two"])

    assert response.status == "error"
    assert "API connection failed" in (response.error or "")


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


async def test_perform_rephrase_missing_prompt(monkeypatch: pytest.MonkeyPatch):
    """Missing prompt fallback should return original text."""
    monkeypatch.setattr("server.app.mcp.tools.vs_rephrase.find_prompt", lambda _: None)
    settings.client_settings.ll_model.provider = "openai"
    settings.client_settings.ll_model.id = "gpt"
    _patch_llm_with_response(monkeypatch, "never used")

    result = await vs_rephrase._perform_rephrase("Question?", ["one", "two"], "ctx", _DUMMY_SPEC)

    assert result == "Question?"


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
