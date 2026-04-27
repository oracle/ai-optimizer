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
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

from server.app.database.config import close_pool, create_pool
from server.app.database.registry import (
    discover_vector_stores,
    drop_vector_store,
    init_core_database,
)
from server.app.database.sql import execute_sql
from server.app.embed.vector_store import generate_vs_metadata, update_vs_comment
from server.app.models.schemas import ModelIdentity
from server.app.testbed.database import (
    delete_testset,
    get_evaluations,
    get_testset_qa,
    get_testsets,
    insert_evaluation,
    upsert_qa,
)
from server.tests.conftest import make_core_db_config, make_test_vs_config

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
            rag_report={"report": {}, "correct_by_topic": {}, "failures": {}},
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
# rag_report migration: BLOB → JSON + legacy row purge
# ---------------------------------------------------------------------------


class TestRagReportMigration:
    """BLOB→JSON migration drops legacy rows so list/detail endpoints stay consistent."""

    async def test_legacy_blob_rows_purged_on_upgrade(self, schema_connection):
        conn = schema_connection
        from server.app.database.objects import RENAME_DDL, SCHEMA_DDL

        conn.autocommit = True
        try:
            # Replace the canonical schema with a legacy (BLOB) one + seeded row.
            await execute_sql(conn, "DROP TABLE aio_evaluations CASCADE CONSTRAINTS PURGE")
            await execute_sql(
                conn,
                """
                CREATE TABLE aio_evaluations (
                    eid          RAW(16) DEFAULT SYS_GUID(),
                    tid          RAW(16),
                    evaluated    TIMESTAMP(9) WITH LOCAL TIME ZONE,
                    correctness  NUMBER DEFAULT 0,
                    settings     JSON,
                    rag_report   BLOB,
                    CONSTRAINT aio_evaluations_pk PRIMARY KEY (eid)
                )
                """,
            )
            await execute_sql(
                conn,
                """
                INSERT INTO aio_evaluations (evaluated, correctness, rag_report)
                VALUES (SYSTIMESTAMP, 0.5, UTL_RAW.CAST_TO_RAW('legacy-blob-payload'))
                """,
            )

            async def _scalar(sql: str):
                rows = await execute_sql(conn, sql)
                assert rows, f"Expected a row from: {sql}"
                return rows[0][0]

            assert await _scalar("SELECT COUNT(*) FROM aio_evaluations") == 1
            assert (
                await _scalar(
                    "SELECT data_type FROM user_tab_columns "
                    "WHERE table_name='AIO_EVALUATIONS' AND column_name='RAG_REPORT'"
                )
                == "BLOB"
            )

            for ddl in RENAME_DDL:
                await execute_sql(conn, ddl)

            assert (
                await _scalar(
                    "SELECT data_type FROM user_tab_columns "
                    "WHERE table_name='AIO_EVALUATIONS' AND column_name='RAG_REPORT'"
                )
                == "JSON"
            )
            assert await _scalar("SELECT COUNT(*) FROM aio_evaluations") == 0, (
                "Legacy evaluation rows must be purged so /testbed/evaluations and "
                "/testbed/evaluation stay consistent after upgrade."
            )

            # Re-running the migration on the now-JSON column must be a no-op.
            for ddl in RENAME_DDL:
                await execute_sql(conn, ddl)
            assert (
                await _scalar(
                    "SELECT data_type FROM user_tab_columns "
                    "WHERE table_name='AIO_EVALUATIONS' AND column_name='RAG_REPORT'"
                )
                == "JSON"
            )
        finally:
            # Restore canonical schema (including FK) for subsequent tests.
            await execute_sql(conn, "DROP TABLE aio_evaluations CASCADE CONSTRAINTS PURGE")
            for ddl in SCHEMA_DDL:
                await execute_sql(conn, ddl)


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
# COMMENT ON TABLE input handling (real DB)
# ---------------------------------------------------------------------------


class TestVectorStoreCommentInputHandling:
    """End-to-end checks for table-name validation and comment escaping."""

    async def test_identifier_payload_rejected_before_db_call(self, async_oracle_connection):
        """``update_vs_comment`` raises ``ValueError`` before any SQL is sent."""
        cfg = make_test_vs_config(vector_store="X IS 'x'--")
        with pytest.raises(ValueError, match="Invalid vector store table name"):
            await update_vs_comment(async_oracle_connection, cfg, '{"alias": "x"}')

    async def test_description_payload_is_literal_not_executed(self, async_oracle_connection):
        """A ``'`` + subquery description survives as a literal in the round-trip.

        Uses ``(SELECT 'SENTINEL' FROM DUAL)`` as a benign discriminator:
        if the SQL escape failed, the round-tripped description would contain
        ``xSENTINELx``; if it held, it contains the original payload string.
        """
        conn = async_oracle_connection
        table = "VS_INJECT_DESC_TEST"

        await _create_genai_table(conn, table, {"alias": "stage", "chunk_size": 1})
        try:
            payload = "x' || (SELECT 'SENTINEL' FROM DUAL) || 'x"
            _, comment_json = generate_vs_metadata(
                embedding_model=ModelIdentity(provider="openai", id="text-embedding-3-small"),
                chunk_size=1000,
                chunk_overlap=100,
                distance_strategy=DistanceStrategy.COSINE,
                description=payload,
            )

            await update_vs_comment(conn, make_test_vs_config(vector_store=table), comment_json)
            await conn.commit()

            stores = await discover_vector_stores(conn)
            match = next((s for s in stores if s.vector_store == table), None)
            assert match is not None, "Updated vector store not found via discovery"
            assert match.description == payload
        finally:
            await drop_vector_store(conn, table)
            await conn.commit()

    async def test_normal_description_round_trips(self, async_oracle_connection):
        """Sanity check: ordinary metadata survives the COMMENT round-trip."""
        conn = async_oracle_connection
        table = "VS_INJECT_BASELINE_TEST"

        await _create_genai_table(conn, table, {"alias": "stage", "chunk_size": 1})
        try:
            _, comment_json = generate_vs_metadata(
                embedding_model=ModelIdentity(provider="openai", id="text-embedding-3-small"),
                chunk_size=1000,
                chunk_overlap=100,
                distance_strategy=DistanceStrategy.COSINE,
                alias="docs",
                description="Project documentation",
            )

            await update_vs_comment(conn, make_test_vs_config(vector_store=table), comment_json)
            await conn.commit()

            stores = await discover_vector_stores(conn)
            match = next((s for s in stores if s.vector_store == table), None)
            assert match is not None
            assert match.alias == "docs"
            assert match.description == "Project documentation"
        finally:
            await drop_vector_store(conn, table)
            await conn.commit()
