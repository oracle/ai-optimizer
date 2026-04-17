"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for database gaps: drop vector store, cascade deletes,
concurrent access, and connection timeout behaviour.
"""
# spell-checker: disable

import asyncio
import json

import oracledb
import pytest

from server.app.database.config import close_pool, create_pool
from server.app.database.registry import (
    discover_vector_stores,
    drop_vector_store,
    init_core_database,
)
from server.app.database.sql import execute_sql, validate_oracle_identifier
from server.app.testbed.database import (
    delete_testset,
    get_evaluations,
    get_testset_qa,
    get_testsets,
    insert_evaluation,
    upsert_qa,
)
from server.tests.conftest import make_core_db_config

pytestmark = [pytest.mark.db]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_genai_table(conn, name: str, metadata: dict) -> None:
    """Create a table with GENAI comment metadata."""
    await execute_sql(conn, f'DROP TABLE "{name}" PURGE')
    await execute_sql(conn, f'CREATE TABLE "{name}" (id NUMBER, text CLOB)')
    meta_str = json.dumps(metadata).replace("'", "''")
    await execute_sql(conn, f"""COMMENT ON TABLE "{name}" IS 'GENAI: {meta_str}'""")
    await conn.commit()


# ---------------------------------------------------------------------------
# Drop vector store (real DB)
# ---------------------------------------------------------------------------


class TestDropVectorStore:
    """Integration tests for drop_vector_store against a real database."""

    async def test_drop_existing_table(self, async_oracle_connection):
        """drop_vector_store removes a real GENAI table."""
        conn = async_oracle_connection
        table = "VS_DROP_TEST"

        await _create_genai_table(
            conn,
            table,
            {"alias": "drop_me", "chunk_size": 128},
        )

        # Verify table exists
        stores = await discover_vector_stores(conn)
        assert any(s.vector_store == table for s in stores)

        # Drop it
        await drop_vector_store(conn, table)
        await conn.commit()

        # Verify table is gone
        stores = await discover_vector_stores(conn)
        assert not any(s.vector_store == table for s in stores)

    async def test_drop_nonexistent_table_is_safe(self, async_oracle_connection):
        """Dropping a table that doesn't exist raises no error."""
        await drop_vector_store(async_oracle_connection, "DOES_NOT_EXIST_999")

    async def test_drop_and_recreate(self, async_oracle_connection):
        """A dropped table can be recreated with the same name."""
        conn = async_oracle_connection
        table = "VS_RECREATE_TEST"

        await _create_genai_table(conn, table, {"alias": "v1", "chunk_size": 64})
        await drop_vector_store(conn, table)
        await conn.commit()

        # Recreate with different metadata
        await _create_genai_table(conn, table, {"alias": "v2", "chunk_size": 256})

        stores = await discover_vector_stores(conn)
        match = [s for s in stores if s.vector_store == table]
        assert len(match) == 1
        assert match[0].alias == "v2"
        assert match[0].chunk_size == 256

        # Cleanup
        await drop_vector_store(conn, table)
        await conn.commit()

    async def test_drop_identifier_with_quotes(self, async_oracle_connection):
        """validate_oracle_identifier escapes embedded quotes for safe DROP."""
        safe = validate_oracle_identifier('table"name')
        assert safe == 'table""name'


# ---------------------------------------------------------------------------
# Cascade deletes (FK ON DELETE CASCADE)
# ---------------------------------------------------------------------------


@pytest.fixture
async def schema_connection(async_oracle_connection):
    """Ensure schema tables exist for testbed operations."""
    conn = async_oracle_connection
    from server.app.database.objects import SCHEMA_DDL

    conn.autocommit = True
    for ddl in SCHEMA_DDL:
        await execute_sql(conn, ddl)
    conn.autocommit = False
    yield conn


class TestCascadeDeletes:
    """Verify FK ON DELETE CASCADE behaviour on aio_testsets children."""

    async def test_delete_testset_cascades_to_qa(self, schema_connection):
        """Deleting a testset removes its child Q&A records."""
        conn = schema_connection

        qa = json.dumps([{"question": "Q1?", "answer": "A1"}])
        tid = await upsert_qa(conn, "Cascade QA Test", "2026-01-01T00:00:00.000", qa)
        await conn.commit()

        # Verify Q&A exists
        qa_data = await get_testset_qa(conn, tid)
        assert len(qa_data["qa_data"]) == 1

        # Delete the parent testset
        await delete_testset(conn, tid)

        # Q&A should be gone (cascade)
        qa_data = await get_testset_qa(conn, tid)
        assert qa_data["qa_data"] == []

    async def test_delete_testset_cascades_to_evaluations(self, schema_connection):
        """Deleting a testset removes its child evaluation records."""
        conn = schema_connection

        qa = json.dumps([{"question": "Q?", "answer": "A"}])
        tid = await upsert_qa(conn, "Cascade Eval Test", "2026-01-02T00:00:00.000", qa)
        await conn.commit()

        eid = await insert_evaluation(
            conn,
            tid=tid,
            evaluated="2026-01-02T00:00:01.000",
            correctness=0.75,
            settings_json='{"model": "test"}',
            rag_report=b"dummy",
        )
        await conn.commit()

        # Verify evaluation exists
        evals = await get_evaluations(conn, tid)
        assert len(evals) == 1
        assert evals[0]["eid"] == eid

        # Delete parent
        await delete_testset(conn, tid)

        # Evaluations should be gone
        evals = await get_evaluations(conn, tid)
        assert evals == []

    async def test_testset_not_found_after_delete(self, schema_connection):
        """Deleted testset no longer appears in get_testsets()."""
        conn = schema_connection

        qa = json.dumps([{"question": "Q?", "answer": "A"}])
        tid = await upsert_qa(conn, "Delete Visibility Test", "2026-01-03T00:00:00.000", qa)
        await conn.commit()

        testsets = await get_testsets(conn)
        assert any(t["tid"] == tid for t in testsets)

        await delete_testset(conn, tid)

        testsets = await get_testsets(conn)
        assert not any(t["tid"] == tid for t in testsets)


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------


class TestConcurrentAccess:
    """Tests for concurrent database operations via connection pool."""

    async def test_concurrent_selects(self, configure_db_env):
        """Multiple concurrent SELECT queries on a shared pool succeed."""
        del configure_db_env
        cfg = make_core_db_config()
        pool = await create_pool(cfg)
        assert pool is not None

        try:

            async def _select(i):
                async with pool.acquire() as conn:
                    result = await execute_sql(conn, "SELECT :val FROM DUAL", {"val": i})
                    assert result is not None
                    return result[0][0]

            results = await asyncio.gather(*[_select(i) for i in range(10)])
            assert sorted(results) == list(range(10))
        finally:
            await close_pool(pool)

    async def test_concurrent_dml(self, schema_connection, configure_db_env):
        """Concurrent inserts into aio_testsets don't deadlock or error."""
        del configure_db_env
        cfg = make_core_db_config()
        pool = await create_pool(cfg)
        assert pool is not None

        try:

            async def _insert(i):
                async with pool.acquire() as conn:
                    qa = json.dumps([{"question": f"Q{i}?", "answer": f"A{i}"}])
                    tid = await upsert_qa(
                        conn,
                        f"Concurrent Test {i}",
                        f"2026-02-{i + 1:02d}T00:00:00.000",
                        qa,
                    )
                    await conn.commit()
                    return tid

            tids = await asyncio.gather(*[_insert(i) for i in range(5)])
            assert len(tids) == 5
            assert len(set(tids)) == 5  # All unique

            # Cleanup
            for tid in tids:
                async with pool.acquire() as conn:
                    await delete_testset(conn, tid)
        finally:
            await close_pool(pool)

    async def test_pool_acquire_under_contention(self, configure_db_env):
        """Pool handles more concurrent requests than its max size."""
        del configure_db_env
        cfg = make_core_db_config()
        # Small pool to force contention
        pool = await create_pool(cfg)
        assert pool is not None

        try:
            results = []

            async def _work(i):
                async with pool.acquire() as conn:
                    r = await execute_sql(conn, "SELECT :val FROM DUAL", {"val": i})
                    assert r is not None
                    results.append(r[0][0])

            # More tasks than pool size
            await asyncio.gather(*[_work(i) for i in range(20)])
            assert len(results) == 20
        finally:
            await close_pool(pool)


# ---------------------------------------------------------------------------
# Connection timeout / error handling
# ---------------------------------------------------------------------------


class TestConnectionTimeout:
    """Tests for connection timeout and error handling."""

    async def test_pool_acquire_with_bad_dsn_raises(self, configure_db_env):
        """Acquiring from a pool with refused DSN raises on connect."""
        del configure_db_env
        # Use localhost with a port that is not listening — gives an immediate
        # connection-refused instead of a black-hole timeout.
        cfg = make_core_db_config(dsn="//localhost:19999/NONEXIST")

        pool = await create_pool(cfg)
        try:
            with pytest.raises(oracledb.Error):
                async with pool.acquire() as conn:
                    await execute_sql(conn, "SELECT 1 FROM DUAL")
        finally:
            await close_pool(pool)

    async def test_pool_acquire_with_bad_credentials_raises(self, configure_db_env):
        """Acquiring from a pool with wrong password raises oracledb.Error."""
        del configure_db_env
        cfg = make_core_db_config(password="WRONG_PASSWORD_123")

        pool = await create_pool(cfg)
        try:
            with pytest.raises(oracledb.Error):
                async with pool.acquire() as conn:
                    await execute_sql(conn, "SELECT 1 FROM DUAL")
        finally:
            await close_pool(pool)

    async def test_init_core_database_bad_credentials_sets_unusable(self, configure_db_env):
        """init_core_database marks config as unusable on auth failure."""
        del configure_db_env
        cfg = make_core_db_config(password="WRONG_PASSWORD_123")

        with pytest.raises(oracledb.Error):
            await init_core_database(cfg)

        assert cfg.usable is False
        assert cfg.pool is None

    async def test_execute_sql_on_closed_connection_raises(self, oracle_db_container):
        """Using a closed connection raises oracledb.Error."""
        del oracle_db_container
        from server.tests.conftest import TEST_DB_CONFIG

        conn = await oracledb.connect_async(
            user=TEST_DB_CONFIG["db_username"],
            password=TEST_DB_CONFIG["db_password"],
            dsn=TEST_DB_CONFIG["db_dsn"],
        )
        await conn.close()

        with pytest.raises(oracledb.Error):
            await execute_sql(conn, "SELECT 1 FROM DUAL")


# ---------------------------------------------------------------------------
# RAW identifier edge cases
# ---------------------------------------------------------------------------


class TestRawIdentifierEdgeCases:
    """Test validate_oracle_identifier with edge case inputs against real DB."""

    async def test_table_name_with_special_chars(self, async_oracle_connection):
        """Tables with special characters in names work via quoted identifiers."""
        conn = async_oracle_connection
        name = "TEST$SPECIAL#TBL"

        safe = validate_oracle_identifier(name)
        await execute_sql(conn, f'CREATE TABLE "{safe}" (id NUMBER)')
        await conn.commit()

        result = await execute_sql(conn, f'SELECT COUNT(*) FROM "{safe}"')
        assert result == [(0,)]

        await execute_sql(conn, f'DROP TABLE "{safe}" PURGE')
        await conn.commit()

    async def test_table_name_with_spaces(self, async_oracle_connection):
        """Quoted identifiers with spaces work in real Oracle."""
        conn = async_oracle_connection
        name = "MY TEST TABLE"

        safe = validate_oracle_identifier(name)
        await execute_sql(conn, f'CREATE TABLE "{safe}" (id NUMBER)')
        await conn.commit()

        result = await execute_sql(conn, f'SELECT COUNT(*) FROM "{safe}"')
        assert result == [(0,)]

        await execute_sql(conn, f'DROP TABLE "{safe}" PURGE')
        await conn.commit()
