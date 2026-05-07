"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Background-job machinery for the long-running split-and-embed pipeline.

The /v1/embed/ pipeline (parse, chunk, embed, MERGE, build HNSW) is too
long-lived to run on the request thread — large corpora and cold
embedding models routinely exceed the LB / nginx idle timeout — so it
is scheduled as a background asyncio task and observed via a status
endpoint. This module owns the asyncio.Task handles plus the per-pod
heartbeat / reaper machinery; the persisted state lives in CORE
(``aio_embed_jobs``) so any replica can serve a GET regardless of
which pod accepted the POST.

Three correctness invariants this module is responsible for:

1. **Cross-replica visibility (P1).** Status reads always go through
   the shared store, never through a per-pod cache that another pod
   cannot see. The local task map is *only* used for cancellation.
2. **Crash recovery (P3).** The pod owning a running job heartbeats
   its rows; a periodic sweep on every pod marks rows whose heartbeat
   went stale as ``failed``. This terminates polling clients whose
   pod crashed mid-pipeline (the work directory is an emptyDir volume
   so a crashed pipeline cannot meaningfully be resumed elsewhere —
   failing it is the only correct outcome).
3. **Test ergonomics.** When CORE is unavailable (``get_core_pool()``
   returns None) the store falls back to a process-local dict so unit
   tests do not need a live database. Production deployments without
   CORE are already rejected at endpoint level, so this fallback is
   only ever exercised by tests.
"""

import asyncio
import contextlib
import dataclasses
import datetime
import json
import logging
import uuid
from collections import OrderedDict
from typing import Awaitable, Callable, Optional

import oracledb
from pydantic import BaseModel

from server.app.api.v1.schemas.embed import (
    EmbedJobInfo,
    EmbedJobProgress,
    EmbedJobStage,
    EmbedJobStatus,
    EmbedProcessingResult,
)
from server.app.database.config import get_core_pool
from server.app.database.sql import execute_sql

LOGGER = logging.getLogger(__name__)

# Defaults; production values can be tuned later via settings if needed.
_DEFAULT_HEARTBEAT_SECONDS = 30
_DEFAULT_REAP_THRESHOLD_SECONDS = 180
_DEFAULT_REAP_INTERVAL_SECONDS = 60
_DEFAULT_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Persisted-row representation
# ---------------------------------------------------------------------------


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class _JobRow(BaseModel):
    """Snapshot of one ``aio_embed_jobs`` row.

    Pydantic so it round-trips cleanly to/from the JSON columns. Holds
    *only* persisted state — the local asyncio.Task handle lives on
    :class:`JobSubmission` instead, since a Task is per-pod and is not
    serialisable across replicas.
    """

    job_id: str
    client: str
    owner_pod: str
    status: EmbedJobStatus
    # Alias of the database that holds the vector store this job is
    # populating. The database-update endpoint filters
    # ``aio_embed_jobs`` by this column to refuse rotations of an
    # alias still targeted by an in-flight job — without it, a
    # successful rotation closes the captured pool the pipeline is
    # still using for ``update_vs_comment`` / ``discover_vector_stores``,
    # leaving a populated table and a failed-status row.
    #
    # Default ``""`` keeps the field optional for unit tests that
    # don't exercise the rotation guard; production always sets it
    # via :meth:`EmbedJobManager.submit`.
    target_db: str = ""
    progress: Optional[EmbedJobProgress] = None
    result: Optional[EmbedProcessingResult] = None
    error: Optional[str] = None
    created: datetime.datetime
    updated: datetime.datetime

    def to_info(self) -> EmbedJobInfo:
        return EmbedJobInfo(
            job_id=self.job_id,
            status=self.status,
            created_at=self.created.isoformat(),
            updated_at=self.updated.isoformat(),
            progress=self.progress,
            result=self.result,
            error=self.error,
        )


@dataclasses.dataclass
class JobSubmission:
    """What :meth:`EmbedJobManager.submit` returns.

    Carries both the persisted identity (so the caller can build the
    202 response and tests can poll the row) and the local asyncio.Task
    handle (so callers can cancel or await completion in tests). Kept
    as a dataclass — not a Pydantic model — because :class:`asyncio.Task`
    is not a Pydantic-serialisable type and there is no value in
    serialising the submission record itself.
    """

    job_id: str
    status: EmbedJobStatus
    task: asyncio.Task


# ---------------------------------------------------------------------------
# In-memory fallback store (test ergonomics + degraded mode safety net)
# ---------------------------------------------------------------------------


_LOCAL_STORE: OrderedDict[str, _JobRow] = OrderedDict()
_LOCAL_LOCK = asyncio.Lock()


# Per-job CORE pool pin. Populated by ``_store_create`` when the
# INSERT succeeds against an actual pool, drained by terminal-state
# writes (``_store_set_status`` / ``_store_set_result``). Subsequent
# reads / writes for a pinned ``job_id`` route through the captured
# pool reference instead of ``get_core_pool()``.
#
# This protects against ``/v1/databases/CORE`` rotation while a job
# is in flight: without the pin, ``_store_get`` after rotation would
# look up the row in the *new* CORE database (likely empty) and
# polling clients would see 404 on a still-running job. The pin is
# per-job-id (not per-manager) so cross-replica reads on the same
# pod can still fall through to the live pool when this pod did not
# submit the job.
_PINNED_POOLS: dict[str, oracledb.AsyncConnectionPool] = {}


def _resolve_pool_for_job(job_id: str) -> Optional[oracledb.AsyncConnectionPool]:
    """Return the CORE pool tied to *job_id*, falling back to the live pool.

    When ``_store_create`` ran on this pod, the pool it used to insert
    the row is pinned in ``_PINNED_POOLS``; subsequent operations for
    the same ``job_id`` route back to that pinned reference so a
    concurrent CORE rotation cannot redirect them to a different
    database. For ``job_id``s this pod did not submit (cross-replica
    reads), no pin exists and the live pool is returned. That falls
    short of cross-replica visibility *during* a rotation but
    preserves the common sticky-routing case where the user's poll
    lands back on the submitting pod.
    """
    pinned = _PINNED_POOLS.get(job_id)
    if pinned is not None:
        return pinned
    return get_core_pool()


class _LocalFallback:
    """Toggle for the in-memory fallback path.

    Production code never flips this — the endpoint guards CORE
    availability up front, and a transient ``pool=None`` inside
    ``_store_create`` means the user's submission would otherwise
    live only in this pod's memory and break the cross-replica
    polling contract. ``reset_local_jobs_store`` flips it for tests
    so the pool-less unit tests in ``test_jobs.py`` keep functioning
    without a real Oracle. Class attribute rather than a module-level
    ``global`` so the toggle's mutation does not trip Pylint PLW0603.
    """

    allowed: bool = False


def reset_local_jobs_store() -> None:
    """Drop the in-memory fallback. Tests only.

    Calling this also enables the fallback path: only test code
    invokes this function, so production submissions never reach
    the fallback even if CORE briefly goes None between the
    endpoint's availability guard and ``_store_create``.
    """
    _LocalFallback.allowed = True
    _LOCAL_STORE.clear()
    _PINNED_POOLS.clear()


# ---------------------------------------------------------------------------
# SQL — kept here next to the row dataclass so a schema change touches one
# file rather than three. Bind variables only; never f-string user input.
# ---------------------------------------------------------------------------


_INSERT_SQL = """
INSERT INTO aio_embed_jobs
    (job_id, client, owner_pod, status, target_db, progress, created, updated)
VALUES
    (:job_id, :client, :owner_pod, :status, :target_db, :progress, SYSTIMESTAMP, SYSTIMESTAMP)
"""

# CORE-rotation guard: a row is "live" if it is queued/running OR
# terminal-but-still-readable (within the TTL window clients can
# poll). Terminal rows count because status/result reads route
# through CORE — rotating CORE during the TTL window would make
# them disappear (the per-job pool pin is dropped on terminal
# write, so the read falls through to the live CORE pool).
_UNEXPIRED_ROW_PREDICATE = (
    "status IN ('queued', 'running')"
    " OR (status IN ('succeeded', 'failed')"
    "     AND updated >= SYSTIMESTAMP - NUMTODSINTERVAL(:ttl_seconds, 'SECOND'))"
)

_COUNT_ACTIVE_SQL = f"SELECT COUNT(*) FROM aio_embed_jobs WHERE {_UNEXPIRED_ROW_PREDICATE}"

# Per-alias variant used by ``/v1/databases/{alias}`` (PUT/DELETE).
# Counts only running rows, NOT terminal ones — the guard exists
# because the pipeline holds a captured pool to the target alias
# during ``populate_vs`` and the post-populate comment / discovery
# step. That pool reference is dropped on terminal write, so a
# completed job is no longer using the target pool: rotating or
# removing the alias is then safe even within the row-retention
# TTL. (Terminal status reads come from CORE, not from the target
# database — those are protected by the CORE-side guard above.)
_COUNT_ACTIVE_BY_TARGET_SQL = (
    "SELECT COUNT(*) FROM aio_embed_jobs"
    " WHERE target_db = :target_db AND status IN ('queued', 'running')"
)

_SELECT_BY_ID_SQL = """
SELECT job_id, client, owner_pod, status, target_db, progress, result, error, created, updated
  FROM aio_embed_jobs
 WHERE job_id = :job_id
"""

_SELECT_BY_CLIENT_SQL = """
SELECT job_id, client, owner_pod, status, target_db, progress, result, error, created, updated
  FROM aio_embed_jobs
 WHERE client = :client
 ORDER BY created DESC
"""

# Lean variant for the polling status panel: skips terminal rows so
# the panel does not pull every still-tracked job's ``result`` blob
# (``processed_files`` / ``skipped_files``) on every 2-second tick.
# After a large embedding run those payloads can be hundreds of kB;
# filtering at the SQL level keeps the polling path inexpensive.
_SELECT_ACTIVE_BY_CLIENT_SQL = """
SELECT job_id, client, owner_pod, status, target_db, progress, result, error, created, updated
  FROM aio_embed_jobs
 WHERE client = :client
   AND status IN ('queued', 'running')
 ORDER BY created DESC
"""

# Each update path is a small targeted statement rather than a single
# generic UPDATE — Oracle's bind variable handling for nullable JSON
# columns is touchy, and small statements make intent obvious in logs.
#
# Status / result writes are guarded by ``status IN ('queued','running')``
# so a reaper that already terminated a stranded row is not
# overwritten by a late finish from the original task. Without that
# guard a clients-saw-then-saw-different sequence would be possible:
# (heartbeat outage → reaper marks failed → polling client observes
# failed) → (event-loop unblocks → original task writes succeeded →
# polling client now observes succeeded). Once the row has reached a
# terminal state, that state is final.
_UPDATE_STATUS_SQL = """
UPDATE aio_embed_jobs
   SET status = :status,
       error  = :error,
       updated = SYSTIMESTAMP
 WHERE job_id = :job_id
   AND status IN ('queued', 'running')
"""

_UPDATE_PROGRESS_SQL = """
UPDATE aio_embed_jobs
   SET progress = :progress,
       updated  = SYSTIMESTAMP
 WHERE job_id = :job_id
"""

_UPDATE_RESULT_SQL = """
UPDATE aio_embed_jobs
   SET status  = :status,
       result  = :result,
       updated = SYSTIMESTAMP
 WHERE job_id = :job_id
   AND status IN ('queued', 'running')
"""
# Note: this UPDATE intentionally does *not* touch ``error``. A row
# transitioning queued/running → succeeded has never had ``error``
# set (only the failed-status path writes that column). Oracle 23ai
# rejected the previous shape — which also included ``error = NULL``
# — with ORA-00957 on real schemas, so every successful terminal
# write fell through to ``_terminal_write_with_retry`` and was
# eventually abandoned, leaving a fully-populated vector store with
# its row stuck at ``running`` until the reaper marked it failed.

_HEARTBEAT_SQL = """
UPDATE aio_embed_jobs
   SET updated = SYSTIMESTAMP
 WHERE owner_pod = :owner_pod
   AND job_id = :job_id
   AND status IN ('queued', 'running')
"""

_REAP_SQL = """
UPDATE aio_embed_jobs
   SET status = 'failed',
       error  = :error,
       updated = SYSTIMESTAMP
 WHERE status IN ('queued', 'running')
   AND updated < SYSTIMESTAMP - NUMTODSINTERVAL(:threshold_seconds, 'SECOND')
"""

_DELETE_TTL_SQL = """
DELETE FROM aio_embed_jobs
 WHERE status IN ('succeeded', 'failed')
   AND updated < SYSTIMESTAMP - NUMTODSINTERVAL(:ttl_seconds, 'SECOND')
"""


# ---------------------------------------------------------------------------
# DB / in-memory abstraction. Each function picks a path based on whether
# CORE is available; behaviour matches between the two so tests exercise
# the same observable contract as production.
# ---------------------------------------------------------------------------


def _row_from_db(row: tuple) -> _JobRow:
    """Inflate a DB tuple into a :class:`_JobRow`."""
    (
        job_id,
        client,
        owner_pod,
        status,
        target_db,
        progress,
        result,
        error,
        created,
        updated,
    ) = row
    progress_data = json.loads(progress) if isinstance(progress, str) else progress
    result_data = json.loads(result) if isinstance(result, str) else result
    return _JobRow(
        job_id=job_id,
        client=client,
        owner_pod=owner_pod,
        status=EmbedJobStatus(status),
        target_db=target_db,
        progress=EmbedJobProgress.model_validate(progress_data) if progress_data else None,
        result=EmbedProcessingResult.model_validate(result_data) if result_data else None,
        error=error,
        created=created if created.tzinfo else created.replace(tzinfo=datetime.timezone.utc),
        updated=updated if updated.tzinfo else updated.replace(tzinfo=datetime.timezone.utc),
    )


async def _store_create(row: _JobRow) -> None:
    pool = get_core_pool()
    if pool is None:
        if not _LocalFallback.allowed:
            # Production: CORE was cleared between the endpoint's
            # availability guard and this call. Refusing to fall back
            # to per-process memory keeps the cross-replica polling
            # contract honest — the endpoint converts this to 503 so
            # the client retries.
            raise EmbedJobStoreUnavailable(
                "Job state store is unavailable for this operation."
            )
        async with _LOCAL_LOCK:
            _LOCAL_STORE[row.job_id] = row
        return
    progress_payload = row.progress.model_dump(mode="json") if row.progress else None
    binds = {
        "job_id": row.job_id,
        "client": row.client,
        "owner_pod": row.owner_pod,
        "status": row.status.value,
        "target_db": row.target_db,
        "progress": progress_payload,
    }
    async with pool.acquire() as conn:
        # Bypass ``execute_sql`` for this INSERT so ORA-00942 (table or
        # view does not exist) is not silently swallowed. Otherwise a
        # missing ``aio_embed_jobs`` table would let POST /v1/embed/
        # return 202 with no persisted row, and later polls would 404
        # instead of receiving the documented retry-able 503. We also
        # check ``rowcount`` to catch any other path that drops the
        # write without raising.
        async with conn.cursor() as cursor:
            cursor.setinputsizes(progress=oracledb.DB_TYPE_JSON)
            await cursor.execute(_INSERT_SQL, binds)
            if (cursor.rowcount or 0) != 1:
                raise EmbedJobStoreUnavailable(
                    f"INSERT into aio_embed_jobs affected "
                    f"{cursor.rowcount} rows; expected 1 for {row.job_id}"
                )
        await conn.commit()
    # Pin the pool that accepted the INSERT so subsequent reads /
    # writes for this ``job_id`` route back here even if
    # ``/v1/databases/CORE`` is rotated mid-job. Without this, a
    # later ``_store_get`` would resolve to the new CORE pool, find
    # nothing, and polling clients would see a 404 on a still-
    # running job. Released by the terminal-state writers.
    _PINNED_POOLS[row.job_id] = pool


async def _read_lob_safe_rows(cursor) -> list[tuple]:
    """Drain *cursor* with the same LOB-read semantics as ``execute_sql``.

    Used in place of ``execute_sql`` for SELECTs against
    ``aio_embed_jobs`` so that ORA-00942 (table or view does not
    exist) is *not* silently swallowed — a missing table on read
    must surface as ``oracledb.Error`` so the endpoint can return
    503 instead of pretending the row was simply absent.
    """
    batch = await cursor.fetchall()
    out: list[tuple] = []
    for row in batch:
        cols = []
        for val in row:
            cols.append(await val.read() if isinstance(val, oracledb.AsyncLOB) else val)
        out.append(tuple(cols))
    return out


async def _store_get(job_id: str) -> Optional[_JobRow]:
    # Route through the per-job pin so a CORE rotation mid-flight
    # cannot redirect this read to a different (likely empty)
    # database. Falls through to ``get_core_pool()`` for cross-
    # replica reads where this pod did not submit the job.
    pool = _resolve_pool_for_job(job_id)
    if pool is None:
        if not _LocalFallback.allowed:
            # Production: pool was cleared between the endpoint's
            # ``_require_core_pool`` guard and this read. Falling back
            # to ``_LOCAL_STORE`` (which production never writes to)
            # would silently report a real, persisted job as 404 —
            # polling clients only retry on 503, so a 404 makes them
            # stop polling for a job that may still be running. Raise
            # so the endpoint surfaces the documented retry-able 503.
            raise EmbedJobStoreUnavailable(
                f"Job state store is unavailable for this operation (job {job_id})."
            )
        async with _LOCAL_LOCK:
            return _LOCAL_STORE.get(job_id)
    # Bypass ``execute_sql`` so ORA-00942 propagates instead of being
    # swallowed and returned as ``None`` (which would look like
    # "no such job" — a 404 the polling client treats as terminal,
    # rather than the documented retry-able 503).
    async with pool.acquire() as conn, conn.cursor() as cursor:
        await cursor.execute(_SELECT_BY_ID_SQL, {"job_id": job_id})
        rows = await _read_lob_safe_rows(cursor)
    if not rows:
        return None
    return _row_from_db(rows[0])


_ACTIVE_STATUSES_FOR_FILTER = frozenset({EmbedJobStatus.QUEUED, EmbedJobStatus.RUNNING})


async def _store_list_for_client(client: str, active_only: bool = False) -> list[_JobRow]:
    pool = get_core_pool()
    if pool is None:
        if not _LocalFallback.allowed:
            # Same rationale as ``_store_get``: a fallback to the
            # empty in-memory store would imply "this client has no
            # jobs" even though jobs may already exist in CORE that
            # we just can't reach. Surface ``EmbedJobStoreUnavailable``
            # so the endpoint returns 503 instead of an empty list.
            raise EmbedJobStoreUnavailable(
                f"Job state store is unavailable for this operation (client {client})."
            )
        async with _LOCAL_LOCK:
            rows = [r for r in _LOCAL_STORE.values() if r.client == client]
            if active_only:
                rows = [r for r in rows if r.status in _ACTIVE_STATUSES_FOR_FILTER]
            return rows
    # Same rationale as ``_store_get``: a missing or inaccessible
    # table must surface so the endpoint returns 503 rather than an
    # empty list that implies "this client has no jobs".
    sql = _SELECT_ACTIVE_BY_CLIENT_SQL if active_only else _SELECT_BY_CLIENT_SQL
    async with pool.acquire() as conn, conn.cursor() as cursor:
        await cursor.execute(sql, {"client": client})
        rows = await _read_lob_safe_rows(cursor)
    return [_row_from_db(r) for r in rows]


async def _store_set_progress(job_id: str, progress: EmbedJobProgress) -> None:
    # Route through the per-job pin so progress writes target the
    # CORE that holds the row, not a rotated-in replacement.
    pool = _resolve_pool_for_job(job_id)
    if pool is None:
        async with _LOCAL_LOCK:
            row = _LOCAL_STORE.get(job_id)
            if row is None:
                return
            row.progress = progress
            row.updated = _utcnow()
        return
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            _UPDATE_PROGRESS_SQL,
            {"job_id": job_id, "progress": progress.model_dump(mode="json")},
            input_sizes={"progress": oracledb.DB_TYPE_JSON},
        )
        await conn.commit()


class EmbedJobStoreUnavailable(RuntimeError):
    """Raised when a terminal write cannot reach the persisted row.

    The job was originally inserted while CORE was up, but the pool is
    now ``None`` (config reload, transient outage). Falling back to
    ``_LOCAL_STORE`` would silently drop the terminal state because the
    row was never replicated there. ``_terminal_write_with_retry``
    catches this as a transient failure and re-attempts; if CORE comes
    back, the next attempt goes through the DB path normally.
    """


class JobFailure(Exception):
    """Controlled pipeline failure with a user-meaningful detail.

    Recorded verbatim on the job row; surfaced via the GET status
    endpoint. Caught separately from generic ``Exception`` so that
    expected failures don't emit a traceback log.
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


async def _store_set_status(job_id: str, status: EmbedJobStatus, error: Optional[str]) -> None:
    # Route through the per-job pin so terminal writes target the
    # CORE that holds the row. Without this, a status write after
    # ``/v1/databases/CORE`` rotation would land on the new (empty)
    # database, the original row would stay at ``running`` forever,
    # and the reaper would eventually mark it failed against the
    # wrong DB.
    pool = _resolve_pool_for_job(job_id)
    if pool is None:
        async with _LOCAL_LOCK:
            row = _LOCAL_STORE.get(job_id)
            if row is None:
                # The row was created via the DB path but the pool is
                # gone now — silently returning would let the caller
                # think this terminal write succeeded. Raise so the
                # retry helper waits for the pool to come back.
                raise EmbedJobStoreUnavailable(
                    f"CORE pool unavailable while updating status for embed job {job_id}"
                )
            # Mirror the SQL guard: terminal rows are final.
            if row.status not in (EmbedJobStatus.QUEUED, EmbedJobStatus.RUNNING):
                return
            row.status = status
            row.error = error
            row.updated = _utcnow()
        if status in (EmbedJobStatus.SUCCEEDED, EmbedJobStatus.FAILED):
            _PINNED_POOLS.pop(job_id, None)
        return
    # Bypass ``execute_sql`` so ORA-00942 / ORA-00955 propagate
    # instead of being swallowed. Otherwise the retry helper would
    # treat a silently-dropped UPDATE as a successful terminal write,
    # ``_run`` would pop ``_tasks``, and the reaper would mark the
    # row failed even though the pipeline reached a terminal state.
    async with pool.acquire() as conn, conn.cursor() as cursor:
        await cursor.execute(
            _UPDATE_STATUS_SQL,
            {"job_id": job_id, "status": status.value, "error": error},
        )
        await conn.commit()
    # Drop the per-job pool pin once the row reaches a terminal
    # state. Long-lived pods would otherwise accumulate references
    # to pools that have since been replaced, blocking GC of the
    # old pool and its underlying connections.
    if status in (EmbedJobStatus.SUCCEEDED, EmbedJobStatus.FAILED):
        _PINNED_POOLS.pop(job_id, None)


async def _store_set_result(job_id: str, result: EmbedProcessingResult) -> None:
    # See ``_store_set_status`` for the per-job pin rationale.
    pool = _resolve_pool_for_job(job_id)
    if pool is None:
        async with _LOCAL_LOCK:
            row = _LOCAL_STORE.get(job_id)
            if row is None:
                # See ``_store_set_status``: missing locally + no pool
                # means the row only lives in CORE and we cannot reach
                # it. Raise so the retry helper waits for CORE to
                # recover instead of dropping the success silently.
                raise EmbedJobStoreUnavailable(
                    f"CORE pool unavailable while writing result for embed job {job_id}"
                )
            # Mirror the SQL guard: terminal rows are final.
            if row.status not in (EmbedJobStatus.QUEUED, EmbedJobStatus.RUNNING):
                return
            row.status = EmbedJobStatus.SUCCEEDED
            row.result = result
            row.error = None
            row.updated = _utcnow()
        _PINNED_POOLS.pop(job_id, None)
        return
    # See ``_store_set_status`` — same rationale for bypassing the
    # swallow. A successful pipeline must not be silently downgraded
    # to "failed/orphaned" because the status table briefly went
    # missing or lost privileges.
    async with pool.acquire() as conn, conn.cursor() as cursor:
        cursor.setinputsizes(result=oracledb.DB_TYPE_JSON)
        await cursor.execute(
            _UPDATE_RESULT_SQL,
            {
                "job_id": job_id,
                "status": EmbedJobStatus.SUCCEEDED.value,
                "result": result.model_dump(mode="json"),
            },
        )
        await conn.commit()
    # ``_store_set_result`` always transitions to SUCCEEDED — drop
    # the per-job pool pin so a long-lived pod does not accumulate
    # references to pools that may since have been replaced.
    _PINNED_POOLS.pop(job_id, None)


async def _store_heartbeat_active(
    owner_pod: str,
    job_ids: list[str],
) -> tuple[int, bool]:
    """Bump ``updated`` for non-terminal rows whose tasks are still alive.

    Restricted to *job_ids* explicitly so a row whose local task has
    exited — e.g. because the terminal-state write raised after
    ``coro_factory`` returned — is *not* refreshed and the reaper can
    eventually mark it failed. Without this guard the row would be
    heartbeated forever and clients would poll indefinitely.

    Returns ``(bumped, hit_core)``. ``hit_core`` is True only when a
    CORE round-trip was actually performed. The manager uses
    ``hit_core`` to decide whether to advance its warmup-gate
    timestamps — a heartbeat that didn't validate CORE health must
    not warm the reaper, otherwise an idle replica would stay warm
    throughout a CORE outage and reap live jobs owned by other
    replicas as soon as CORE returned.

    Even when *job_ids* is empty, the DB-backed path performs a CORE
    round-trip (``SELECT 1 FROM DUAL``) so a failed acquire / SELECT
    bubbles up and ``hit_core`` stays False. The in-memory test path
    (pool is None) returns ``hit_core=False`` regardless — tests
    that rely on the warmup gate seed timestamps directly via
    ``_prime_heartbeat`` instead of routing through this helper.
    """
    pool = get_core_pool()
    if pool is None:
        if not job_ids:
            return 0, False
        bumped = 0
        active = set(job_ids)
        async with _LOCAL_LOCK:
            now = _utcnow()
            for row in _LOCAL_STORE.values():
                if (
                    row.owner_pod == owner_pod
                    and row.job_id in active
                    and row.status in (EmbedJobStatus.QUEUED, EmbedJobStatus.RUNNING)
                ):
                    row.updated = now
                    bumped += 1
        return bumped, False
    async with pool.acquire() as conn:
        if not job_ids:
            await execute_sql(conn, "SELECT 1 FROM DUAL")
            return 0, True
        binds = [{"owner_pod": owner_pod, "job_id": jid} for jid in job_ids]
        async with conn.cursor() as cursor:
            # ``executemany`` issues N statements in one round-trip and
            # accumulates the affected-row count across them.
            await cursor.executemany(_HEARTBEAT_SQL, binds)
            count = cursor.rowcount
        await conn.commit()
    return count or 0, True


async def _store_reap_stale(threshold_seconds: int, error: str) -> int:
    """Mark non-terminal rows older than *threshold_seconds* as failed."""
    pool = get_core_pool()
    if pool is None:
        reaped = 0
        async with _LOCAL_LOCK:
            cutoff = _utcnow() - datetime.timedelta(seconds=threshold_seconds)
            for row in _LOCAL_STORE.values():
                if row.status in (EmbedJobStatus.QUEUED, EmbedJobStatus.RUNNING) and row.updated < cutoff:
                    row.status = EmbedJobStatus.FAILED
                    row.error = error
                    row.updated = _utcnow()
                    reaped += 1
        return reaped
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                _REAP_SQL,
                {"error": error, "threshold_seconds": threshold_seconds},
            )
            count = cursor.rowcount
        await conn.commit()
    return count or 0


async def _store_delete_ttl(ttl_seconds: int) -> int:
    """Delete terminal rows older than *ttl_seconds* — bounded retention."""
    pool = get_core_pool()
    if pool is None:
        async with _LOCAL_LOCK:
            cutoff = _utcnow() - datetime.timedelta(seconds=ttl_seconds)
            stale = [
                jid
                for jid, row in _LOCAL_STORE.items()
                if row.status in (EmbedJobStatus.SUCCEEDED, EmbedJobStatus.FAILED)
                and row.updated < cutoff
            ]
            for jid in stale:
                _LOCAL_STORE.pop(jid, None)
        return len(stale)
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(_DELETE_TTL_SQL, {"ttl_seconds": ttl_seconds})
            count = cursor.rowcount
        await conn.commit()
    return count or 0


# ---------------------------------------------------------------------------
# Terminal-write retry. ``populate_vs`` commits before this runs, so a
# transient CORE blip on the success path would otherwise turn a
# successful job into one the reaper marks ``failed`` (heartbeat lost).
# A small bounded retry absorbs the common transient case; if every
# attempt fails the row stays non-terminal, ``_tasks`` still gets
# popped by ``_run``'s ``finally``, and the reaper takes over — at
# least the operator gets a loud log line to investigate.
# ---------------------------------------------------------------------------


_TERMINAL_WRITE_ATTEMPTS = 5
_TERMINAL_WRITE_INITIAL_DELAY = 0.5
_TERMINAL_WRITE_MAX_DELAY = 5.0


async def _terminal_write_with_retry(
    kind: str,
    job_id: str,
    do_write: Callable[[], Awaitable[None]],
) -> None:
    """Run *do_write* with bounded exponential backoff on failure.

    *kind* is just a label for log messages (``"succeed"`` /
    ``"fail"``). Cancellation is never retried — propagated immediately
    so a shutdown isn't delayed by retry sleeps.
    """
    delay = _TERMINAL_WRITE_INITIAL_DELAY
    last_exc: Optional[BaseException] = None
    for attempt in range(1, _TERMINAL_WRITE_ATTEMPTS + 1):
        try:
            await do_write()
            return
        except asyncio.CancelledError:
            raise
        except Exception as ex:  # noqa: BLE001 — bounded-retry path
            last_exc = ex
            LOGGER.warning(
                "Embed job %s: %s terminal write attempt %d/%d failed: %s",
                job_id,
                kind,
                attempt,
                _TERMINAL_WRITE_ATTEMPTS,
                ex,
            )
            if attempt < _TERMINAL_WRITE_ATTEMPTS:
                await asyncio.sleep(delay)
                delay = min(delay * 2, _TERMINAL_WRITE_MAX_DELAY)
    LOGGER.error(
        "Embed job %s: %s terminal write failed after %d attempts; row will "
        "remain non-terminal until reaper marks it failed. Last error: %s",
        job_id,
        kind,
        _TERMINAL_WRITE_ATTEMPTS,
        last_exc,
    )


# ---------------------------------------------------------------------------
# Test-only helper — backdate a row so reap-stale can be exercised
# deterministically without sleeping.
# ---------------------------------------------------------------------------


async def _test_force_updated(job_id: str, when: datetime.datetime) -> None:
    """Set the ``updated`` timestamp on *job_id* directly. Tests only."""
    pool = get_core_pool()
    if pool is None:
        async with _LOCAL_LOCK:
            row = _LOCAL_STORE.get(job_id)
            if row is not None:
                row.updated = when
        return
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            "UPDATE aio_embed_jobs SET updated = :when WHERE job_id = :job_id",
            {"when": when, "job_id": job_id},
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Public façade: JobHandle + EmbedJobManager
# ---------------------------------------------------------------------------


class JobHandle:
    """Async-safe surface a running pipeline uses to report progress."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    async def set_progress(
        self,
        stage: EmbedJobStage,
        message: Optional[str] = None,
        total_chunks: Optional[int] = None,
    ) -> None:
        """Record stage progress.

        Best-effort: a transient CORE write failure must not abort an
        otherwise-valid pipeline. Progress is telemetry — the polling
        client may briefly see a stale stage, but the embedding work
        itself proceeds and the terminal-state write transitions the
        row normally.
        """
        progress = EmbedJobProgress(stage=stage, message=message, total_chunks=total_chunks)
        try:
            await _store_set_progress(self.job_id, progress)
        except Exception:  # noqa: BLE001 — telemetry failure must not abort pipeline
            LOGGER.warning(
                "Failed to write progress for embed job %s — pipeline continues",
                self.job_id,
                exc_info=True,
            )


class EmbedJobManager:
    """Per-pod façade around the shared ``aio_embed_jobs`` store.

    The asyncio.Task handle is the only piece kept locally — every other
    read/write goes through the store, which means a sibling replica
    (``EmbedJobManager(pod_id="other")``) sees the exact same state.
    """

    def __init__(self, pod_id: Optional[str] = None):
        # Each replica picks a stable per-process id; in production this
        # is a fresh uuid per pod-startup so a restarted pod never
        # confuses its old in-flight jobs with new ones.
        self.pod_id = pod_id or uuid.uuid4().hex
        self._tasks: dict[str, asyncio.Task] = {}
        self._tasks_lock = asyncio.Lock()
        # Heartbeat warmup history. ``reap_stale`` consults the most
        # recent two timestamps to confirm the heartbeat is healthy
        # before sweeping — see ``_is_heartbeat_warm`` for why.
        self._last_heartbeat_at: Optional[datetime.datetime] = None
        self._previous_heartbeat_at: Optional[datetime.datetime] = None

    async def submit(
        self,
        client: str,
        coro_factory: Callable[[JobHandle], Awaitable[EmbedProcessingResult]],
        *,
        target_db: str = "",
    ) -> JobSubmission:
        """Persist a new job row and schedule its coroutine on this pod.

        ``target_db`` is the alias of the database whose vector store
        this job will populate. It is recorded on the row so the
        database-update endpoint can refuse rotations of an alias
        that is still targeted by an in-flight job (the captured
        pool would otherwise be closed mid-pipeline). Keyword-only
        with a default of ``""`` so unit tests that don't exercise
        the rotation guard don't have to pass it; production code
        path in ``split_embed`` always sets it to the captured
        ``db_config.alias``.

        Returns a :class:`JobSubmission` carrying the freshly-allocated
        ``job_id``, the initial ``status``, and the local
        :class:`asyncio.Task` handle (so callers can cancel / await it).
        """
        job_id = uuid.uuid4().hex
        now = _utcnow()
        row = _JobRow(
            job_id=job_id,
            client=client,
            owner_pod=self.pod_id,
            status=EmbedJobStatus.QUEUED,
            target_db=target_db,
            progress=EmbedJobProgress(stage=EmbedJobStage.QUEUED),
            created=now,
            updated=now,
        )
        await _store_create(row)
        handle = JobHandle(job_id)
        # No await between ``create_task`` and the dict insert: a
        # cancellation here would otherwise leave ``_run`` running
        # but unknown to ``_tasks``. Single ``__setitem__`` is atomic
        # in single-threaded asyncio, so the lock is unnecessary
        # (``_tasks_lock`` only guards multi-step iteration elsewhere).
        task = asyncio.create_task(self._run(handle, coro_factory))
        self._tasks[job_id] = task
        return JobSubmission(job_id=job_id, status=row.status, task=task)

    async def _run(
        self,
        handle: JobHandle,
        coro_factory: Callable[[JobHandle], Awaitable[EmbedProcessingResult]],
    ) -> None:
        # Outer try/finally guarantees ``_tasks`` is popped no matter
        # how ``_run`` exits — including ``CancelledError`` raised
        # while awaiting the initial RUNNING write below, which would
        # otherwise bypass the inner ``except Exception`` and leave a
        # stale entry in ``_tasks`` that the heartbeat would refresh
        # forever.
        try:
            # The RUNNING write is best-effort: if it raises (e.g.
            # transient CORE blip) we still want the pipeline body to
            # execute so the work_dir cleanup in its ``finally`` runs.
            # The terminal-state write below is retried before being
            # suppressed — see ``_terminal_write_with_retry`` for why.
            try:
                await _store_set_status(handle.job_id, EmbedJobStatus.RUNNING, error=None)
            except asyncio.CancelledError:
                # Cancellation here means we never started the pipeline
                # body; leaving the row at ``queued`` is fine because the
                # outer finally pops ``_tasks`` so the heartbeat stops
                # covering it and the reaper takes over.
                raise
            except Exception:  # noqa: BLE001 — best-effort status write
                LOGGER.exception(
                    "Failed to mark embed job %s as RUNNING; running pipeline anyway",
                    handle.job_id,
                )
            # Cancellation must propagate into the pipeline so an
            # async-cancellable await (DB call, event waiter, etc.)
            # actually stops — shielding the inner Task and waiting
            # for it instead would convert every cancel into "wait
            # for natural completion" and hang teardown indefinitely.
            #
            # Trade-off acknowledged: ``Task.cancel()`` cannot
            # interrupt a worker thread already running inside
            # ``asyncio.to_thread`` (Python's executor doesn't
            # support thread cancellation). The asyncio Future
            # wrapping the to_thread call is cancelled but the
            # thread runs to natural completion, so a terminal
            # "Job cancelled." may be written while a thread is
            # still mid-read or mid-write. Closing that gap fully
            # would require the pipeline body to track its own
            # ``run_in_executor`` futures and join them on
            # cancellation; out of scope for this layer.
            try:
                result = await coro_factory(handle)
            except asyncio.CancelledError:
                await _terminal_write_with_retry(
                    "fail",
                    handle.job_id,
                    lambda: _store_set_status(
                        handle.job_id, EmbedJobStatus.FAILED, error="Job cancelled."
                    ),
                )
                raise
            except JobFailure as ex:
                # Pipeline-authored detail (already passed through
                # ``response_error_detail`` for source-detail normalization).
                # Capture the detail into a local before the lambda —
                # ``ex`` goes out of scope after the ``except`` block.
                detail = ex.detail
                await _terminal_write_with_retry(
                    "fail",
                    handle.job_id,
                    lambda detail=detail: _store_set_status(
                        handle.job_id, EmbedJobStatus.FAILED, error=detail
                    ),
                )
            except Exception as ex:  # noqa: BLE001 — terminal-state recorder
                LOGGER.exception("Embed job %s failed", handle.job_id)
                error_msg = str(ex) or type(ex).__name__
                await _terminal_write_with_retry(
                    "fail",
                    handle.job_id,
                    lambda error_msg=error_msg: _store_set_status(
                        handle.job_id,
                        EmbedJobStatus.FAILED,
                        error=error_msg,
                    ),
                )
            else:
                await _terminal_write_with_retry(
                    "succeed",
                    handle.job_id,
                    lambda: _store_set_result(handle.job_id, result),
                )
        finally:
            async with self._tasks_lock:
                self._tasks.pop(handle.job_id, None)

    def discard_local_task(self, job_id: str) -> None:
        """Drop the per-pod task entry for *job_id* if present.

        Idempotent. Used by the request handler when a task was
        registered via :meth:`submit` but cancelled before its
        first event-loop step — ``_run``'s outer ``finally`` would
        normally pop the entry, but a fresh-task ``Task.cancel()``
        throws ``CancelledError`` BEFORE any code in ``_run`` runs
        (including the surrounding ``try``), so the finally never
        fires. Without an explicit pop here the heartbeat would
        keep refreshing the QUEUED row indefinitely and the reaper
        would never sweep it.

        Safe to call without ``_tasks_lock``: dict ``pop`` is
        atomic in single-threaded asyncio. The lock only guards
        multi-step blocks (e.g. snapshotting keys for the
        heartbeat).
        """
        self._tasks.pop(job_id, None)

    async def get(self, client: str, job_id: str) -> Optional[_JobRow]:
        """Return *job_id* iff it exists and belongs to *client*.

        Reads always go through the store so a poll routed to a sibling
        pod returns the same answer as one to the owning pod.
        """
        row = await _store_get(job_id)
        if row is None or row.client != client:
            return None
        return row

    async def list_for_client(self, client: str, active_only: bool = False) -> list[_JobRow]:
        return await _store_list_for_client(client, active_only=active_only)

    # -- crash-recovery primitives -----------------------------------------

    async def heartbeat_owned(self) -> int:
        """Bump ``updated`` for rows whose local task is still alive.

        Keying the heartbeat on ``self._tasks`` rather than just
        ``owner_pod`` is what makes the reaper effective: a row stranded
        at ``running`` because its terminal-state write failed will not
        be refreshed (its task entry was popped in ``_run``'s finally)
        so its ``updated`` ages out and the reaper marks it failed.

        Records the success timestamp into a 2-slot history that
        ``reap_stale`` consults for its warmup gate — but only when
        ``_store_heartbeat_active`` reports an actual CORE round-trip.
        A pool-less invocation (CORE outage, or unit-test fallback)
        does not advance the warmup signal; otherwise an idle replica
        would stay warm throughout a CORE outage and the moment CORE
        returned its reaper would mark live jobs owned by other
        replicas ``failed`` before any owner heartbeat caught up.
        """
        async with self._tasks_lock:
            active = list(self._tasks.keys())
        bumped, hit_core = await _store_heartbeat_active(self.pod_id, active)
        if hit_core:
            self._previous_heartbeat_at = self._last_heartbeat_at
            self._last_heartbeat_at = _utcnow()
        return bumped

    def _is_heartbeat_warm(self, heartbeat_interval: int = _DEFAULT_HEARTBEAT_SECONDS) -> bool:
        """True iff the pod has had two recent on-schedule heartbeats AND
        the most recent one is itself recent.

        After a CORE outage longer than the reap threshold, every live
        job's row looks stale because heartbeats couldn't refresh it.
        If the reaper fires immediately on CORE recovery, it will mark
        active jobs ``failed`` before the heartbeat catches up, and
        the terminal-state guard prevents the original task from
        flipping the row back to ``succeeded`` later. Two checks
        together close the loophole:

        * **gap** — ``last`` and ``prev`` must be within one heartbeat
          interval of each other, i.e. they straddle a normal cycle of
          operation. Without this, a single post-recovery heartbeat
          plus an old pre-outage one would qualify as warm.
        * **recency** — ``last`` itself must be within the same window.
          Without this, two old normal-gap heartbeats would qualify
          forever, including throughout a long CORE outage during
          which no successful heartbeat happened. As soon as CORE
          returned, the reaper would fire on the next loop tick and
          mark live jobs failed before any owner heartbeat refreshed
          their rows.
        """
        last = self._last_heartbeat_at
        prev = self._previous_heartbeat_at
        if last is None or prev is None:
            return False
        if (last - prev).total_seconds() >= heartbeat_interval * 2:
            return False
        # ``last`` itself must be recent — a successful round-trip
        # within the warmup window. This is what closes the gate
        # during an ongoing CORE outage.
        return (_utcnow() - last).total_seconds() < heartbeat_interval * 2

    async def reap_stale(
        self,
        threshold_seconds: int = _DEFAULT_REAP_THRESHOLD_SECONDS,
        error: str = "Job orphaned: pod heartbeat lost.",
    ) -> int:
        """Mark non-terminal rows whose heartbeat went stale as failed.

        Skipped while the heartbeat is in warmup — see
        :meth:`_is_heartbeat_warm`. Returns 0 on a skipped round so
        callers can still log "reaper ran" without misreporting.
        """
        if not self._is_heartbeat_warm():
            LOGGER.debug(
                "Skipping reap on pod %s: heartbeat warmup gate not satisfied "
                "(last=%s, previous=%s)",
                self.pod_id,
                self._last_heartbeat_at,
                self._previous_heartbeat_at,
            )
            return 0
        return await _store_reap_stale(threshold_seconds, error)

    async def delete_terminal_ttl(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> int:
        """Drop terminal rows older than *ttl_seconds*."""
        return await _store_delete_ttl(ttl_seconds)

    async def cancel_local(self, job_id: str) -> bool:
        """Cancel a task this pod owns. Returns True if cancellation was issued."""
        async with self._tasks_lock:
            task = self._tasks.get(job_id)
        if task is None:
            return False
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        return True


# ---------------------------------------------------------------------------
# Module singleton — wired into the FastAPI app via dependency lookup.
#
# A class attribute holder rather than a module-level ``global`` so the
# singleton's mutation does not trip Pylint PLW0603 — same observable
# behaviour, lint-clean.
# ---------------------------------------------------------------------------


class _ManagerHolder:
    instance: Optional[EmbedJobManager] = None


def get_embed_job_manager() -> EmbedJobManager:
    """Lazy singleton (one per process / pod)."""
    if _ManagerHolder.instance is None:
        _ManagerHolder.instance = EmbedJobManager()
    return _ManagerHolder.instance


def reset_embed_job_manager() -> None:
    """Drop the singleton — only for tests / shutdown."""
    _ManagerHolder.instance = None


# ---------------------------------------------------------------------------
# Cross-module helper: active-job count.
#
# Used by the database-update endpoint to refuse a CORE rotation while
# embed jobs are still in flight. Without that guard, rotating CORE
# closes the previous pool — and the per-job pool pin in
# ``_PINNED_POOLS`` keeps routing reads / terminal writes through it,
# so polling clients see CORE errors and a successful pipeline can be
# left non-terminal forever. By blocking the rotation until non-
# terminal rows are gone, the pin remains valid for the whole job
# lifecycle.
# ---------------------------------------------------------------------------


def _is_ora_table_missing(ex: oracledb.DatabaseError) -> bool:
    """Return True if *ex* is ORA-00942 (table or view does not exist)."""
    first_arg = ex.args[0] if ex.args else None
    code = getattr(first_arg, "code", None)
    message = str(first_arg) if first_arg is not None else ""
    return code == 942 or "ORA-00942" in message


async def count_active_embed_jobs(
    pool: oracledb.AsyncConnectionPool,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> int:
    """Return the number of unexpired embed-job rows visible in *pool*.

    "Unexpired" covers ``queued``/``running`` rows AND terminal rows
    whose ``updated`` is within ``ttl_seconds`` of now. The latter
    matters for rotation safety: terminal rows are kept for the TTL
    so clients can poll the result; if rotation closed the pool
    holding them, polls would 404 inside the documented retention
    window. Counting them here forces the rotation guard to wait
    until those reads have drained.

    A missing ``aio_embed_jobs`` table (ORA-00942) is treated as
    zero — a fresh CORE that has never had embed jobs run against
    it has nothing to protect. Other ``oracledb.Error`` shapes
    propagate so the caller can decide how to handle a flaky check
    (the database-update endpoint logs and proceeds, since failing
    closed would make a broken CORE unrepairable).
    """
    try:
        async with pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(_COUNT_ACTIVE_SQL, {"ttl_seconds": ttl_seconds})
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
    except oracledb.DatabaseError as ex:
        # Fresh CORE without ``aio_embed_jobs`` has nothing to
        # protect — surface as zero rather than blocking rotation.
        if _is_ora_table_missing(ex):
            return 0
        raise


async def count_active_embed_jobs_for_alias(
    pool: oracledb.AsyncConnectionPool,
    alias: str,
) -> int:
    """Return queued/running embed-job rows whose ``target_db`` equals *alias*.

    Counts only in-flight rows, not terminal-within-TTL ones — the
    pipeline drops its captured target-pool reference on terminal
    write, so completed jobs no longer hold the alias's pool and
    rotating / removing the alias is safe even while the row is
    retained for cross-replica polling. (CORE-side rotation is
    different: terminal status reads route through CORE, so its
    guard does count terminal rows — see
    :func:`count_active_embed_jobs`.)

    ORA-00942 is treated as zero — a fresh deploy has no table to
    count against and rotation should still be allowed.
    """
    try:
        async with pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(_COUNT_ACTIVE_BY_TARGET_SQL, {"target_db": alias})
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
    except oracledb.DatabaseError as ex:
        if _is_ora_table_missing(ex):
            return 0
        raise


# ---------------------------------------------------------------------------
# Background lifecycle: heartbeat + reaper. Started from app lifespan so
# every replica participates in stale-row cleanup.
# ---------------------------------------------------------------------------


async def run_heartbeat_loop(
    manager: EmbedJobManager,
    interval_seconds: int = _DEFAULT_HEARTBEAT_SECONDS,
) -> None:
    """Periodically heartbeat *manager*'s owned rows."""
    while True:
        try:
            bumped = await manager.heartbeat_owned()
            if bumped:
                LOGGER.debug("Heartbeat bumped %d owned embed-job rows", bumped)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — keep the loop alive across DB blips
            LOGGER.exception("Heartbeat loop iteration failed")
        await asyncio.sleep(interval_seconds)


async def run_reaper_loop(
    manager: EmbedJobManager,
    interval_seconds: int = _DEFAULT_REAP_INTERVAL_SECONDS,
    threshold_seconds: int = _DEFAULT_REAP_THRESHOLD_SECONDS,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Periodically reap stale non-terminal rows + evict expired terminal rows.

    Every replica runs its own reaper. The reap statement is idempotent
    (it transitions a row to a terminal state in a single UPDATE) so two
    pods racing to reap the same row do not corrupt state.
    """
    while True:
        try:
            reaped = await manager.reap_stale(threshold_seconds=threshold_seconds)
            if reaped:
                LOGGER.warning("Reaped %d stale embed jobs (heartbeat lost)", reaped)
            evicted = await manager.delete_terminal_ttl(ttl_seconds=ttl_seconds)
            if evicted:
                LOGGER.debug("Evicted %d terminal embed-job rows past TTL", evicted)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            LOGGER.exception("Reaper loop iteration failed")
        await asyncio.sleep(interval_seconds)
