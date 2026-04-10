"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.tools.vs_retriever.
"""
# spell-checker: disable

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List, Optional, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from fastmcp.tools.function_tool import FunctionTool
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.embed.schemas import VectorStoreConfig
from server.app.mcp.tools import vs_retriever
from server.app.mcp.tools.schemas import VectorSearchResponse, VectorStoreListResponse, VectorTable
from server.app.mcp.tools.vs_retriever import _search_tables
from server.app.models.schemas import ModelIdentity


class _Doc:
    def __init__(self, content: str, metadata: Optional[dict] = None) -> None:
        self.page_content = content
        self.metadata = metadata or {}


def _make_vector_table(
    name: str,
    *,
    embedding_model: Optional[ModelIdentity] = None,
    alias: Optional[str] = None,
    description: Optional[str] = None,
    distance_strategy: DistanceStrategy = DistanceStrategy.COSINE,
) -> VectorTable:
    storage = VectorStoreConfig(
        vector_store=name,
        embedding_model=embedding_model,
        chunk_size=1,
        alias=alias,
        description=description,
        distance_strategy=distance_strategy,
    )
    return VectorTable(table_name=name, table_comment=None, parsed=storage)


async def test_get_available_vector_stores_error(monkeypatch: pytest.MonkeyPatch):
    async def _fake_discovery(filter_enabled_models: bool = True, client: str = "CONFIGURED"):
        return VectorStoreListResponse(parsed_tables=[], status="error", error="x")

    monkeypatch.setattr(vs_retriever, "_vs_discovery_impl", _fake_discovery)

    result = await vs_retriever._get_available_vector_stores()
    assert result == []


async def test_select_tables_zero_tables():
    assert await vs_retriever._select_tables_with_llm("q", [], {}, 3) == []


async def test_get_available_vector_stores_exception(monkeypatch: pytest.MonkeyPatch):
    async def _boom(filter_enabled_models: bool = True, client: str = "CONFIGURED"):
        raise RuntimeError("crash")

    monkeypatch.setattr(vs_retriever, "_vs_discovery_impl", _boom)

    assert await vs_retriever._get_available_vector_stores() == []


async def test_select_tables_single_table(prompt_config_factory, monkeypatch):
    prompt_config_factory("optimizer_vs-discovery", "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}")

    async def _fake_completion(*args: Any, **kwargs: Any):
        raise AssertionError("Should not call LLM when single table")

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.acompletion", _fake_completion)

    tables = [_make_vector_table("ONE", embedding_model=ModelIdentity(provider="openai", id="embed"))]
    result = await vs_retriever._select_tables_with_llm("q", tables, {}, 3)
    assert result == ["ONE"]


async def test_select_tables_valid_json(prompt_config_factory, monkeypatch):
    prompt_config_factory("optimizer_vs-discovery", "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}")

    async def _fake_completion(*args: Any, **kwargs: Any):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(["B", "A", "UNKNOWN"])))]
        )

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.acompletion", _fake_completion)

    tables = [
        _make_vector_table(
            "A",
            embedding_model=ModelIdentity(provider="openai", id="embed"),
            alias="ALPHA",
            description="First table",
        ),
        _make_vector_table(
            "B",
            embedding_model=ModelIdentity(provider="openai", id="embed"),
            alias="BETA",
            description="Second table",
        ),
    ]
    result = await vs_retriever._select_tables_with_llm("q", tables, {}, max_tables=2)
    assert result == ["B", "A"]


async def test_select_tables_invalid_response(prompt_config_factory, monkeypatch):
    prompt_config_factory("optimizer_vs-discovery", "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}")

    async def _fake_completion(*args: Any, **kwargs: Any):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.acompletion", _fake_completion)

    tables = [
        _make_vector_table("A", embedding_model=ModelIdentity(provider="openai", id="embed")),
        _make_vector_table("B", embedding_model=ModelIdentity(provider="openai", id="embed")),
    ]
    result = await vs_retriever._select_tables_with_llm("q", tables, {}, max_tables=2)
    assert result == ["A"]


async def test_select_tables_non_list_json(prompt_config_factory, monkeypatch):
    prompt_config_factory("optimizer_vs-discovery", "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}")

    async def _fake_completion(*args: Any, **kwargs: Any):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"table": "A"})))])

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.acompletion", _fake_completion)

    tables = [
        _make_vector_table("A", embedding_model=ModelIdentity(provider="openai", id="embed")),
        _make_vector_table("B", embedding_model=ModelIdentity(provider="openai", id="embed")),
    ]
    result = await vs_retriever._select_tables_with_llm("q", tables, {}, max_tables=2)
    assert result == ["A"]


async def test_select_tables_no_valid_entries(prompt_config_factory, monkeypatch):
    prompt_config_factory("optimizer_vs-discovery", "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}")

    async def _fake_completion(*args: Any, **kwargs: Any):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(["UNKNOWN"])))])

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.acompletion", _fake_completion)

    tables = [
        _make_vector_table("A", embedding_model=ModelIdentity(provider="openai", id="embed")),
        _make_vector_table("B", embedding_model=ModelIdentity(provider="openai", id="embed")),
    ]
    result = await vs_retriever._select_tables_with_llm("q", tables, {}, max_tables=2)
    assert result == ["A"]


async def test_select_tables_missing_prompt(monkeypatch):
    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.find_prompt", lambda _: None)

    tables = [
        _make_vector_table("A", embedding_model=ModelIdentity(provider="openai", id="embed")),
        _make_vector_table("B", embedding_model=ModelIdentity(provider="openai", id="embed")),
    ]
    result = await vs_retriever._select_tables_with_llm("q", tables, {}, max_tables=2)
    assert result == ["A"]


def test_deduplicate_documents():
    docs = [
        {"page_content": "A", "metadata": {"similarity_score": 0.5}},
        {"page_content": "A", "metadata": {"similarity_score": 0.9}},
        {"page_content": "B", "metadata": {"similarity_score": 0.1}},
    ]

    result = vs_retriever._deduplicate_documents(docs)

    assert len(result) == 2
    assert result[0]["metadata"]["similarity_score"] == 0.9


async def test_search_table_similarity(monkeypatch: pytest.MonkeyPatch):
    settings.client_settings.vector_search.search_type = "Similarity"
    settings.client_settings.vector_search.top_k = 5
    settings.client_settings.vector_search.score_threshold = 0.7

    async def _fake_acreate(*args: Any, **kwargs: Any):
        class _Store:
            async def asimilarity_search_with_score(self, question: str, k: int):
                doc1 = _Doc("Doc1", {"similarity_score": 0.1})
                doc2 = _Doc("Doc2", {"similarity_score": 0.2})
                return [(doc1, 0.2), (doc2, 1.8)]

        return _Store()

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.OracleVS.acreate", _fake_acreate)

    docs = await vs_retriever._search_table(
        table_name="T",
        question="Q",
        async_conn=None,
        embed_client=None,
        vector_search=settings.client_settings.vector_search,
        distance_strategy=DistanceStrategy.COSINE,
    )

    assert len(docs) == 1
    assert docs[0]["metadata"]["searched_table"] == "T"
    assert docs[0]["metadata"]["similarity_score"] > 0.7


async def test_search_table_similarity_dot(monkeypatch: pytest.MonkeyPatch):
    settings.client_settings.vector_search.search_type = "Similarity"
    settings.client_settings.vector_search.top_k = 5
    settings.client_settings.vector_search.score_threshold = 0.0

    async def _fake_acreate(*args: Any, **kwargs: Any):
        class _Store:
            async def asimilarity_search_with_score(self, question: str, k: int):
                return [
                    (_Doc("Doc1", {}), 0.25),
                ]

        return _Store()

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.OracleVS.acreate", _fake_acreate)

    docs = await vs_retriever._search_table(
        table_name="T",
        question="Q",
        async_conn=None,
        embed_client=None,
        vector_search=settings.client_settings.vector_search,
        distance_strategy=DistanceStrategy.DOT_PRODUCT,
    )

    assert docs[0]["metadata"]["similarity_score"] == 0.25


async def test_search_table_similarity_other(monkeypatch: pytest.MonkeyPatch):
    settings.client_settings.vector_search.search_type = "Similarity"
    settings.client_settings.vector_search.top_k = 5
    settings.client_settings.vector_search.score_threshold = 0.0

    async def _fake_acreate(*args: Any, **kwargs: Any):
        class _Store:
            async def asimilarity_search_with_score(self, question: str, k: int):
                return [
                    (_Doc("Doc1", {}), 1.0),
                ]

        return _Store()

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.OracleVS.acreate", _fake_acreate)

    docs = await vs_retriever._search_table(
        table_name="T",
        question="Q",
        async_conn=None,
        embed_client=None,
        vector_search=settings.client_settings.vector_search,
        distance_strategy=None,
    )

    assert docs[0]["metadata"]["similarity_score"] == 0.5


async def test_search_table_mmr(monkeypatch: pytest.MonkeyPatch):
    settings.client_settings.vector_search.search_type = "Maximal Marginal Relevance"
    settings.client_settings.vector_search.top_k = 3

    async def _fake_acreate(*args: Any, **kwargs: Any):
        class _Store:
            async def amax_marginal_relevance_search(self, question: str, k: int, fetch_k: int, lambda_mult: float):
                return [_Doc("Doc1"), _Doc("Doc2")]

        return _Store()

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.OracleVS.acreate", _fake_acreate)

    docs = await vs_retriever._search_table(
        table_name="T",
        question="Q",
        async_conn=None,
        embed_client=None,
        vector_search=settings.client_settings.vector_search,
        distance_strategy=DistanceStrategy.COSINE,
    )

    assert len(docs) == 2
    assert all(doc["metadata"]["searched_table"] == "T" for doc in docs)


async def test_search_table_default_branch(monkeypatch: pytest.MonkeyPatch):
    settings.client_settings.vector_search.search_type = "Hybrid"
    settings.client_settings.vector_search.top_k = 2

    async def _fake_acreate(*args: Any, **kwargs: Any):
        class _Store:
            async def asimilarity_search(self, question: str, k: int):
                return [_Doc("Doc1"), _Doc("Doc2")]

        return _Store()

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.OracleVS.acreate", _fake_acreate)

    docs = await vs_retriever._search_table(
        table_name="T",
        question="Q",
        async_conn=None,
        embed_client=None,
        vector_search=settings.client_settings.vector_search,
        distance_strategy=DistanceStrategy.COSINE,
    )

    assert len(docs) == 2


class _AcquireContext:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        return _AcquireContext(self._conn)


async def test_vs_retrieve_no_tables(monkeypatch: pytest.MonkeyPatch):
    async def _available(client="CONFIGURED"):
        return []

    monkeypatch.setattr(vs_retriever, "_get_available_vector_stores", _available)

    response = await vs_retriever._vs_retrieve_impl("Q")

    assert response.status == "error"
    assert response.error == "No vector stores available with enabled embedding models"


async def test_vs_retrieve_no_pool(model_config_factory, prompt_config_factory, monkeypatch: pytest.MonkeyPatch):
    settings.client_settings.ll_model.provider = "openai"
    settings.client_settings.ll_model.id = "gpt-retrieve"
    model_config_factory(provider="openai", model_id="gpt-retrieve", model_type="ll")
    prompt_config_factory("optimizer_vs-discovery", "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}")
    monkeypatch.setattr(
        "server.app.mcp.tools.vs_retriever.acompletion",
        lambda *args, **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='["T"]'))]),
    )
    tables = [_make_vector_table("T", embedding_model=ModelIdentity(provider="openai", id="embed"))]

    async def _available(client="CONFIGURED"):
        return tables

    monkeypatch.setattr(vs_retriever, "_get_available_vector_stores", _available)
    monkeypatch.setattr(vs_retriever, "get_database_pool", lambda client="CONFIGURED": None)

    response = await vs_retriever._vs_retrieve_impl("Q")

    assert response.status == "error"
    assert response.error == "No database connection pool available"


async def test_vs_retrieve_missing_embedding_model(
    model_config_factory,
    prompt_config_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    settings.client_settings.ll_model.provider = "openai"
    settings.client_settings.ll_model.id = "gpt-retrieve"
    model_config_factory(provider="openai", model_id="gpt-retrieve", model_type="ll")
    prompt_config_factory("optimizer_vs-discovery", "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}")
    monkeypatch.setattr(
        "server.app.mcp.tools.vs_retriever.acompletion",
        lambda *args, **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='["T"]'))]),
    )
    tables = [_make_vector_table("T")]

    async def _available(client="CONFIGURED"):
        return tables

    async def _select(question: str, available: List[VectorTable], config: dict, max_tables: int = 3):
        return [available[0].table_name]

    fake_conn = object()
    monkeypatch.setattr(vs_retriever, "_get_available_vector_stores", _available)
    monkeypatch.setattr(vs_retriever, "_select_tables_with_llm", _select)
    monkeypatch.setattr(vs_retriever, "get_database_pool", lambda client="CONFIGURED": _FakePool(fake_conn))

    response = await vs_retriever._vs_retrieve_impl("Q")

    assert response.status == "success"
    assert response.failed_tables == ["T"]
    assert response.searched_tables == []


async def test_vs_retrieve_search_exception(
    model_config_factory,
    prompt_config_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    settings.client_settings.vector_search.discovery = True
    settings.client_settings.ll_model.provider = "openai"
    settings.client_settings.ll_model.id = "gpt-retrieve"
    model_config_factory(provider="openai", model_id="gpt-retrieve", model_type="ll")
    prompt_config_factory("optimizer_vs-discovery", "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}")

    tables = [
        _make_vector_table("T", embedding_model=ModelIdentity(provider="openai", id="embed")),
    ]

    async def _available(client="CONFIGURED"):
        return tables

    async def _select(question: str, available: List[VectorTable], config: dict, max_tables: int = 3):
        return [available[0].table_name]

    fake_conn = object()
    monkeypatch.setattr(vs_retriever, "_get_available_vector_stores", _available)
    monkeypatch.setattr(vs_retriever, "_select_tables_with_llm", _select)
    monkeypatch.setattr(vs_retriever, "get_database_pool", lambda client="CONFIGURED": _FakePool(fake_conn))
    monkeypatch.setattr(vs_retriever, "get_client_embed", lambda *args, **kwargs: object())

    async def _raise_search(*args, **kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr(vs_retriever, "_search_table", _raise_search)
    _mock_spec = SimpleNamespace(to_litellm_kwargs=lambda: {})
    monkeypatch.setattr(
        vs_retriever,
        "LiteLlmModelSpec",
        SimpleNamespace(from_ll_model_settings=lambda *a, **kw: _mock_spec),
    )
    monkeypatch.setattr(
        "server.app.mcp.tools.vs_retriever.acompletion",
        lambda *args, **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='["T"]'))]),
    )

    response = await vs_retriever._vs_retrieve_impl("Q")

    assert response.status == "success"
    assert response.failed_tables == ["T"]
    assert response.searched_tables == []


async def test_vs_retrieve_generic_error(monkeypatch: pytest.MonkeyPatch):
    settings.client_settings = None  # type: ignore[assignment]

    response = await vs_retriever._vs_retrieve_impl("Q")

    assert response.status == "error"
    assert "Vector search failed" in (response.error or "")


@pytest.mark.db
async def test_vs_retrieve_success(
    vector_db_config,
    vector_store_table,
    model_config_factory,
    prompt_config_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    del vector_store_table
    model_config_factory(provider="openai", model_id="text-embed", model_type="embed")
    model_config_factory(provider="openai", model_id="gpt-retrieve", model_type="ll")
    settings.client_settings.ll_model.provider = "openai"
    settings.client_settings.ll_model.id = "gpt-retrieve"
    settings.client_settings.vector_search.search_type = "Similarity"
    settings.client_settings.vector_search.top_k = 2
    settings.client_settings.vector_search.score_threshold = 0.0

    prompt_config_factory(
        "optimizer_vs-discovery",
        "Tables: {tables_info}\nQuestion: {question}\nMax: {max_tables}",
    )

    async def _fake_completion(*args: Any, **kwargs: Any):
        return {"choices": [{"message": {"content": json.dumps(["PYTEST_GENAI_TABLE"])}}]}

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.acompletion", _fake_completion)
    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.get_client_embed", lambda *args, **kwargs: object())

    async def _fake_acreate(*args: Any, **kwargs: Any):
        class _Store:
            async def asimilarity_search_with_score(self, question: str, k: int):
                doc = _Doc("Doc1", {"similarity_score": 0.9})
                duplicate = _Doc("Doc1", {"similarity_score": 0.8})
                return [(doc, 0.1), (duplicate, 0.2)]

        return _Store()

    monkeypatch.setattr("server.app.mcp.tools.vs_retriever.OracleVS.acreate", _fake_acreate)

    class _Ctx:
        def __init__(self):
            self.progress: list[tuple[int, int]] = []
            self.messages: list[str] = []

        async def report_progress(self, step: int, total: int) -> None:
            self.progress.append((step, total))

        async def info(self, message: str) -> None:
            self.messages.append(message)

    ctx = _Ctx()
    response = await vs_retriever._vs_retrieve_impl("Question?", cast(Context, ctx))

    assert response.status == "success"
    assert response.searched_tables == ["PYTEST_GENAI_TABLE"]
    assert response.failed_tables == []
    assert response.num_documents == 1
    assert response.documents[0]["page_content"] == "Doc1"
    assert ctx.progress == [(1, 4), (2, 4), (3, 4), (4, 4)]


async def test_register_retriever_tool(monkeypatch: pytest.MonkeyPatch):
    async def _fake_impl(question: str, ctx=None, client: str = "CONFIGURED") -> VectorSearchResponse:
        return VectorSearchResponse(
            context_input=question,
            documents=[],
            num_documents=0,
            searched_tables=[],
            failed_tables=[],
            status="ok",
        )

    monkeypatch.setattr(vs_retriever, "_vs_retrieve_impl", _fake_impl)

    vs_retriever.register_retriever_tool()

    tool = cast(FunctionTool, await mcp.local_provider.get_tool("optimizer_vs-retriever"))

    class _Ctx:
        def __init__(self):
            self.messages: list[str] = []

        async def info(self, message: str) -> None:
            self.messages.append(message)

    ctx = _Ctx()
    response = await tool.fn(thread_id="abc", question="Q", ctx=ctx)

    assert response.status == "ok"
    assert ctx.messages == ["VS Retriever (Thread ID: abc)"]


# ---------------------------------------------------------------------------
# _search_tables concurrent orchestration
# ---------------------------------------------------------------------------

PATCH_SEARCH = "server.app.mcp.tools.vs_retriever._search_table"
PATCH_EMBED = "server.app.mcp.tools.vs_retriever.get_client_embed"


def _make_search_table(name, provider="oci", model_id="embed-v1"):
    """Build a VectorTable with a minimal VectorStoreConfig."""
    return VectorTable(
        table_name=name,
        parsed=VectorStoreConfig(
            embedding_model=ModelIdentity(provider=provider, id=model_id),
            distance_strategy=DistanceStrategy.COSINE,
        ),
    )


def _make_table_no_embed(name):
    """Build a VectorTable without an embedding model."""
    return VectorTable(
        table_name=name,
        parsed=VectorStoreConfig(embedding_model=None),
    )


def _make_search_response(question="test question"):
    """Create an empty VectorSearchResponse."""
    return VectorSearchResponse(
        context_input=question,
        documents=[],
        num_documents=0,
        searched_tables=[],
        failed_tables=[],
        status="pending",
    )


def _make_pool():
    """Mock pool whose acquire() returns an async context manager."""
    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = MagicMock(name="conn")
    ctx.__aexit__.return_value = False
    pool.acquire.return_value = ctx
    return pool


def _doc_dict(content="doc content", table="t", score=0.9):
    """Build a minimal document dict."""
    return {"page_content": content, "metadata": {"similarity_score": score, "searched_table": table}}


class TestSearchTables:
    """Tests for _search_tables concurrent orchestration logic."""

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_single_table_success(self, mock_search, mock_embed):
        """Single table search returns documents and populates searched_tables."""
        mock_embed.return_value = MagicMock(name="embed_client")
        mock_search.return_value = [_doc_dict("hello", "t1")]

        table = _make_search_table("t1")
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t1"], [table], "q", MagicMock(), MagicMock(), response)

        assert response.searched_tables == ["t1"]
        assert len(response.documents) == 1
        assert response.documents[0]["page_content"] == "hello"
        assert response.failed_tables == []

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_multiple_tables_concurrent(self, mock_search, mock_embed):
        """Multiple tables are searched concurrently, results merged."""
        mock_embed.return_value = MagicMock(name="embed_client")
        mock_search.side_effect = [
            [_doc_dict("doc_a", "t1")],
            [_doc_dict("doc_b", "t2")],
        ]

        tables = [_make_search_table("t1"), _make_search_table("t2", model_id="embed-v2")]
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t1", "t2"], tables, "q", MagicMock(), MagicMock(), response)

        assert set(response.searched_tables) == {"t1", "t2"}
        assert len(response.documents) == 2
        assert mock_search.call_count == 2
        assert response.failed_tables == []

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_embed_client_cached_same_model(self, mock_search, mock_embed):
        """Same (provider, id) reuses a single embed client."""
        sentinel = MagicMock(name="shared_client")
        mock_embed.return_value = sentinel
        mock_search.return_value = []

        tables = [_make_search_table("t1", "oci", "embed-v1"), _make_search_table("t2", "oci", "embed-v1")]
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t1", "t2"], tables, "q", MagicMock(), MagicMock(), response)

        mock_embed.assert_called_once()
        for call in mock_search.call_args_list:
            assert call.args[3] is sentinel

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_embed_client_separate_for_different_models(self, mock_search, mock_embed):
        """Different (provider, id) pairs create separate embed clients."""
        clients = [MagicMock(name="c1"), MagicMock(name="c2")]
        mock_embed.side_effect = clients
        mock_search.return_value = []

        tables = [_make_search_table("t1", "oci", "embed-v1"), _make_search_table("t2", "oci", "embed-v2")]
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t1", "t2"], tables, "q", MagicMock(), MagicMock(), response)

        assert mock_embed.call_count == 2

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_table_not_discovered_skipped(self, mock_search, mock_embed):
        """A table name not in available_tables goes to failed_tables."""
        mock_embed.return_value = MagicMock()
        mock_search.return_value = [_doc_dict("ok", "t1")]

        table = _make_search_table("t1")
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t1", "missing_table"], [table], "q", MagicMock(), MagicMock(), response)

        assert "missing_table" in response.failed_tables
        assert response.searched_tables == ["t1"]
        assert len(response.documents) == 1

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_table_no_embedding_model_skipped(self, mock_search, mock_embed):
        """A table without an embedding model goes to failed_tables."""
        table = _make_table_no_embed("t_no_embed")
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t_no_embed"], [table], "q", MagicMock(), MagicMock(), response)

        assert "t_no_embed" in response.failed_tables
        mock_search.assert_not_called()

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_one_table_fails_others_succeed(self, mock_search, mock_embed):
        """When one table raises, it goes to failed_tables; others succeed."""
        mock_embed.return_value = MagicMock()
        mock_search.side_effect = [
            RuntimeError("boom"),
            [_doc_dict("good", "t2")],
        ]

        tables = [_make_search_table("t1"), _make_search_table("t2")]
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t1", "t2"], tables, "q", MagicMock(), MagicMock(), response)

        assert response.failed_tables == ["t1"]
        assert response.searched_tables == ["t2"]
        assert len(response.documents) == 1

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_all_tables_fail(self, mock_search, mock_embed):
        """When all searches raise, all go to failed_tables, no documents."""
        mock_embed.return_value = MagicMock()
        mock_search.side_effect = RuntimeError("boom")

        tables = [_make_search_table("t1"), _make_search_table("t2")]
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t1", "t2"], tables, "q", MagicMock(), MagicMock(), response)

        assert set(response.failed_tables) == {"t1", "t2"}
        assert response.searched_tables == []
        assert response.documents == []

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_empty_tables_to_search(self, mock_search, mock_embed):
        """Empty tables_to_search list results in unchanged response."""
        response = _make_search_response()

        await _search_tables(_make_pool(), [], [_make_search_table("t1")], "q", MagicMock(), MagicMock(), response)

        assert response.documents == []
        assert response.searched_tables == []
        assert response.failed_tables == []
        mock_search.assert_not_called()

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_all_tables_invalid(self, mock_search, mock_embed):
        """All tables fail pre-validation; _search_table never called."""
        response = _make_search_response()

        await _search_tables(
            _make_pool(), ["ghost1", "ghost2"], [_make_search_table("real")], "q", MagicMock(), MagicMock(), response
        )

        assert set(response.failed_tables) == {"ghost1", "ghost2"}
        assert response.searched_tables == []
        mock_search.assert_not_called()

    @patch(PATCH_EMBED)
    @patch(PATCH_SEARCH, new_callable=AsyncMock)
    async def test_embed_client_error_isolates_table(self, mock_search, mock_embed):
        """A get_client_embed failure marks that table failed; others proceed."""
        mock_embed.side_effect = [ValueError("bad model config"), MagicMock(name="good_client")]
        mock_search.return_value = [_doc_dict("ok", "t2")]

        tables = [_make_search_table("t1", model_id="bad-model"), _make_search_table("t2", model_id="good-model")]
        response = _make_search_response()

        await _search_tables(_make_pool(), ["t1", "t2"], tables, "q", MagicMock(), MagicMock(), response)

        assert response.failed_tables == ["t1"]
        assert response.searched_tables == ["t2"]
        assert len(response.documents) == 1
        mock_search.assert_called_once()
