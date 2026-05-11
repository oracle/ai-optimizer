"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.tools.vs_grade.
"""
# spell-checker: disable

from typing import Any, List, cast
from unittest.mock import MagicMock

from fastmcp.tools.function_tool import FunctionTool
from litellm.exceptions import APIConnectionError

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.mcp.tools import vs_grade
from server.app.mcp.tools.schemas import VectorGradeResponse

_DUMMY_SPEC = MagicMock(name="LiteLlmModelSpec")  # opaque to tests that mock ainvoke_text_from_spec


def _patch_llm_with_response(monkeypatch, content: str) -> None:
    """Patch ainvoke_text_from_spec to return *content* directly."""

    async def _fake(*_args, **_kwargs) -> str:
        return content

    monkeypatch.setattr("server.app.mcp.tools.vs_grade.ainvoke_text_from_spec", _fake)


def _patch_llm_with_error(monkeypatch, exc: BaseException) -> None:
    async def _fake(*_args, **_kwargs) -> str:
        raise exc

    monkeypatch.setattr("server.app.mcp.tools.vs_grade.ainvoke_text_from_spec", _fake)


def test_format_documents() -> None:
    """_format_documents joins page content rows."""
    docs = [
        {"page_content": "Doc A"},
        {"page_content": "Doc B"},
        {"missing": "ignored"},
    ]

    assert vs_grade._format_documents(docs) == "Doc A\n\nDoc B"


async def test_vs_grade_disabled_returns_documents():
    """Grading disabled should return original documents."""
    settings.client_settings.vector_search.grade = False

    response = await vs_grade._vs_grade_impl("Q", [{"page_content": "Doc"}])

    assert response.grading_performed is False
    assert response.formatted_documents == "Doc"
    assert response.relevant == "yes"


async def test_vs_grade_llm_yes(configure_ll_model, prompt_config_factory, monkeypatch):
    """LLM returning 'Yes' should keep documents."""
    settings.client_settings.vector_search.grade = True
    configure_ll_model(provider="openai", model_id="gpt-grade")
    prompt_config_factory("optimizer_vs-grade", "Question: {question}\nDocs: {documents}")
    _patch_llm_with_response(monkeypatch, "Yes")

    response = await vs_grade._vs_grade_impl("What?", [{"page_content": "Doc"}])

    assert response.relevant == "yes"
    assert response.grading_performed is True
    assert response.formatted_documents == "Doc"


async def test_vs_grade_llm_no(configure_ll_model, prompt_config_factory, monkeypatch):
    """LLM returning 'No' should clear documents."""
    settings.client_settings.vector_search.grade = True
    configure_ll_model(provider="openai", model_id="gpt-grade")
    prompt_config_factory("optimizer_vs-grade", "Prompt {question} :: {documents}")
    _patch_llm_with_response(monkeypatch, "No")

    response = await vs_grade._vs_grade_impl("Q", [{"page_content": "Doc"}])

    assert response.relevant == "no"
    assert response.formatted_documents == ""


async def test_vs_grade_api_connection_error(configure_ll_model, prompt_config_factory, monkeypatch):
    """Connection errors should fall back to success with 'yes'."""
    settings.client_settings.vector_search.grade = True
    configure_ll_model(provider="openai", model_id="gpt-grade")
    prompt_config_factory("optimizer_vs-grade", "Prompt {question} :: {documents}")
    _patch_llm_with_error(monkeypatch, APIConnectionError("network", "openai", "gpt-grade"))

    response = await vs_grade._vs_grade_impl("Q", [{"page_content": "Doc"}])

    assert response.relevant == "yes"
    assert response.status == "success"


async def test_vs_grade_generic_error(prompt_config_factory, monkeypatch):
    """Unexpected errors should set status to error."""
    settings.client_settings.vector_search.grade = True
    prompt_config_factory("optimizer_vs-grade", "Prompt {question}")

    def _bad_impl(*_args: Any, **_kwargs: Any):
        raise RuntimeError("boom")

    monkeypatch.setattr("server.app.mcp.tools.vs_grade.LiteLlmModelSpec.from_ll_model_settings", _bad_impl)

    response = await vs_grade._vs_grade_impl("Q", [{"page_content": "Doc"}])

    assert response.status == "error"
    assert response.error == "boom"


async def test_grade_documents_with_llm_missing_prompt(monkeypatch):
    """Missing prompt should default to 'yes'."""
    _patch_llm_with_response(monkeypatch, "irrelevant")
    monkeypatch.setattr("server.app.mcp.tools.vs_grade.find_prompt", lambda name: None)

    result = await vs_grade._grade_documents_with_llm("Q", "Docs", _DUMMY_SPEC)

    assert result == "yes"


async def test_grade_documents_with_llm_invalid_response(prompt_config_factory, monkeypatch, caplog):
    """Invalid LLM response should log and return 'yes'."""
    prompt_config_factory("optimizer_vs-grade", "Prompt {question} :: {documents}")
    _patch_llm_with_response(monkeypatch, "maybe")
    caplog.set_level("ERROR")

    result = await vs_grade._grade_documents_with_llm("Q", "Docs", _DUMMY_SPEC)

    assert result == "yes"
    assert "LLM did not return binary relevant" in caplog.text


async def test_register_grade_tool(monkeypatch):
    """Registered grade tool should call implementation and emit info."""

    async def _fake_impl(question: str, documents: List[dict], client: str = "CONFIGURED") -> VectorGradeResponse:
        return VectorGradeResponse(
            relevant="yes",
            formatted_documents="",
            grading_performed=False,
            num_documents=len(documents),
            status=question,
        )

    monkeypatch.setattr(vs_grade, "_vs_grade_impl", _fake_impl)

    vs_grade.register_grade_tool()

    tool = cast(FunctionTool, await mcp.local_provider.get_tool("optimizer_vs-grade"))

    class _Ctx:
        """Collects MCP context messages."""

        def __init__(self):
            self.messages: list[str] = []

        async def info(self, message: str) -> None:
            self.messages.append(message)

    ctx = _Ctx()
    response = await tool.fn(
        thread_id="abc",
        question="test",
        documents=[{"page_content": "Doc"}],
        ctx=ctx,
    )

    assert response.status == "test"
    assert ctx.messages == ["VS Grade (Thread ID: abc, Docs: 1)"]
