"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for the EmbedJobManager / jobs_store layer.

These cover the multi-replica visibility (P1) and crash-recovery (P3)
review concerns at the layer where they are easiest to isolate from
the FastAPI endpoint plumbing — a separate replica simulation here is
just a second manager instance pointing at the same backing store.
"""

import asyncio
import contextlib
import datetime
from typing import Optional

import pytest

from server.app.api.v1.schemas.embed import (
    EmbedJobStage,
    EmbedJobStatus,
    EmbedProcessingResult,
)
from server.app.embed import jobs as jobs_mod


def _ok_result(total_chunks: int = 0) -> EmbedProcessingResult:
    return EmbedProcessingResult(
        message="ok",
        total_chunks=total_chunks,
        processed_files=[],
        skipped_files=[],
    )


async def _prime_heartbeat(pod: jobs_mod.EmbedJobManager) -> None:
    """Open the reaper's warmup gate by seeding the timestamps directly.

    ``reap_stale`` skips its sweep until ``_is_heartbeat_warm`` returns
    True — which requires two recent on-schedule timestamps AND that
    the most recent one corresponds to a real CORE round-trip. In
    unit tests ``get_core_pool()`` returns None so ``heartbeat_owned``
    deliberately does not advance the timestamps (production: that
    refusal is what stops an idle replica from warming the gate
    during a CORE outage). Tests that need to exercise the reaper
    seed the timestamps directly to bypass that production guard.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    pod._previous_heartbeat_at = now - datetime.timedelta(seconds=10)
    pod._last_heartbeat_at = now


@pytest.fixture(autouse=True)
def _isolated_store():
    """Reset the in-memory fallback store so tests don't bleed state."""
    jobs_mod.reset_embed_job_manager()
    jobs_mod.reset_local_jobs_store()
    yield
    jobs_mod.reset_embed_job_manager()
    jobs_mod.reset_local_jobs_store()


@pytest.mark.unit
@pytest.mark.anyio
async def test_jobs_visible_across_replicas() -> None:
    """A job submitted on one manager instance is visible from another.

    P1: when ``server.replicaCount > 1``, polls can land on any pod.
    Two manager instances simulate two pods; both must see the same
    job state because they share the backing store (CORE database in
    production; in-memory fallback in tests).
    """
    pod_a = jobs_mod.EmbedJobManager(pod_id="pod-a")
    pod_b = jobs_mod.EmbedJobManager(pod_id="pod-b")

    # Pod A schedules a coroutine that just records the result without
    # any cross-pod work. The asyncio.Task remains local to pod_a — pod_b
    # only ever sees the persisted state.
    async def _quick_pipeline(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        return _ok_result(total_chunks=1)

    submission = await pod_a.submit(client="x", coro_factory=_quick_pipeline)

    # Pod B can read the row even before the task runs.
    info_via_b = await pod_b.get(client="x", job_id=submission.job_id)
    assert info_via_b is not None
    assert info_via_b.job_id == submission.job_id
    assert info_via_b.status in (EmbedJobStatus.QUEUED, EmbedJobStatus.RUNNING, EmbedJobStatus.SUCCEEDED)

    # Drain the task; pod B should now observe the terminal state too.
    await submission.task
    info_via_b = await pod_b.get(client="x", job_id=submission.job_id)
    assert info_via_b is not None
    assert info_via_b.status == EmbedJobStatus.SUCCEEDED
    assert info_via_b.result is not None
    assert info_via_b.result.total_chunks == 1


@pytest.mark.unit
@pytest.mark.anyio
async def test_jobs_remain_scoped_per_client_across_replicas() -> None:
    """The cross-pod read still enforces the per-client scope check."""
    pod_a = jobs_mod.EmbedJobManager(pod_id="pod-a")
    pod_b = jobs_mod.EmbedJobManager(pod_id="pod-b")

    async def _noop(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        return _ok_result()

    submission = await pod_a.submit(client="alice", coro_factory=_noop)
    await submission.task

    # A pod that handles a request from a different client must NOT
    # surface alice's job — the scope check applies to every read,
    # local or remote.
    bob_view = await pod_b.get(client="bob", job_id=submission.job_id)
    assert bob_view is None
    bob_list = await pod_b.list_for_client("bob")
    assert bob_list == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_orphaned_job_reaped_after_heartbeat_stale() -> None:
    """A non-terminal job whose heartbeat went stale is marked failed.

    P3: when the pod running the pipeline crashes, the DB row is left
    in 'running' with no executor and no heartbeat refreshing it. A
    different replica's reaper picks it up. We model that with two
    managers: ``pod_dead`` is represented only by a row inserted
    directly into the store (no live task), and ``pod_reaper`` does
    the sweep. Because ``pod_reaper`` owns no jobs, priming its
    warmup gate doesn't bump any rows — so the orphan stays stale
    and is reaped on the first eligible round.
    """
    pod_reaper = jobs_mod.EmbedJobManager(pod_id="pod-reaper")

    long_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    orphan = jobs_mod._JobRow(
        job_id="job-from-dead-pod",
        client="x",
        owner_pod="pod-dead",
        status=EmbedJobStatus.RUNNING,
        progress=None,
        result=None,
        error=None,
        created=long_ago,
        updated=long_ago,
    )
    await jobs_mod._store_create(orphan)
    # Backdate ``updated`` because ``_store_create`` rewrites it to
    # ``now`` on insert.
    await jobs_mod._test_force_updated(orphan.job_id, long_ago)

    # Prime the reaper's warmup gate; in production the heartbeat
    # loop runs alongside the reaper loop and warms it naturally.
    await _prime_heartbeat(pod_reaper)

    reaped = await pod_reaper.reap_stale(threshold_seconds=300)
    assert reaped >= 1

    info = await pod_reaper.get(client="x", job_id=orphan.job_id)
    assert info is not None
    assert info.status == EmbedJobStatus.FAILED
    assert "heartbeat" in (info.error or "").lower() or "orphan" in (info.error or "").lower()


@pytest.mark.unit
@pytest.mark.anyio
async def test_heartbeat_keeps_owned_job_alive() -> None:
    """A pod that is still alive bumps its rows so they aren't reaped."""
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    started = asyncio.Event()
    blocker: asyncio.Future = asyncio.Future()

    async def _hang(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        started.set()
        await blocker
        return _ok_result()

    submission = await pod.submit(client="x", coro_factory=_hang)
    await started.wait()

    # Backdate the row so it WOULD be reaped...
    await jobs_mod._test_force_updated(
        submission.job_id,
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10),
    )
    # ...then have the pod heartbeat its owned rows, bumping `updated`.
    bumped = await pod.heartbeat_owned()
    assert bumped >= 1

    # Now the reaper with a 5-minute threshold should leave it alone.
    reaped = await pod.reap_stale(threshold_seconds=300)
    assert reaped == 0

    info = await pod.get(client="x", job_id=submission.job_id)
    assert info is not None
    assert info.status in (EmbedJobStatus.QUEUED, EmbedJobStatus.RUNNING)

    submission.task.cancel()
    with contextlib.suppress(BaseException):
        await submission.task


@pytest.mark.unit
@pytest.mark.anyio
async def test_progress_writes_propagate_across_replicas() -> None:
    """Stage progress reported on one pod is observable from another."""
    pod_a = jobs_mod.EmbedJobManager(pod_id="pod-a")
    pod_b = jobs_mod.EmbedJobManager(pod_id="pod-b")

    progress_seen = asyncio.Event()

    async def _emit_progress(handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        await handle.set_progress(
            EmbedJobStage.EMBEDDING,
            message="halfway through",
            total_chunks=42,
        )
        progress_seen.set()
        return _ok_result(total_chunks=42)

    submission = await pod_a.submit(client="x", coro_factory=_emit_progress)
    await progress_seen.wait()

    # Pod B reads progress mid-flight via the shared store.
    info = await pod_b.get(client="x", job_id=submission.job_id)
    assert info is not None
    assert info.progress is not None
    assert info.progress.stage == EmbedJobStage.EMBEDDING
    assert info.progress.total_chunks == 42

    await submission.task


@pytest.mark.unit
@pytest.mark.anyio
async def test_submission_failure_propagates_through_pipeline() -> None:
    """Submission cleanup contract: ``cancel_local`` returns False once a job is terminal."""
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    async def _quick(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        return _ok_result()

    submission = await pod.submit(client="x", coro_factory=_quick)
    await submission.task

    # Once the task is done the manager has already dropped its handle,
    # so cancel_local has nothing to act on.
    assert await pod.cancel_local(submission.job_id) is False


@pytest.mark.unit
@pytest.mark.anyio
async def test_running_write_failure_does_not_strand_pipeline() -> None:
    """If marking a job RUNNING fails, the pipeline still runs and cleans up.

    P2: previously the RUNNING update sat outside ``_run``'s try block,
    so a transient DB blip on that write meant ``coro_factory`` never
    executed — work_dir would be left on disk and the local task map
    would still have the entry. The contract now is: a RUNNING-write
    failure is logged and ignored; the pipeline runs normally and the
    final terminal write transitions the row.
    """
    pipeline_started = asyncio.Event()

    async def _pipeline(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        pipeline_started.set()
        return _ok_result(total_chunks=7)

    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    real_set_status = jobs_mod._store_set_status
    failed_once = {"running": False}

    async def _flaky_set_status(job_id, status, error):
        if status == EmbedJobStatus.RUNNING and not failed_once["running"]:
            failed_once["running"] = True
            raise RuntimeError("synthetic CORE blip on RUNNING write")
        await real_set_status(job_id, status, error)

    from unittest.mock import patch as _patch

    with _patch.object(jobs_mod, "_store_set_status", _flaky_set_status):
        submission = await pod.submit(client="x", coro_factory=_pipeline)
        await submission.task

    # Pipeline body must have run despite the RUNNING-write failure.
    assert pipeline_started.is_set()
    # Local task map must have been cleaned up.
    assert submission.job_id not in pod._tasks
    # Final terminal state should be SUCCEEDED — the success-write goes
    # through ``_store_set_result`` which we did not intercept.
    info = await pod.get(client="x", job_id=submission.job_id)
    assert info is not None
    assert info.status == EmbedJobStatus.SUCCEEDED
    assert info.result is not None
    assert info.result.total_chunks == 7


@pytest.mark.unit
@pytest.mark.anyio
async def test_transient_success_write_failure_is_retried() -> None:
    """A transient blip on the success terminal write must not lose the job.

    P2: ``populate_vs`` has already committed the embeddings to the
    vector store by the time ``_store_set_result`` runs. If that
    status write hits a transient CORE error and we just swallow it,
    the row is left ``running``, the heartbeat (keyed to ``_tasks``)
    no longer covers it after the task exits, and the reaper marks
    it ``failed``. Clients then see "failed" for a job whose vector
    store is fully populated. The fix is to retry before giving up.
    """
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    real_set_result = jobs_mod._store_set_result
    attempts = {"n": 0}

    async def _flaky_set_result(job_id, result):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient CORE blip on success write")
        await real_set_result(job_id, result)

    async def _success_pipeline(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        return _ok_result(total_chunks=11)

    from unittest.mock import patch as _patch

    # Patch the sleep helper so the retry backoff doesn't slow the test.
    async def _no_sleep(_seconds):
        return None

    with (
        _patch.object(jobs_mod, "_store_set_result", _flaky_set_result),
        _patch.object(jobs_mod.asyncio, "sleep", _no_sleep),
    ):
        submission = await pod.submit(client="x", coro_factory=_success_pipeline)
        await submission.task

    info = await pod.get(client="x", job_id=submission.job_id)
    assert info is not None
    assert info.status == EmbedJobStatus.SUCCEEDED, (
        "transient terminal-write failure should be retried; the job "
        "ultimately succeeded and clients must observe SUCCEEDED."
    )
    assert info.result is not None
    assert info.result.total_chunks == 11
    assert attempts["n"] >= 3, "retry should have occurred at least twice before success"


@pytest.mark.unit
@pytest.mark.anyio
async def test_persistent_terminal_write_failure_pops_local_tasks() -> None:
    """A persistent terminal-write failure still releases the local task slot.

    Even if every retry fails, ``_tasks`` must end up empty so the
    pod's heartbeat stops covering the row and the reaper can mark
    it failed eventually. Without this guarantee, a wedged terminal
    write could pin a heartbeat-refreshed row at ``running`` forever.
    """
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    async def _always_fails_set_result(_job_id, _result):
        raise RuntimeError("CORE down — every retry fails")

    async def _success_pipeline(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        return _ok_result()

    async def _no_sleep(_seconds):
        return None

    from unittest.mock import patch as _patch

    with (
        _patch.object(jobs_mod, "_store_set_result", _always_fails_set_result),
        _patch.object(jobs_mod.asyncio, "sleep", _no_sleep),
    ):
        submission = await pod.submit(client="x", coro_factory=_success_pipeline)
        await submission.task

    # Even after all retries failed, the local tasks map must be clean
    # so heartbeats stop refreshing the row and the reaper can act.
    assert submission.job_id not in pod._tasks


@pytest.mark.unit
@pytest.mark.anyio
async def test_cancellation_propagates_promptly_through_async_await() -> None:
    """[P1] Cancellation must propagate into the pipeline rather than
    wait for natural completion.

    Reviewer concern: an earlier shield-and-await fix (intended to
    avoid writing terminal status while a worker thread was still
    running) turned every cancel into "wait for natural
    completion." For a pipeline parked on a cancellable async await
    (DB call, event waiter, etc.), that wait never resolves —
    ``await submission.task`` hangs forever, ``_tasks`` is never
    popped, and shutdown / teardown blocks indefinitely.

    Contract: an outer ``Task.cancel()`` while the pipeline is
    parked on an async await must propagate ``CancelledError``
    promptly, not block on the inner running to natural completion.

    The pipeline body in this test parks on an
    ``asyncio.Future()`` that is never resolved — only an inbound
    cancellation can free it. ``await submission.task`` must
    therefore complete shortly after the cancel; if it does not,
    the test deadline (1s) fails it.
    """
    blocker: asyncio.Future = asyncio.Future()

    async def _hangs_on_async(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        await blocker
        return _ok_result()

    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")
    submission = await pod.submit(client="x", coro_factory=_hangs_on_async)

    # Yield enough turns for the inner task to actually park on
    # ``await blocker``.
    for _ in range(20):
        await asyncio.sleep(0)

    submission.task.cancel()
    # Cancellation must reach the pipeline and unwind it within a
    # tight bound. Without the fix, a shield-and-await converts
    # this into an infinite wait on ``blocker`` and ``wait_for``
    # times out.
    with contextlib.suppress(BaseException):
        await asyncio.wait_for(submission.task, timeout=1.0)

    assert submission.task.done(), (
        "task did not unwind within the cancellation deadline — "
        "outer cancel was effectively swallowed (e.g. by shielding "
        "the inner task), which leaves _tasks populated and blocks "
        "shutdown indefinitely"
    )
    assert submission.job_id not in pod._tasks, (
        "_tasks was not popped after cancellation; the heartbeat "
        "would refresh the row indefinitely and the reaper would "
        "never sweep it"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_cancellation_during_running_write_pops_local_tasks() -> None:
    """P2: cancellation while awaiting the initial RUNNING write must still cleanup.

    ``CancelledError`` inherits from ``BaseException`` rather than
    ``Exception``, so the existing ``except Exception`` around the
    RUNNING write does not catch it. Without an outer try/finally the
    cancellation propagates straight out of ``_run``, the pop from
    ``_tasks`` never happens, the heartbeat keeps the row alive
    indefinitely, and the pipeline cleanup never runs.
    """
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    cancel_during_running = asyncio.Event()
    proceed = asyncio.Event()
    real_set_status = jobs_mod._store_set_status

    async def _slow_running_write(job_id, status, error):
        if status == EmbedJobStatus.RUNNING:
            cancel_during_running.set()
            # Block until cancelled — the test cancels before this
            # ever resolves, simulating a cancellation that arrives
            # mid-flight on the initial RUNNING write.
            await proceed.wait()
        else:
            await real_set_status(job_id, status, error)

    async def _pipeline_should_not_run(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        # If we got here, ``_run`` somehow proceeded past the cancelled
        # RUNNING write — the test would be lying about the scenario.
        raise AssertionError("pipeline ran despite mid-flight cancellation")

    from unittest.mock import patch as _patch

    with _patch.object(jobs_mod, "_store_set_status", _slow_running_write):
        submission = await pod.submit(client="x", coro_factory=_pipeline_should_not_run)
        await cancel_during_running.wait()
        submission.task.cancel()
        with contextlib.suppress(BaseException):
            await submission.task

    # The local tasks map MUST be empty even though the pipeline body
    # never ran — otherwise the heartbeat would keep the row alive
    # indefinitely after the task is gone.
    assert submission.job_id not in pod._tasks


@pytest.mark.unit
@pytest.mark.anyio
async def test_reaper_skips_until_two_consecutive_heartbeats() -> None:
    """P2: post-CORE-outage races must not let the reaper kill live jobs.

    During a CORE outage longer than the reap threshold, heartbeats
    fail (they can't reach CORE) and rows look stale. As soon as CORE
    recovers, ``_run_reaper_loop`` would otherwise mark every still-
    running job ``failed`` before the heartbeat catches up. Combined
    with the terminal-state guard, a successful job whose vector
    store was populated would then be reported as failed forever.

    The fix is a warmup gate: ``reap_stale`` requires two consecutive
    successful heartbeats with a normal gap before sweeping. The
    first post-recovery heartbeat establishes only one history entry
    (the gap to the previous entry — from before the outage — is
    huge), so the next on-schedule heartbeat is needed to clear the
    gate. By that point owned rows have been bumped and the false-
    positive reap is impossible.
    """
    from unittest.mock import patch as _patch

    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    # Pre-populate a row directly in the store. We don't want a real
    # task running because the reaper sweeps non-terminal rows
    # regardless of ownership; the question is whether the gate
    # prevents reaping at all.
    long_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    target = jobs_mod._JobRow(
        job_id="job-warmup",
        client="x",
        owner_pod=pod.pod_id,
        status=EmbedJobStatus.RUNNING,
        progress=None,
        result=None,
        error=None,
        created=long_ago,
        updated=long_ago,
    )
    await jobs_mod._store_create(target)
    await jobs_mod._test_force_updated(target.job_id, long_ago)

    # In production, heartbeats go through CORE so ``hit_core`` is
    # True. In this unit test ``get_core_pool`` returns None and
    # heartbeat_owned would deliberately not warm the gate (which is
    # the production guard against idle-replica false reaps). Patch
    # the helper to claim a successful CORE round-trip so the test
    # can exercise the gate's progression directly.
    real_hb = jobs_mod._store_heartbeat_active

    async def _hit_core(owner_pod, job_ids):
        bumped, _ = await real_hb(owner_pod, job_ids)
        return bumped, True

    with _patch.object(jobs_mod, "_store_heartbeat_active", _hit_core):
        # Cold start: no heartbeats recorded → reaper must abstain.
        assert await pod.reap_stale(threshold_seconds=300) == 0

        # First post-outage heartbeat: only one history entry — still cold.
        await pod.heartbeat_owned()
        assert await pod.reap_stale(threshold_seconds=300) == 0

        # Second on-schedule heartbeat: warmup complete. Reaper allowed.
        await pod.heartbeat_owned()
        # Now the reaper IS allowed; whether it actually reaps the row
        # depends on whether heartbeat_owned bumped it. ``target`` is not
        # owned via ``self._tasks`` (we inserted it directly), so the
        # heartbeat did not refresh it. The row is still stale and gets
        # reaped — proving the gate is now open.
        assert await pod.reap_stale(threshold_seconds=300) == 1


def _ora_error(code: int, message: str) -> BaseException:
    """Construct an ``oracledb.DatabaseError`` whose ``args[0].code == code``.

    Mirrors the wire shape ``execute_sql`` inspects when deciding
    whether to swallow ORA-00942 / ORA-00955. A bare-string
    ``DatabaseError("ORA-...")`` has ``args[0]`` as a ``str`` whose
    ``getattr(..., "code", None)`` returns None — so execute_sql
    does NOT swallow it, defeating the test. We need an inner object
    that carries ``.code`` directly.
    """
    from unittest.mock import MagicMock as _MagicMock

    import oracledb as _oracledb

    inner = _MagicMock()
    inner.code = code
    inner.message = message
    return _oracledb.DatabaseError(inner)


def _make_recording_pool(fetch_rows: Optional[list[tuple]] = None):
    """Build a fake CORE pool whose cursor records its usage and returns *fetch_rows*.

    Used by tests that need to verify *which* pool an operation went
    through (e.g. the CORE-rotation scenario). The mock chain mirrors
    the production call path: ``pool.acquire() → conn.cursor() →
    cursor.execute()``. ``rowcount`` is set to 1 by default so an
    INSERT sees the success contract enforced by ``_store_create``.
    """
    from unittest.mock import AsyncMock as _AsyncMock
    from unittest.mock import MagicMock as _MagicMock

    cursor = _AsyncMock()
    cursor.execute = _AsyncMock()
    cursor.executemany = _AsyncMock()
    cursor.setinputsizes = _MagicMock()
    cursor.rowcount = 1
    cursor.description = None
    cursor.fetchall = _AsyncMock(return_value=fetch_rows or [])
    cursor.fetchmany = _AsyncMock(return_value=fetch_rows or [])

    cursor_ctx = _MagicMock()
    cursor_ctx.__aenter__ = _AsyncMock(return_value=cursor)
    cursor_ctx.__aexit__ = _AsyncMock(return_value=False)

    conn = _MagicMock()
    conn.cursor = _MagicMock(return_value=cursor_ctx)
    conn.commit = _AsyncMock()

    acquire_ctx = _MagicMock()
    acquire_ctx.__aenter__ = _AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = _AsyncMock(return_value=False)

    pool = _MagicMock()
    pool.acquire = _MagicMock(return_value=acquire_ctx)
    return pool


def _make_pool_with_failing_cursor(execute_side_effect: BaseException):
    """Build a fake CORE pool whose ``cursor.execute`` raises *execute_side_effect*.

    Used by tests that simulate ``ORA-00942`` (table missing) without a
    real Oracle. The mock chain mirrors the production call path:
    ``pool.acquire() → conn.cursor() → cursor.execute()``.
    """
    from unittest.mock import AsyncMock as _AsyncMock
    from unittest.mock import MagicMock as _MagicMock

    cursor = _AsyncMock()
    cursor.execute = _AsyncMock(side_effect=execute_side_effect)
    cursor.executemany = _AsyncMock(side_effect=execute_side_effect)
    cursor.setinputsizes = _MagicMock()
    cursor.rowcount = 0
    cursor.description = None
    cursor.fetchmany = _AsyncMock(return_value=[])

    cursor_ctx = _MagicMock()
    cursor_ctx.__aenter__ = _AsyncMock(return_value=cursor)
    cursor_ctx.__aexit__ = _AsyncMock(return_value=False)

    conn = _MagicMock()
    conn.cursor = _MagicMock(return_value=cursor_ctx)
    conn.commit = _AsyncMock()

    acquire_ctx = _MagicMock()
    acquire_ctx.__aenter__ = _AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = _AsyncMock(return_value=False)

    pool = _MagicMock()
    pool.acquire = _MagicMock(return_value=acquire_ctx)
    return pool


@pytest.mark.unit
@pytest.mark.anyio
async def test_store_create_raises_in_production_mode_when_pool_missing(monkeypatch) -> None:
    """P2: production submissions must not silently fall back to _LOCAL_STORE.

    The endpoint guards CORE availability with ``_require_core_pool``
    before calling ``manager.submit``, but there is a TOCTOU window:
    if the pool is cleared between the guard and ``_store_create``,
    the in-memory fallback path silently accepts the job. The 202
    that results would be invisible to other replicas and to this
    same pod after CORE recovers — breaking the cross-replica
    polling contract. Production must raise so the endpoint surfaces
    the documented retry-able 503 instead.
    """
    # Disable the fallback (simulating production, where the test
    # autouse fixture's call to ``reset_local_jobs_store`` would
    # never run).
    monkeypatch.setattr(jobs_mod._LocalFallback, "allowed", False)

    row = jobs_mod._JobRow(
        job_id="prod-job-1",
        client="x",
        owner_pod="pod-1",
        status=EmbedJobStatus.QUEUED,
        progress=None,
        result=None,
        error=None,
        created=datetime.datetime.now(datetime.timezone.utc),
        updated=datetime.datetime.now(datetime.timezone.utc),
    )

    with pytest.raises(jobs_mod.EmbedJobStoreUnavailable):
        await jobs_mod._store_create(row)


@pytest.mark.unit
@pytest.mark.anyio
async def test_store_get_raises_in_production_mode_when_pool_missing(monkeypatch) -> None:
    """P2: TOCTOU race — pool cleared after endpoint guard must surface 503.

    The endpoint calls ``_require_core_pool`` up front, but if the
    pool is cleared between that check and ``_store_get`` (config
    reload, transient outage), the in-memory fallback would silently
    return ``None`` for a job that exists in CORE — making the
    endpoint return 404. Polling clients treat 404 as terminal and
    stop polling for a job that's still running. Production must
    surface ``EmbedJobStoreUnavailable`` so the endpoint converts to
    503 (the documented retry-able status).
    """
    monkeypatch.setattr(jobs_mod._LocalFallback, "allowed", False)

    with pytest.raises(jobs_mod.EmbedJobStoreUnavailable):
        await jobs_mod._store_get("any-job-id")


@pytest.mark.unit
@pytest.mark.anyio
async def test_store_list_for_client_raises_in_production_mode_when_pool_missing(
    monkeypatch,
) -> None:
    """P2: same TOCTOU concern as ``_store_get`` — empty fallback list
    would imply 'this client has no jobs' even though jobs may exist
    in CORE that we just can't reach. Surface ``EmbedJobStoreUnavailable``
    so the endpoint returns 503.
    """
    monkeypatch.setattr(jobs_mod._LocalFallback, "allowed", False)

    with pytest.raises(jobs_mod.EmbedJobStoreUnavailable):
        await jobs_mod._store_list_for_client("any-client")


@pytest.mark.unit
@pytest.mark.anyio
async def test_store_get_raises_on_missing_table() -> None:
    """P2: a missing job table on read must propagate, not look like 'no row'.

    ``execute_sql`` swallows ORA-00942 and returns None for SELECT.
    If ``_store_get`` routed through that helper, a dropped table or
    revoked privilege would make every poll look like the job had
    been evicted: GET /v1/embed/jobs/{id} would return 404 and the
    polling client (which only retries 503) would stop polling for
    a job that may still be running. The read path must propagate
    the error so the endpoint can surface 503.
    """
    from unittest.mock import patch as _patch

    pool = _make_pool_with_failing_cursor(
        _ora_error(942, "ORA-00942: table or view does not exist")
    )

    with (
        _patch.object(jobs_mod, "get_core_pool", return_value=pool),
        pytest.raises(BaseException),
    ):
        await jobs_mod._store_get("any-job-id")


@pytest.mark.unit
@pytest.mark.anyio
async def test_store_list_for_client_raises_on_missing_table() -> None:
    """Same swallow hazard applies to GET /v1/embed/jobs.

    A swallowed ORA-00942 would make the list endpoint return ``[]``
    — implying "this client has no jobs" — even though jobs may
    exist in CORE that we just can't reach. The read path must
    propagate the error so the endpoint surfaces 503.
    """
    from unittest.mock import patch as _patch

    pool = _make_pool_with_failing_cursor(
        _ora_error(942, "ORA-00942: table or view does not exist")
    )

    with (
        _patch.object(jobs_mod, "get_core_pool", return_value=pool),
        pytest.raises(BaseException),
    ):
        await jobs_mod._store_list_for_client("any-client")


@pytest.mark.unit
@pytest.mark.anyio
async def test_store_set_result_raises_on_missing_table() -> None:
    """P2: a terminal SUCCESS write must propagate a missing-table error.

    Pre-fix, ``_store_set_result`` called ``execute_sql`` which
    swallows ORA-00942 and returns ``None``. The retry helper then
    treated the silently-dropped UPDATE as a successful terminal
    write, the local task entry was popped, the heartbeat stopped
    covering the row, and the reaper marked a fully populated
    vector store ``failed``. The write path must bypass the swallow
    so the retry helper waits for the table / privileges to come
    back instead.
    """
    from unittest.mock import patch as _patch

    pool = _make_pool_with_failing_cursor(
        _ora_error(942, "ORA-00942: table or view does not exist")
    )

    with (
        _patch.object(jobs_mod, "get_core_pool", return_value=pool),
        pytest.raises(BaseException),
    ):
        await jobs_mod._store_set_result("any-job-id", _ok_result(total_chunks=1))


@pytest.mark.unit
@pytest.mark.anyio
async def test_store_set_status_raises_on_missing_table() -> None:
    """Same swallow hazard applies to the FAILED terminal write path."""
    from unittest.mock import patch as _patch

    pool = _make_pool_with_failing_cursor(
        _ora_error(942, "ORA-00942: table or view does not exist")
    )

    with (
        _patch.object(jobs_mod, "get_core_pool", return_value=pool),
        pytest.raises(BaseException),
    ):
        await jobs_mod._store_set_status(
            "any-job-id",
            EmbedJobStatus.FAILED,
            error="any error",
        )


@pytest.mark.unit
@pytest.mark.anyio
async def test_store_create_raises_on_missing_table() -> None:
    """P2: a missing ``aio_embed_jobs`` table must surface, not be acknowledged.

    ``execute_sql`` swallows ORA-00942 (table or view does not exist)
    by checking ``error.args[0].code``. If ``_store_create`` routed
    its INSERT through that helper, schema drift would let the
    INSERT silently succeed: the row never lands in CORE, the
    endpoint still returns 202, and later polls 404 instead of
    receiving the documented 503. The write path must bypass the
    swallow so ORA-00942 propagates and the endpoint surfaces 503.
    """
    from unittest.mock import patch as _patch

    pool = _make_pool_with_failing_cursor(
        _ora_error(942, "ORA-00942: table or view does not exist")
    )

    row = jobs_mod._JobRow(
        job_id="missing-table-job",
        client="x",
        owner_pod="pod-1",
        status=EmbedJobStatus.QUEUED,
        progress=None,
        result=None,
        error=None,
        created=datetime.datetime.now(datetime.timezone.utc),
        updated=datetime.datetime.now(datetime.timezone.utc),
    )

    with (
        _patch.object(jobs_mod, "get_core_pool", return_value=pool),
        pytest.raises(BaseException),
    ):
        await jobs_mod._store_create(row)


@pytest.mark.unit
@pytest.mark.anyio
async def test_pool_less_heartbeat_does_not_warm_gate() -> None:
    """P2: when CORE is unreachable, heartbeats must not advance warmup.

    Pre-fix, ``heartbeat_owned`` calls ``_store_heartbeat_active``;
    that helper falls back to ``_LOCAL_STORE`` when ``get_core_pool``
    returns ``None`` and returns a count even though no DB row was
    refreshed. The manager unconditionally records timestamps after
    the call, so an idle replica stays warm throughout a CORE outage
    and the moment CORE returns its reaper marks live jobs owned by
    other replicas ``failed`` before any owner heartbeat catches up.
    The fallback path must signal "no CORE round-trip" so the
    manager skips advancing the timestamps.
    """
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")
    # Submit a job so the local task map is non-empty; the heartbeat
    # call now has owned ids to look up but pool is None.
    blocker: asyncio.Future = asyncio.Future()

    async def _hang(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        await blocker
        return _ok_result()

    submission = await pod.submit(client="x", coro_factory=_hang)

    bumped = await pod.heartbeat_owned()
    # The local fallback bumped the row (it's in _LOCAL_STORE because
    # _store_create wrote there with pool=None).
    assert bumped >= 1
    # Critical: timestamps must remain unset because no CORE round-trip
    # actually validated that CORE is healthy.
    assert pod._last_heartbeat_at is None
    assert pod._previous_heartbeat_at is None

    # Cleanup
    submission.task.cancel()
    with contextlib.suppress(BaseException):
        await submission.task


@pytest.mark.unit
@pytest.mark.anyio
async def test_warmup_gate_closes_when_last_heartbeat_is_stale() -> None:
    """P1: a "warm" gate must not stay warm forever.

    ``_is_heartbeat_warm`` previously only compared ``last`` to
    ``prev``. Once a normal gap had been observed, the gate stayed
    open until the manager was reset — including across a CORE
    outage during which no successful heartbeat occurred. The first
    reaper run after recovery would then mark live jobs failed.
    The gate must additionally require ``last`` itself to be recent,
    so a long stretch with no successful heartbeat closes it.
    """
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    # Simulate two on-schedule heartbeats from 10 minutes ago.
    ten_min_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    pod._previous_heartbeat_at = ten_min_ago - datetime.timedelta(seconds=30)
    pod._last_heartbeat_at = ten_min_ago

    # The gap between them is normal (30s), but ``last`` itself is
    # stale — heartbeats have not been succeeding for the past 10 min.
    assert not pod._is_heartbeat_warm(), (
        "Gate must close when the last successful heartbeat is too old."
    )

    # And ``reap_stale`` honours it.
    reaped = await pod.reap_stale(threshold_seconds=300)
    assert reaped == 0


@pytest.mark.unit
@pytest.mark.anyio
async def test_idle_heartbeat_requires_core_roundtrip() -> None:
    """P1: idle replicas must NOT stay warm during a CORE outage.

    An idle pod (no submitted jobs) calling ``heartbeat_owned`` would
    previously short-circuit the store call and return 0 without
    touching CORE — so the timestamp got recorded even when CORE was
    unreachable. As soon as CORE recovered, the idle replica's
    reaper was already warm and could mark live jobs owned by other
    replicas ``failed`` before any of those replicas had a chance to
    refresh their rows.

    The heartbeat helper must perform a CORE round-trip on every
    invocation — a no-op SELECT when there are no rows to bump — so
    a CORE outage causes ``heartbeat_owned`` to raise and the
    manager skips recording the timestamp.
    """
    from unittest.mock import AsyncMock, MagicMock
    from unittest.mock import patch as _patch

    import oracledb as _oracledb

    pod = jobs_mod.EmbedJobManager(pod_id="idle-pod")  # no jobs submitted

    # Build a fake pool whose ``acquire().__aenter__`` raises — simulates
    # CORE listener refusing the connection.
    failing_acquire_ctx = MagicMock()
    failing_acquire_ctx.__aenter__ = AsyncMock(
        side_effect=_oracledb.DatabaseError("ORA-12541: CORE listener refused")
    )
    failing_acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    failing_pool = MagicMock()
    failing_pool.acquire.return_value = failing_acquire_ctx

    with (
        _patch.object(jobs_mod, "get_core_pool", return_value=failing_pool),
        pytest.raises(_oracledb.DatabaseError),
    ):
        await pod.heartbeat_owned()

    # Failed heartbeat must NOT have advanced the warmup signal.
    assert pod._last_heartbeat_at is None, (
        "An idle pod whose CORE round-trip failed must not record a "
        "successful heartbeat timestamp."
    )
    assert pod._previous_heartbeat_at is None


@pytest.mark.unit
@pytest.mark.anyio
async def test_terminal_writes_raise_when_db_row_missing_and_pool_gone() -> None:
    """Reviewer P2: a DB-backed job must not lose terminal state on a CORE drop.

    Scenario: ``_store_create`` ran with a real pool and inserted into
    ``aio_embed_jobs``. The pool is then taken away (config reload,
    transient outage). When the pipeline finishes and calls
    ``_store_set_result`` (or ``_store_set_status``) with pool=None,
    the in-memory fallback finds nothing — the row was DB-only.
    Returning silently would let ``_terminal_write_with_retry`` treat
    the write as successful, ``_run`` would pop ``_tasks``, the
    heartbeat would stop covering the row, and the reaper would
    eventually mark a fully populated vector store as failed. The
    fallback must raise so the retry helper waits for the pool to
    come back instead.
    """
    # No row anywhere — pool is None (test mode) AND _LOCAL_STORE empty.
    # This is exactly the shape the reviewer described: a row that was
    # written via the DB path but cannot be located via the fallback.
    with pytest.raises(Exception):
        await jobs_mod._store_set_result(
            "missing-id",
            _ok_result(),
        )
    with pytest.raises(Exception):
        await jobs_mod._store_set_status(
            "missing-id",
            EmbedJobStatus.FAILED,
            error="anything",
        )


@pytest.mark.unit
@pytest.mark.anyio
async def test_terminal_write_silently_succeeds_when_row_exists_in_local_store() -> None:
    """Existing tests rely on the fallback when both create and update see pool=None.

    Pin the regression boundary: when the row IS in ``_LOCAL_STORE``,
    the fallback path must continue to apply the update (no raise).
    Otherwise every test in test_jobs.py that exercises the in-memory
    path would break the moment we add the new raise.
    """
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    async def _quick(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        return _ok_result(total_chunks=3)

    submission = await pod.submit(client="x", coro_factory=_quick)
    await submission.task

    info = await pod.get(client="x", job_id=submission.job_id)
    assert info is not None
    assert info.status == EmbedJobStatus.SUCCEEDED
    assert info.result is not None
    assert info.result.total_chunks == 3


@pytest.mark.unit
@pytest.mark.anyio
async def test_progress_write_failure_does_not_abort_pipeline() -> None:
    """A transient CORE blip on a progress write must not fail the job.

    P2: progress writes are telemetry. If ``_store_set_progress`` raises
    while the pipeline is calling ``handle.set_progress``, the
    exception used to propagate up through ``coro_factory`` and the
    manager would mark the whole job ``failed`` even though the parse /
    embed work could otherwise have completed normally. Progress
    failures must be swallowed so a status-DB blip never aborts the
    embedding job itself.
    """
    pipeline_finished = asyncio.Event()

    async def _emits_progress(handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        # First progress write hits the synthetic blip; if the pipeline
        # is robust, the second one (a real progress write) succeeds.
        await handle.set_progress(EmbedJobStage.SPLITTING, message="step 1")
        await handle.set_progress(EmbedJobStage.EMBEDDING, message="step 2")
        pipeline_finished.set()
        return _ok_result(total_chunks=5)

    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    real_set_progress = jobs_mod._store_set_progress
    progress_calls = {"n": 0}

    async def _flaky_progress(job_id, progress):
        progress_calls["n"] += 1
        if progress_calls["n"] == 1:
            raise RuntimeError("synthetic CORE blip on progress write")
        await real_set_progress(job_id, progress)

    from unittest.mock import patch as _patch

    with _patch.object(jobs_mod, "_store_set_progress", _flaky_progress):
        submission = await pod.submit(client="x", coro_factory=_emits_progress)
        await submission.task

    assert pipeline_finished.is_set(), "pipeline must continue past a failed progress write"

    info = await pod.get(client="x", job_id=submission.job_id)
    assert info is not None
    # Pipeline succeeded — the progress blip was swallowed.
    assert info.status == EmbedJobStatus.SUCCEEDED
    assert info.result is not None
    assert info.result.total_chunks == 5


@pytest.mark.unit
@pytest.mark.anyio
async def test_terminal_state_not_overwritten_after_reap() -> None:
    """A reaper-set terminal state must survive the original task's success write.

    P2: a heartbeat outage can let the reaper mark a still-running row
    ``failed`` while the local pipeline is mid-flight. When the
    pipeline finishes successfully and ``_store_set_result`` writes
    ``succeeded``, the row must NOT flip terminal-state from failed to
    succeeded — clients that polled after the reap already observed
    ``failed`` and a later flip would be a correctness violation.
    """
    # Two pods: ``pod_runner`` owns the hanging task; ``pod_reaper`` is
    # the one whose reaper fires. ``pod_reaper`` doesn't own the row,
    # so priming its warmup gate doesn't bump the row.
    pod_runner = jobs_mod.EmbedJobManager(pod_id="pod-runner")
    pod_reaper = jobs_mod.EmbedJobManager(pod_id="pod-reaper")

    blocker = asyncio.Event()

    async def _hangs_then_succeeds(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        await blocker.wait()
        return _ok_result(total_chunks=99)

    submission = await pod_runner.submit(client="x", coro_factory=_hangs_then_succeeds)

    # Simulate a heartbeat outage: backdate the row past the reap
    # threshold while the pipeline is still running.
    await jobs_mod._test_force_updated(
        submission.job_id,
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10),
    )
    await _prime_heartbeat(pod_reaper)
    reaped = await pod_reaper.reap_stale(threshold_seconds=300)
    assert reaped == 1

    # Confirm the intermediate state — clients polling now see FAILED.
    intermediate = await pod_reaper.get(client="x", job_id=submission.job_id)
    assert intermediate is not None
    assert intermediate.status == EmbedJobStatus.FAILED

    # Now let the pipeline finish. ``_run`` will call ``_store_set_result``
    # with status=succeeded; the guard must keep the row at FAILED.
    blocker.set()
    await submission.task

    final = await pod_reaper.get(client="x", job_id=submission.job_id)
    assert final is not None
    assert final.status == EmbedJobStatus.FAILED, (
        "Reaped row was overwritten by a late terminal write — clients "
        "that already saw FAILED would observe a flip to SUCCEEDED."
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_terminal_failure_state_not_overwritten_after_reap() -> None:
    """The status-write guard also covers the failed-pipeline path.

    Same shape as the success case: reaper marks FAILED, then the
    original pipeline raises and ``_run`` calls ``_store_set_status``
    with status=failed and a different error message. The guard must
    keep the original (reaper-authored) terminal state intact.
    """
    pod_runner = jobs_mod.EmbedJobManager(pod_id="pod-runner")
    pod_reaper = jobs_mod.EmbedJobManager(pod_id="pod-reaper")

    blocker = asyncio.Event()

    async def _hangs_then_raises(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        await blocker.wait()
        raise RuntimeError("late pipeline failure")

    submission = await pod_runner.submit(client="x", coro_factory=_hangs_then_raises)

    await jobs_mod._test_force_updated(
        submission.job_id,
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10),
    )
    await _prime_heartbeat(pod_reaper)
    await pod_reaper.reap_stale(threshold_seconds=300)

    intermediate = await pod_reaper.get(client="x", job_id=submission.job_id)
    assert intermediate is not None
    assert intermediate.status == EmbedJobStatus.FAILED
    reap_error = intermediate.error

    blocker.set()
    await submission.task

    final = await pod_reaper.get(client="x", job_id=submission.job_id)
    assert final is not None
    assert final.status == EmbedJobStatus.FAILED
    assert final.error == reap_error, (
        "Reaper-authored error message was overwritten by the late "
        "pipeline failure write."
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_heartbeat_skips_rows_without_local_task() -> None:
    """Heartbeat must not refresh rows whose local task has exited.

    P2: with heartbeat keyed only on ``owner_pod``, a row stranded at
    ``running`` (e.g. because the terminal-state write raised after
    ``coro_factory`` returned) would be heartbeated forever and never
    reaped. Tying the heartbeat to ``self._tasks`` instead means the
    reaper sees a stale ``updated`` and marks the orphan failed.
    """
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")

    # Insert an "orphan" row directly via the store — simulates a row
    # whose task already exited but never reached a terminal write.
    long_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    orphan = jobs_mod._JobRow(
        job_id="orphan-1",
        client="x",
        owner_pod=pod.pod_id,
        status=EmbedJobStatus.RUNNING,
        progress=None,
        result=None,
        error=None,
        created=long_ago,
        updated=long_ago,
    )
    await jobs_mod._store_create(orphan)
    # Backdate ``updated`` because ``_store_create`` overwrites it
    # via SYSTIMESTAMP / `_utcnow()` to "now".
    await jobs_mod._test_force_updated(orphan.job_id, long_ago)

    # owner_pod matches and the row is non-terminal, but ``self._tasks``
    # does not contain ``orphan-1`` — heartbeat must skip it.
    bumped = await pod.heartbeat_owned()
    assert bumped == 0, "heartbeat must not refresh rows without a live local task"

    # Seed the warmup gate so the reaper is allowed to run; in unit
    # tests heartbeat_owned doesn't advance it (no CORE round-trip).
    await _prime_heartbeat(pod)

    # The reaper should now see the stale row and mark it failed.
    reaped = await pod.reap_stale(threshold_seconds=300)
    assert reaped == 1
    info = await pod.get(client="x", job_id=orphan.job_id)
    assert info is not None
    assert info.status == EmbedJobStatus.FAILED


@pytest.mark.unit
@pytest.mark.anyio
async def test_jobs_pinned_to_submitting_core_pool_after_rotation(monkeypatch) -> None:
    """[P2] Reads/writes for an in-flight job stay tied to the CORE that accepted it.

    Reviewer concern: when ``/v1/databases/CORE`` is updated while an
    embed job is running, the row was inserted into the OLD CORE
    pool. Subsequent ``_store_get`` / ``_store_set_*`` calls that
    blindly resolve via ``get_core_pool()`` would target the NEW
    (likely empty) pool — polling clients see 404 on a still-running
    job, terminal writes target the wrong store, and the reaper-
    versus-original-task race becomes silently incorrect.

    The fix pins the pool used by ``_store_create`` to the job_id
    so subsequent operations route back to the submitting database
    even after rotation. This test:
      1. Inserts via pool_a (submitting CORE).
      2. Rotates ``get_core_pool`` to return pool_b (rotated CORE).
      3. Reads via ``_store_get`` and asserts pool_a was hit, not pool_b.
    """
    job_id = "rotation-test-job"
    now = datetime.datetime.now(datetime.timezone.utc)

    # The row pool_a will return on SELECT — encoded as the tuple
    # shape ``_row_from_db`` consumes.
    db_row = (
        job_id, "x", "pod-a", "queued", "", None, None, None, now, now,
    )

    pool_a = _make_recording_pool(fetch_rows=[db_row])
    pool_b = _make_recording_pool(fetch_rows=[])  # rotated CORE — empty

    current = {"pool": pool_a}
    monkeypatch.setattr(jobs_mod, "get_core_pool", lambda: current["pool"])

    # Phase 1: insert via pool_a.
    row = jobs_mod._JobRow(
        job_id=job_id, client="x", owner_pod="pod-a",
        status=EmbedJobStatus.QUEUED, progress=None, result=None, error=None,
        created=now, updated=now,
    )
    await jobs_mod._store_create(row)
    pool_a_inserts = pool_a.acquire.call_count
    assert pool_a_inserts >= 1, "INSERT did not hit pool_a"

    # Phase 2: rotate CORE — get_core_pool now returns pool_b. The
    # in-flight job_id was pinned to pool_a at submission time.
    current["pool"] = pool_b

    # Phase 3: read. Must hit pool_a (pinned), not pool_b (empty new
    # CORE). Otherwise polling clients see 404 on the still-running
    # job and the reaper / terminal writes target the wrong DB.
    info = await jobs_mod._store_get(job_id)
    assert info is not None, (
        "post-rotation read returned None — _store_get redirected "
        "to the rotated (empty) CORE pool instead of the pool that "
        "accepted the INSERT"
    )
    assert info.job_id == job_id
    assert pool_a.acquire.call_count > pool_a_inserts, (
        "SELECT did not hit pool_a — the read used the rotated pool"
    )
    pool_b.acquire.assert_not_called()


@pytest.mark.unit
@pytest.mark.anyio
async def test_terminal_write_after_core_rotation_uses_submitting_pool(monkeypatch) -> None:
    """[P2] Terminal status writes route through the pinned CORE.

    Same rationale as the read-pinning test: a terminal
    ``_store_set_status(SUCCEEDED, ...)`` after rotation must land
    on the database holding the row, not on whatever CORE was
    rotated in. Otherwise the original row stays at ``running``
    forever (the UPDATE matches no rows in the new pool) and the
    reaper eventually marks it failed against the wrong DB.
    """
    job_id = "rotation-terminal-job"
    now = datetime.datetime.now(datetime.timezone.utc)

    pool_a = _make_recording_pool()
    pool_b = _make_recording_pool()

    current = {"pool": pool_a}
    monkeypatch.setattr(jobs_mod, "get_core_pool", lambda: current["pool"])

    # Phase 1: insert via pool_a (submitting CORE).
    row = jobs_mod._JobRow(
        job_id=job_id, client="x", owner_pod="pod-a",
        status=EmbedJobStatus.QUEUED, progress=None, result=None, error=None,
        created=now, updated=now,
    )
    await jobs_mod._store_create(row)
    pool_a_calls_after_insert = pool_a.acquire.call_count

    # Phase 2: rotate CORE.
    current["pool"] = pool_b

    # Phase 3: terminal status write. Must hit pool_a (pinned).
    await jobs_mod._store_set_status(job_id, EmbedJobStatus.FAILED, error="boom")

    assert pool_a.acquire.call_count > pool_a_calls_after_insert, (
        "terminal status UPDATE did not hit pool_a — the write went "
        "to the rotated CORE and the original row was left at "
        "'running' forever"
    )
    pool_b.acquire.assert_not_called()


@pytest.mark.unit
def test_update_result_sql_does_not_redundantly_clear_error() -> None:
    """[P1] ``_UPDATE_RESULT_SQL`` must not assign ``error`` alongside the result.

    Reviewer concern: the success path UPDATE included ``error = NULL``
    in addition to ``status`` / ``result`` / ``updated``. Oracle 23ai
    rejects a SET list it considers to assign a column twice
    (ORA-00957) for this exact statement shape, so every successful
    embed terminal write hit ``_terminal_write_with_retry``, was
    eventually abandoned, and the row stayed non-terminal until the
    reaper marked it failed even though the vector store was fully
    populated. The success path doesn't need to clear ``error``
    anyway — a row transitioning from queued/running → succeeded
    has ``error`` already at its INSERT default of NULL (only the
    failed-status path ever sets it). Pin the SQL shape so a future
    refactor doesn't reintroduce the clobber.
    """
    sql = jobs_mod._UPDATE_RESULT_SQL
    assert "error" not in sql.lower(), (
        f"_UPDATE_RESULT_SQL must not touch the error column on the "
        f"success path; got {sql!r}"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_count_active_embed_jobs_returns_select_count() -> None:
    """The CORE-rotation guard's count helper returns the SELECT result."""
    from unittest.mock import AsyncMock as _AsyncMock

    pool = _make_recording_pool()
    cursor = pool.acquire.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
    cursor.fetchone = _AsyncMock(return_value=(7,))

    n = await jobs_mod.count_active_embed_jobs(pool)
    assert n == 7


@pytest.mark.unit
@pytest.mark.anyio
async def test_count_active_embed_jobs_treats_missing_table_as_zero() -> None:
    """A fresh CORE without ``aio_embed_jobs`` must report zero, not raise.

    The database-update endpoint uses this count to refuse a CORE
    rotation while jobs are in flight. A brand-new CORE that has
    never had embed jobs run against it has no table to count
    against, but rotation should still be allowed — there's nothing
    to protect.
    """
    pool = _make_pool_with_failing_cursor(
        _ora_error(942, "ORA-00942: table or view does not exist")
    )

    assert await jobs_mod.count_active_embed_jobs(pool) == 0


@pytest.mark.unit
@pytest.mark.anyio
async def test_count_active_embed_jobs_propagates_other_db_errors() -> None:
    """Non-ORA-00942 database errors must propagate so the caller can decide."""
    pool = _make_pool_with_failing_cursor(
        _ora_error(12541, "ORA-12541: TNS:no listener")
    )

    with pytest.raises(BaseException):
        await jobs_mod.count_active_embed_jobs(pool)


@pytest.mark.unit
@pytest.mark.anyio
async def test_count_active_embed_jobs_for_alias_filters_by_target_db() -> None:
    """[P2] Non-CORE rotation guard counts only jobs targeting *that* alias.

    The CORE rotation guard refuses any active embed job. A non-CORE
    rotation must be more selective: blocking unrelated DBs would
    make ordinary maintenance impossible. The new helper filters by
    ``target_db`` so an admin updating ``MYDB`` only waits for jobs
    whose vector store lives in ``MYDB``.

    Test contract: the helper passes ``:target_db`` as a bind and
    returns the SELECT count.
    """
    from unittest.mock import AsyncMock as _AsyncMock

    pool = _make_recording_pool()
    cursor = pool.acquire.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
    cursor.fetchone = _AsyncMock(return_value=(3,))

    n = await jobs_mod.count_active_embed_jobs_for_alias(pool, "MYDB")
    assert n == 3
    # The bind must carry the alias so the rotation guard for ``MYDB``
    # is not falsely blocked by a job that targets ``OTHERDB``.
    args, kwargs = cursor.execute.call_args
    binds = args[1] if len(args) > 1 else kwargs.get("parameters") or kwargs
    assert binds.get("target_db") == "MYDB", (
        f"helper must bind ``target_db``; got {binds!r}"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_count_active_embed_jobs_includes_recent_terminal_rows() -> None:
    """[P2] Rotation guard must keep terminal rows readable across CORE rotation.

    Reviewer concern: terminal (succeeded/failed) rows are retained
    for the advertised TTL so clients can poll the result. Counting
    only ``queued``/``running`` lets a CORE rotation slip through
    while a recent terminal row still lives in the old CORE — the
    rotation closes the old pool, and per-job pool pins are dropped
    on terminal write, so subsequent polls hit the rotated CORE
    (which has no row) and see 404 within the documented TTL.
    Block rotation while ANY unexpired row exists.
    """
    from unittest.mock import AsyncMock as _AsyncMock

    pool = _make_recording_pool()
    cursor = pool.acquire.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
    cursor.fetchone = _AsyncMock(return_value=(2,))

    n = await jobs_mod.count_active_embed_jobs(pool)
    assert n == 2

    args, kwargs = cursor.execute.call_args
    sql = args[0]
    # The SQL must consider both active and recent-terminal rows.
    # Without the latter, CORE rotation can slip through while
    # clients still expect to read the result.
    sql_lower = sql.lower()
    assert "succeeded" in sql_lower or "terminal" in sql_lower or "ttl" in sql_lower, (
        "count_active_embed_jobs SQL must also count terminal rows "
        "still within their TTL window — clients poll those rows "
        "and a CORE rotation between terminal write and TTL expiry "
        f"would otherwise make them disappear. Got SQL: {sql}"
    )
    binds = args[1] if len(args) > 1 else kwargs.get("parameters") or {}
    assert "ttl_seconds" in binds, (
        f"SQL must bind ttl_seconds so the terminal-row window is "
        f"explicit; got binds={binds}"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_count_active_embed_jobs_for_alias_excludes_terminal_rows() -> None:
    """[P2] The per-alias guard must NOT count terminal rows.

    Reviewer concern: the captured pool to the *target* database is
    held by the pipeline only while the job is running; on terminal
    write that pool reference is dropped. Terminal status / result
    reads come from CORE (``aio_embed_jobs``), not from the target
    database, so a completed job against alias A is no longer using
    A's pool — rotating or removing A is then safe even though the
    row is retained for the TTL window. Counting terminal rows here
    blocks normal database maintenance for up to an hour after the
    last embed completes against an alias, with no correctness
    benefit. Use a queued/running-only predicate.

    The CORE-side guard (``count_active_embed_jobs``) is different:
    terminal status/result reads route through CORE, so rotating
    CORE during the TTL window would make those reads disappear.
    That guard rightly counts terminal rows; this per-alias one
    must not.
    """
    from unittest.mock import AsyncMock as _AsyncMock

    pool = _make_recording_pool()
    cursor = pool.acquire.return_value.__aenter__.return_value.cursor.return_value.__aenter__.return_value
    cursor.fetchone = _AsyncMock(return_value=(1,))

    n = await jobs_mod.count_active_embed_jobs_for_alias(pool, "MYDB")
    assert n == 1

    args, kwargs = cursor.execute.call_args
    sql = args[0].lower()
    # The query must not reference terminal statuses or the TTL
    # window — those are the symptoms of erroneously counting
    # already-completed jobs against the alias.
    assert "succeeded" not in sql, (
        f"per-alias guard SQL still references 'succeeded'; "
        f"the captured target-pool is dropped on terminal write, "
        f"so completed jobs no longer hold A's pool. SQL: {sql}"
    )
    assert "failed" not in sql, (
        f"per-alias guard SQL still references 'failed'; "
        f"completed jobs no longer hold the target pool. SQL: {sql}"
    )
    assert "ttl" not in sql and "numtodsinterval" not in sql, (
        f"per-alias guard SQL still references the TTL window; "
        f"target-pool retention does not span the terminal-row TTL. "
        f"SQL: {sql}"
    )
    binds = args[1] if len(args) > 1 else kwargs.get("parameters") or {}
    assert binds.get("target_db") == "MYDB"
    assert "ttl_seconds" not in binds, (
        f"per-alias SQL no longer needs ttl_seconds; got binds={binds}"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_count_active_embed_jobs_for_alias_treats_missing_table_as_zero() -> None:
    """[P2] A fresh CORE without ``aio_embed_jobs`` must report zero
    for the per-alias guard too — same fail-open shape as the
    CORE-wide variant. Otherwise an admin trying to update a non-CORE
    DB on a brand-new deploy would get an unhelpful 500.
    """
    pool = _make_pool_with_failing_cursor(
        _ora_error(942, "ORA-00942: table or view does not exist")
    )

    assert await jobs_mod.count_active_embed_jobs_for_alias(pool, "MYDB") == 0


@pytest.mark.unit
@pytest.mark.anyio
async def test_pinned_pool_released_after_terminal_write(monkeypatch) -> None:
    """The per-job pool pin is dropped once the row reaches a terminal
    state, so a long-running pod does not accumulate pinned references
    to pools that have been replaced and would otherwise be eligible
    for garbage collection.
    """
    job_id = "pin-release-job"
    now = datetime.datetime.now(datetime.timezone.utc)

    pool_a = _make_recording_pool()
    monkeypatch.setattr(jobs_mod, "get_core_pool", lambda: pool_a)

    row = jobs_mod._JobRow(
        job_id=job_id, client="x", owner_pod="pod-a",
        status=EmbedJobStatus.QUEUED, progress=None, result=None, error=None,
        created=now, updated=now,
    )
    await jobs_mod._store_create(row)
    assert job_id in jobs_mod._PINNED_POOLS, "pool was not pinned on insert"

    await jobs_mod._store_set_status(job_id, EmbedJobStatus.FAILED, error="done")
    assert job_id not in jobs_mod._PINNED_POOLS, (
        "terminal write should release the per-job pool pin"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_submit_registers_task_without_blocking_on_tasks_lock() -> None:
    """[P2] ``submit`` must not introduce a cancellable await between
    ``create_task`` and registration.

    The previous design did::

        task = asyncio.create_task(self._run(...))
        async with self._tasks_lock:
            self._tasks[id] = task

    which puts a cancellable await between scheduling the task and
    registering it. If the caller is cancelled at the lock acquire,
    the task is created but never tracked — heartbeats stop covering
    its row, and the endpoint's ``BaseException`` handler can tear
    down ``work_dir`` while the orphan ``_run`` continues against it.

    Fix: dict assignment is atomic in single-threaded asyncio, so the
    insertion does not need a lock. The test pins this by holding
    ``_tasks_lock`` externally and confirming ``submit`` still
    completes promptly *and* registers the task — the previous
    design would have deadlocked against the held lock.
    """
    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")
    blocker: asyncio.Future = asyncio.Future()

    async def _hang(_handle: jobs_mod.JobHandle) -> EmbedProcessingResult:
        await blocker
        return _ok_result()

    await pod._tasks_lock.acquire()
    submission: Optional[jobs_mod.JobSubmission] = None
    try:
        # If ``submit`` reintroduces the lock around registration it
        # will park here forever; ``wait_for`` surfaces that as a
        # ``TimeoutError`` and fails the test instead of hanging
        # the suite.
        submission = await asyncio.wait_for(
            pod.submit(client="x", coro_factory=_hang),
            timeout=1.0,
        )
        # And the task must already be visible in ``_tasks`` by the
        # time ``submit`` returns — otherwise heartbeats wouldn't
        # cover it on the very next sweep.
        assert submission.job_id in pod._tasks, (
            "task was not registered before submit() returned; the "
            "registration window must close before any await"
        )
    finally:
        pod._tasks_lock.release()

    # Clean up the hung pipeline.
    assert submission is not None
    submission.task.cancel()
    with contextlib.suppress(BaseException):
        await submission.task
    # And the entry was popped by ``_run``'s finally.
    assert submission.job_id not in pod._tasks
