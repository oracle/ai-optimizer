"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for registry vector store discovery and database initialization.
"""
# spell-checker: disable

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import oracledb
import pytest
from pydantic import SecretStr

from server.app.database.config import close_pool
from server.app.database.registry import (
    discover_vector_stores,
    drop_vector_store,
    init_core_database,
    refresh_db_vector_stores,
)
from server.app.database.registry import test_connection as registry_test_connection
from server.app.database.schemas import DatabaseConfig
from server.app.database.sql import execute_sql
from server.app.embed.schemas import VectorStoreConfig
from server.tests.conftest import make_core_db_config

# ---------------------------------------------------------------------------
# Unit tests (no database required)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_discover_vector_stores_empty():
    """discover_vector_stores returns [] when query returns no rows."""
    conn = MagicMock()
    with patch("server.app.database.registry.execute_sql", new_callable=AsyncMock, return_value=None):
        result = await discover_vector_stores(conn)
    assert result == []


@pytest.mark.unit
async def test_discover_vector_stores_bad_metadata():
    """Bad JSON metadata is skipped; valid entries are returned."""
    rows = [
        ("VS_GOOD", json.dumps({"alias": "good", "chunk_size": 128})),
        ("VS_LEGACY", json.dumps({"model": "cohere/embed", "distance_metric": "COSINE"})),
        ("VS_BAD", "not-json{{{"),
    ]
    conn = MagicMock()
    with patch("server.app.database.registry.execute_sql", new_callable=AsyncMock, return_value=rows):
        result = await discover_vector_stores(conn)

    assert len(result) == 2
    by_name = {item.vector_store: item for item in result}
    assert by_name["VS_GOOD"].alias == "good"
    legacy = by_name["VS_LEGACY"]
    assert legacy.embedding_model is not None
    assert legacy.embedding_model.provider == "cohere"
    assert legacy.embedding_model.id == "embed"
    assert legacy.distance_strategy is not None
    assert legacy.distance_strategy.name == "COSINE"


@pytest.mark.unit
async def test_discover_vector_stores_propagates_db_error():
    """discover_vector_stores lets database errors propagate."""
    conn = MagicMock()
    with (
        patch(
            "server.app.database.registry.execute_sql",
            new_callable=AsyncMock,
            side_effect=oracledb.DatabaseError("connection lost"),
        ),
        pytest.raises(oracledb.DatabaseError),
    ):
        await discover_vector_stores(conn)


@pytest.mark.unit
async def test_drop_vector_store_calls_execute_sql():
    """drop_vector_store calls execute_sql with the correct DROP statement."""
    conn = MagicMock()
    with patch("server.app.database.registry.execute_sql", new_callable=AsyncMock) as mock_exec:
        await drop_vector_store(conn, "MY_TABLE")

    mock_exec.assert_awaited_once_with(conn, 'DROP TABLE "MY_TABLE" PURGE')


def _make_mock_pool(conn):
    """Return a MagicMock pool whose acquire() works as an async context manager."""
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.mark.unit
async def test_test_connection_success():
    """test_connection sets usable=True, stores pool, and discovers vector stores."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=SecretStr("p"), dsn="d")
    mock_conn = AsyncMock()
    mock_pool = _make_mock_pool(mock_conn)

    with (
        patch("server.app.database.registry.create_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("server.app.database.registry.execute_sql", new_callable=AsyncMock),
        patch("server.app.database.registry.discover_vector_stores", new_callable=AsyncMock, return_value=[]),
    ):
        await registry_test_connection(cfg)

    assert cfg.usable is True
    assert cfg.pool is mock_pool


@pytest.mark.unit
async def test_test_connection_failure():
    """test_connection sets usable=False, closes pool, and re-raises on failure."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=SecretStr("p"), dsn="d")

    with (
        patch(
            "server.app.database.registry.create_pool",
            new_callable=AsyncMock,
            side_effect=oracledb.Error("connection refused"),
        ),
        patch("server.app.database.registry.close_pool", new_callable=AsyncMock) as mock_close,
        pytest.raises(oracledb.Error),
    ):
        await registry_test_connection(cfg)

    assert cfg.usable is False
    assert not cfg.vector_stores
    mock_close.assert_awaited_once()


@pytest.mark.unit
async def test_init_core_database_success():
    """init_core_database runs DDL and returns the pool on success."""
    cfg = DatabaseConfig(alias="CORE", username="u", password=SecretStr("p"), dsn="d")
    mock_conn = AsyncMock()
    mock_pool = _make_mock_pool(mock_conn)

    with (
        patch("server.app.database.registry.test_connection", new_callable=AsyncMock) as mock_test,
        patch("server.app.database.registry.execute_sql", new_callable=AsyncMock) as mock_exec,
    ):

        async def _set_pool(db_cfg):
            db_cfg.pool = mock_pool
            db_cfg.usable = True

        mock_test.side_effect = _set_pool

        result = await init_core_database(cfg)

    assert result is mock_pool
    # DDL executed for each statement in SCHEMA_DDL
    assert mock_exec.await_count > 0


@pytest.mark.unit
async def test_init_core_database_failure():
    """init_core_database cleans up pool, sets usable=False, and re-raises."""
    cfg = DatabaseConfig(alias="CORE", username="u", password=SecretStr("p"), dsn="d")

    with (
        patch(
            "server.app.database.registry.test_connection",
            new_callable=AsyncMock,
            side_effect=oracledb.Error("connect failed"),
        ),
        patch("server.app.database.registry.close_pool", new_callable=AsyncMock) as mock_close,
        pytest.raises(oracledb.Error),
    ):
        await init_core_database(cfg)

    assert cfg.usable is False
    assert cfg.pool is None
    assert not cfg.vector_stores
    mock_close.assert_awaited_once()


@pytest.mark.unit
async def test_refresh_db_vector_stores_replaces_cached_list():
    """Refresh overwrites the cached vector_stores list with live discovery output."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=SecretStr("p"), dsn="d")
    cfg.usable = True
    cfg.pool = _make_mock_pool(AsyncMock())
    cfg.vector_stores = [VectorStoreConfig(vector_store="STALE")]

    with patch(
        "server.app.database.registry.discover_vector_stores",
        new_callable=AsyncMock,
        return_value=[VectorStoreConfig(vector_store="FRESH")],
    ):
        await refresh_db_vector_stores(cfg)

    assert [vs.vector_store for vs in cfg.vector_stores] == ["FRESH"]


@pytest.mark.unit
async def test_refresh_db_vector_stores_clears_when_table_dropped():
    """An out-of-band DROP TABLE shows up as an empty discovery result."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=SecretStr("p"), dsn="d")
    cfg.usable = True
    cfg.pool = _make_mock_pool(AsyncMock())
    cfg.vector_stores = [VectorStoreConfig(vector_store="GONE")]

    with patch(
        "server.app.database.registry.discover_vector_stores",
        new_callable=AsyncMock,
        return_value=[],
    ):
        await refresh_db_vector_stores(cfg)

    assert cfg.vector_stores == []


@pytest.mark.unit
async def test_refresh_db_vector_stores_noop_without_pool():
    """No discovery is attempted when the config has no live pool."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=SecretStr("p"), dsn="d")
    cached = [VectorStoreConfig(vector_store="CACHED")]
    cfg.vector_stores = cached

    with patch("server.app.database.registry.discover_vector_stores", new_callable=AsyncMock) as mock_disc:
        await refresh_db_vector_stores(cfg)

    mock_disc.assert_not_awaited()
    assert cfg.vector_stores is cached


@pytest.mark.unit
async def test_refresh_db_vector_stores_discards_result_after_pool_rotation():
    """Stale result from an old pool must not overwrite a freshly-rotated config.

    Simulates a ``PUT /v1/databases/{alias}`` rotating the pool while a
    ``GET /v1/settings`` refresh against the old pool is still mid-flight.
    """
    cfg = DatabaseConfig(alias="TEST", username="u", password=SecretStr("p"), dsn="d")
    cfg.usable = True
    cfg.pool = _make_mock_pool(AsyncMock())

    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow(_conn):
        started.set()
        await release.wait()
        return [VectorStoreConfig(vector_store="STALE_FROM_OLD_POOL")]

    with patch("server.app.database.registry.discover_vector_stores", new=_slow):
        refresh_task = asyncio.create_task(refresh_db_vector_stores(cfg))
        await started.wait()

        # Simulate the concurrent PUT completing: new pool + new stores published.
        cfg.pool = _make_mock_pool(AsyncMock())
        cfg.vector_stores = [VectorStoreConfig(vector_store="NEW_FROM_NEW_POOL")]

        release.set()
        await refresh_task

    assert [vs.vector_store for vs in cfg.vector_stores] == ["NEW_FROM_NEW_POOL"]


@pytest.mark.unit
async def test_refresh_db_vector_stores_bounded_when_discovery_hangs():
    """A hung discovery must not block beyond the requested timeout."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=SecretStr("p"), dsn="d")
    cfg.usable = True
    cfg.pool = _make_mock_pool(AsyncMock())
    cached = [VectorStoreConfig(vector_store="CACHED")]
    cfg.vector_stores = cached

    async def _hang(*_args, **_kwargs):
        await asyncio.sleep(30)
        return []

    with (
        patch("server.app.database.registry.discover_vector_stores", new=_hang),
        patch("server.app.database.registry._DISCOVERY_TIMEOUT_SECONDS", 0.05),
    ):
        # Outer wait_for is a backstop: if the helper doesn't enforce its
        # own deadline, this test fails fast instead of hanging the suite.
        await asyncio.wait_for(refresh_db_vector_stores(cfg), timeout=2.0)

    assert cfg.vector_stores is cached


@pytest.mark.unit
async def test_refresh_db_vector_stores_keeps_cache_on_db_error():
    """A discovery failure logs and leaves the cached list untouched."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=SecretStr("p"), dsn="d")
    cfg.usable = True
    cfg.pool = _make_mock_pool(AsyncMock())
    cached = [VectorStoreConfig(vector_store="CACHED")]
    cfg.vector_stores = cached

    with patch(
        "server.app.database.registry.discover_vector_stores",
        new_callable=AsyncMock,
        side_effect=oracledb.Error("listener down"),
    ):
        await refresh_db_vector_stores(cfg)

    assert cfg.vector_stores is cached


# ---------------------------------------------------------------------------
# Integration tests (require Oracle container)
# ---------------------------------------------------------------------------


async def _create_vector_store(conn, name: str, comment: dict) -> None:
    """Create table with GENAI comment metadata."""
    await execute_sql(
        conn,
        f"""
        BEGIN
            EXECUTE IMMEDIATE 'DROP TABLE {name} PURGE';
        EXCEPTION
            WHEN OTHERS THEN
                IF SQLCODE != -942 THEN RAISE; END IF;
        END;
        """,
    )
    await execute_sql(conn, f"CREATE TABLE {name} (id NUMBER, text CLOB)")
    metadata = json.dumps(comment).replace("'", "''")
    await execute_sql(conn, f"COMMENT ON TABLE {name} IS 'GENAI: {metadata}'")
    await conn.commit()


@pytest.mark.db
async def test_discover_vector_stores(async_oracle_connection):
    """discover_vector_stores returns parsed metadata for GENAI tables."""
    conn = async_oracle_connection

    await _create_vector_store(
        conn,
        "VS_SIMPLE",
        {
            "alias": "simp",
            "embedding_model": {"provider": "openai", "id": "text-embedding"},
            "chunk_size": 512,
            "distance_strategy": "COSINE",
            "index_type": "HNSW",
        },
    )

    await _create_vector_store(
        conn,
        "VS_LEGACY",
        {
            "alias": "legacy",
            "model": "anthropic/claude-embed",
            "chunk_size": 256,
            "chunk_overlap": 32,
            "distance_metric": "EUCLIDEAN_DISTANCE",
            "parse_status": "ok",
        },
    )

    rows = await discover_vector_stores(conn)

    by_name = {row.vector_store: row for row in rows}

    simp = by_name["VS_SIMPLE"]
    assert simp.alias == "simp"
    assert simp.chunk_size == 512
    assert simp.distance_strategy is not None
    assert simp.distance_strategy.name == "COSINE"

    legacy = by_name["VS_LEGACY"]
    assert legacy.embedding_model is not None
    assert legacy.embedding_model.provider == "anthropic"
    assert legacy.embedding_model.id == "claude-embed"
    assert legacy.distance_strategy is not None
    assert legacy.distance_strategy.name == "EUCLIDEAN_DISTANCE"
    assert legacy.chunk_overlap == 32


@pytest.mark.db
async def test_discover_vector_stores_empty_real(async_oracle_connection):
    """Real DB with no GENAI tables returns empty list."""
    # Clean up any leftover GENAI tables from other tests
    conn = async_oracle_connection
    rows = await execute_sql(
        conn,
        "SELECT utc.table_name FROM all_tab_comments utc WHERE utc.comments LIKE 'GENAI:%'",
    )
    if rows:
        for (table_name,) in rows:
            await execute_sql(conn, f'DROP TABLE "{table_name}" PURGE')
        await conn.commit()

    result = await discover_vector_stores(conn)
    assert result == []


@pytest.mark.db
async def test_drop_vector_store_nonexistent_table(async_oracle_connection):
    """Dropping a nonexistent table is safe (ORA-942 swallowed by execute_sql)."""
    await drop_vector_store(async_oracle_connection, "NONEXISTENT_TABLE_12345")
    # No error raised


@pytest.mark.db
async def test_test_connection_real(configure_db_env):
    """Real connection sets usable=True and discovers stores."""
    del configure_db_env
    cfg = make_core_db_config(alias="TEST_CONN")
    try:
        await registry_test_connection(cfg)
        assert cfg.usable is True
        assert cfg.pool is not None
        assert isinstance(cfg.vector_stores, list)
    finally:
        await close_pool(cfg.pool)


@pytest.mark.db
async def test_init_core_database_real(configure_db_env):
    """Real init creates schema tables and returns pool."""
    del configure_db_env
    cfg = make_core_db_config()
    pool = None
    try:
        pool = await init_core_database(cfg)
        assert pool is not None
        assert cfg.usable is True
    finally:
        await close_pool(pool)
