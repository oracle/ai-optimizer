"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for the embed job store against a real Oracle container.

These drive the store through its public ``_store_*`` entry points with
``get_core_pool`` pointed at a live Oracle Free pool, so the actual SQL
(JSON binds, LOB reads, terminal-state guards, reaper / TTL predicates)
executes against real Oracle 23ai — the behaviour the mock-pool unit
tests in ``test_jobs.py`` can only approximate.
"""
# spell-checker: disable

import datetime

import oracledb
import pytest

from server.app.api.v1.schemas.embed import (
    EmbedJobProgress,
    EmbedJobStage,
    EmbedJobStatus,
    EmbedProcessingResult,
    ProcessedFileInfo,
    SkippedFileInfo,
)
from server.app.database.sql import execute_sql
from server.app.embed import jobs as jobs_mod

pytestmark = [pytest.mark.db, pytest.mark.integration]


@pytest.fixture
async def core_pool(embed_core_pool):
    """A live CORE pool wired into ``jobs.get_core_pool`` (see the shared
    ``embed_core_pool`` fixture in conftest). Aliased here so these tests can
    take ``core_pool`` and assert against the pinned pool object."""
    yield embed_core_pool


def _make_row(
    job_id: str,
    *,
    client: str = "itest",
    owner_pod: str = "pod-1",
    status: EmbedJobStatus = EmbedJobStatus.RUNNING,
    target_db: str = "CORE",
    progress: EmbedJobProgress | None = None,
) -> jobs_mod._JobRow:
    now = jobs_mod._utcnow()
    return jobs_mod._JobRow(
        job_id=job_id,
        client=client,
        owner_pod=owner_pod,
        status=status,
        target_db=target_db,
        progress=progress,
        created=now,
        updated=now,
    )


async def test_create_and_get_roundtrip(core_pool):
    """A created row reads back with its fields and JSON progress intact."""
    row = _make_row("it-create", progress=EmbedJobProgress(stage=EmbedJobStage.SPLITTING, total_chunks=4))
    await jobs_mod._store_create(row)

    got = await jobs_mod._store_get("it-create")
    assert got is not None
    assert got.client == "itest"
    assert got.status == EmbedJobStatus.RUNNING
    assert got.target_db == "CORE"
    assert got.progress is not None
    assert got.progress.stage == EmbedJobStage.SPLITTING
    assert got.progress.total_chunks == 4
    # Create pins the inserting pool for the job.
    assert jobs_mod._PINNED_POOLS.get("it-create") is core_pool


async def test_get_missing_returns_none(core_pool):
    """A get for an unknown job_id returns None (not an error)."""
    assert await jobs_mod._store_get("nope") is None


async def test_list_for_client_active_only_filters_terminal(core_pool):
    """``active_only`` returns only queued/running rows for the client."""
    await jobs_mod._store_create(_make_row("it-active", status=EmbedJobStatus.RUNNING))
    await jobs_mod._store_create(_make_row("it-done", status=EmbedJobStatus.RUNNING))
    await jobs_mod._store_set_result(
        "it-done",
        EmbedProcessingResult(message="ok", total_chunks=1, processed_files=[], skipped_files=[]),
    )

    active = await jobs_mod._store_list_for_client("itest", active_only=True)
    assert {r.job_id for r in active} == {"it-active"}

    every = await jobs_mod._store_list_for_client("itest", active_only=False)
    assert {r.job_id for r in every} == {"it-active", "it-done"}


async def test_set_progress_persists(core_pool):
    """A progress update round-trips through the JSON column."""
    await jobs_mod._store_create(_make_row("it-prog"))
    await jobs_mod._store_set_progress(
        "it-prog", EmbedJobProgress(stage=EmbedJobStage.EMBEDDING, message="midway", total_chunks=10)
    )

    got = await jobs_mod._store_get("it-prog")
    assert got is not None and got.progress is not None
    assert got.progress.stage == EmbedJobStage.EMBEDDING
    assert got.progress.message == "midway"
    assert got.progress.total_chunks == 10


async def test_set_status_running_to_failed(core_pool):
    """A failed terminal write records status + error and drops the pin."""
    await jobs_mod._store_create(_make_row("it-fail"))
    await jobs_mod._store_set_status("it-fail", EmbedJobStatus.FAILED, error="boom")

    got = await jobs_mod._store_get("it-fail")
    assert got is not None
    assert got.status == EmbedJobStatus.FAILED
    assert got.error == "boom"
    assert "it-fail" not in jobs_mod._PINNED_POOLS


async def test_set_result_running_to_succeeded_leaves_error_null(core_pool):
    """The success-path UPDATE moves running → succeeded with error still NULL.

    This is the ORA-00957 invariant exercised end-to-end through the store
    against real Oracle 23ai, not just a SQL-string assertion.
    """
    await jobs_mod._store_create(_make_row("it-ok"))
    await jobs_mod._store_set_result(
        "it-ok",
        EmbedProcessingResult(
            message="done",
            total_chunks=3,
            processed_files=[ProcessedFileInfo(filename="a.txt", chunks=3)],
            skipped_files=[SkippedFileInfo(filename="b.txt", reason="dup")],
        ),
    )

    got = await jobs_mod._store_get("it-ok")
    assert got is not None
    assert got.status == EmbedJobStatus.SUCCEEDED
    assert got.error is None
    assert got.result is not None
    assert [f.filename for f in got.result.processed_files] == ["a.txt"]
    assert [f.filename for f in got.result.skipped_files] == ["b.txt"]
    assert "it-ok" not in jobs_mod._PINNED_POOLS


async def test_terminal_state_is_final(core_pool):
    """A status write against an already-terminal row is a no-op (SQL guard)."""
    await jobs_mod._store_create(_make_row("it-final"))
    await jobs_mod._store_set_result(
        "it-final",
        EmbedProcessingResult(message="done", total_chunks=1, processed_files=[], skipped_files=[]),
    )
    # Late failure write from the original task must not overwrite success.
    await jobs_mod._store_set_status("it-final", EmbedJobStatus.FAILED, error="late")

    got = await jobs_mod._store_get("it-final")
    assert got is not None
    assert got.status == EmbedJobStatus.SUCCEEDED
    assert got.error is None


async def test_heartbeat_active_bumps_updated(core_pool):
    """Heartbeat refreshes ``updated`` for owned, non-terminal rows.

    The heartbeat writes ``updated = SYSTIMESTAMP`` (the *DB server* clock),
    while ``old`` below is a *host* clock value. To keep the assertion robust
    when the container clock and the host clock disagree, ``old`` sits days in
    the past — far enough that no realistic skew can invert the comparison.
    """
    await jobs_mod._store_create(_make_row("it-hb", owner_pod="pod-1"))
    old = jobs_mod._utcnow() - datetime.timedelta(days=2)
    await jobs_mod._test_force_updated("it-hb", old)

    bumped, hit_core = await jobs_mod._store_heartbeat_active("pod-1", ["it-hb"])
    assert bumped == 1
    assert hit_core is True

    got = await jobs_mod._store_get("it-hb")
    assert got is not None and got.updated > old


async def test_reap_stale_marks_failed(core_pool):
    """A stale running row is reaped to failed with the supplied error."""
    await jobs_mod._store_create(_make_row("it-reap"))
    # Forced ``updated`` (host clock) vs the reaper's SYSTIMESTAMP predicate
    # (DB clock): keep the staleness gap days-wide so host/container clock
    # skew can't push the row back inside the threshold window.
    await jobs_mod._test_force_updated("it-reap", jobs_mod._utcnow() - datetime.timedelta(days=2))

    reaped = await jobs_mod._store_reap_stale(threshold_seconds=60, error="stale")
    assert reaped >= 1

    got = await jobs_mod._store_get("it-reap")
    assert got is not None
    assert got.status == EmbedJobStatus.FAILED
    assert got.error == "stale"


async def test_delete_ttl_removes_old_terminal_rows(core_pool):
    """TTL delete drops terminal rows past the retention window."""
    await jobs_mod._store_create(_make_row("it-ttl"))
    await jobs_mod._store_set_result(
        "it-ttl",
        EmbedProcessingResult(message="done", total_chunks=1, processed_files=[], skipped_files=[]),
    )
    # Days-wide gap (host clock) keeps the TTL delete robust against
    # host/container clock skew vs the SYSTIMESTAMP retention predicate.
    await jobs_mod._test_force_updated("it-ttl", jobs_mod._utcnow() - datetime.timedelta(days=2))

    deleted = await jobs_mod._store_delete_ttl(ttl_seconds=60)
    assert deleted >= 1
    assert await jobs_mod._store_get("it-ttl") is None


async def test_missing_table_surfaces_as_db_error(core_pool):
    """A get against a dropped table raises (so the endpoint can 503), not None."""
    async with core_pool.acquire() as conn:
        conn.autocommit = True
        await execute_sql(conn, "DROP TABLE aio_embed_jobs")
        conn.autocommit = False
    with pytest.raises(oracledb.DatabaseError):
        await jobs_mod._store_get("anything")


async def test_oracle_job_store_used_directly(core_pool):
    """[refactor] ``OracleJobStore`` is independently usable against a real pool.

    Bypasses the ``_store_*`` dispatcher entirely — constructing the backend
    with a live container pool and driving create → get → set_result — so the
    Oracle implementation is validated as a unit in its own right.
    """
    store = jobs_mod.OracleJobStore(core_pool)

    await store.create(_make_row("it-direct", progress=EmbedJobProgress(stage=EmbedJobStage.INDEXING)))
    got = await store.get("it-direct")
    assert got is not None
    assert got.status == EmbedJobStatus.RUNNING
    assert got.progress is not None and got.progress.stage == EmbedJobStage.INDEXING

    await store.set_result(
        "it-direct",
        EmbedProcessingResult(message="ok", total_chunks=0, processed_files=[], skipped_files=[]),
    )
    done = await store.get("it-direct")
    assert done is not None and done.status == EmbedJobStatus.SUCCEEDED
