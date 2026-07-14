"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for embed API endpoints.
"""
# spell-checker:disable

import asyncio
import contextlib
import io
from contextlib import asynccontextmanager
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy
from pydantic import SecretStr

from server.app.embed.schemas import DoclingDocumentChunk, VectorStoreConfig
from server.app.models.schemas import ModelIdentity
from server.tests.api.conftest import _create_mock_pool
from server.tests.constants import TEST_OPENAI_EMBED_ID


def job_store_test(func):
    """Mark a test that drives the real embed job store.

    Wires the live CORE container pool (``embed_core_pool``) and gates the test
    behind the ``db`` / ``integration`` markers so ``-m "not db"`` skips it.
    Tests that never submit/poll jobs (no-auth, ZIP extraction, client-lock,
    OCI-download, vector-store CRUD) omit this and stay fast and Docker-free.
    """
    func = pytest.mark.db(func)
    func = pytest.mark.integration(func)
    func = pytest.mark.usefixtures("embed_core_pool")(func)
    return func


@pytest.mark.unit
def test_group_chunks_by_filename_alias_combines_matching_source_names():
    """Files from different paths with one name populate the same store."""
    from server.app.api.v1.endpoints.embed import group_chunks_by_filename_alias

    chunks = [
        DoclingDocumentChunk("first", {"source": "/job/a_release_notes.pdf"}, "first"),
        DoclingDocumentChunk("second", {"source": "/job/b_release_notes.pdf"}, "second"),
        DoclingDocumentChunk("guide", {"source": "/job/install_guide.pdf"}, "guide"),
    ]

    grouped = group_chunks_by_filename_alias(
        chunks,
        {
            "a_release_notes.pdf": "release_notes",
            "b_release_notes.pdf": "release_notes",
        },
    )

    assert list(grouped) == ["INSTALL_GUIDE", "RELEASE_NOTES"]
    assert [chunk.id for chunk in grouped["RELEASE_NOTES"]] == ["first", "second"]


@pytest.mark.unit
def test_group_chunks_by_filename_alias_disambiguates_normalized_collisions():
    """Distinct filename stems must not target one normalized table name."""
    from server.app.api.v1.endpoints.embed import group_chunks_by_filename_alias

    chunks = [
        DoclingDocumentChunk("hyphen", {"source": "/job/hyphen.pdf"}, "hyphen"),
        DoclingDocumentChunk("underscore", {"source": "/job/underscore.pdf"}, "underscore"),
    ]

    grouped = group_chunks_by_filename_alias(
        chunks,
        {
            "hyphen.pdf": "release-notes",
            "underscore.pdf": "release_notes",
        },
    )

    assert len(grouped) == 2
    assert "RELEASE_NOTES" in grouped
    assert all(len(alias) <= 20 for alias in grouped)
    assert all(alias.startswith("RELEASE_NOTES") for alias in grouped)


@pytest.mark.unit
def test_group_chunks_by_filename_alias_bounds_long_aliases():
    """Filename-derived aliases must fit the existing alias-length limit."""
    from server.app.api.v1.endpoints.embed import group_chunks_by_filename_alias

    long_stem = "release_notes_" * 10
    chunks = [DoclingDocumentChunk("content", {"source": "/job/long.pdf"}, "long")]

    grouped = group_chunks_by_filename_alias(chunks, {"long.pdf": long_stem})

    alias = next(iter(grouped))
    assert len(alias) <= 20
    assert alias.startswith("RELEASE_NOTES")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_client_db():
    """Mock the database config resolution for all embed tests.

    Also stubs ``get_core_pool`` so the endpoint's CORE-availability
    guard sees a pool — embed tests want to cover the happy path,
    not the "CORE missing" 503 path (which has its own dedicated
    test). Tests that explicitly want CORE-missing behaviour patch
    over this fixture.
    """
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    mock_cfg = MagicMock()
    mock_cfg.pool = pool
    mock_cfg.usable = True
    mock_cfg.alias = "TEST"
    mock_cfg.username = "testuser"
    mock_cfg.password = "testpass"
    mock_cfg.dsn = "//localhost:1521/TEST"
    mock_cfg.wallet_location = None
    mock_cfg.config_dir = None
    # The handler now snapshots via ``live_cfg.model_copy()`` and
    # reads ``.alias`` off the snapshot to record ``target_db`` on the
    # job row. By default ``MagicMock.model_copy()`` returns a fresh
    # mock whose ``.alias`` is a child mock — not a string — and the
    # ``_JobRow`` Pydantic validator rejects it. Returning the same
    # mock from ``model_copy`` keeps the snapshot's attributes the
    # ones the test set above.
    mock_cfg.model_copy.return_value = mock_cfg
    with (
        patch(
            "server.app.api.v1.endpoints.embed._get_client_db_config",
            return_value=(mock_cfg, pool),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_core_pool",
            return_value=pool,
        ),
    ):
        yield conn, pool, mock_cfg


@pytest.fixture(autouse=True)
def _reset_embed_job_manager():
    """Reset the in-process job-manager singleton between tests (no DB).

    Cheap and Docker-free, so it applies to every test. Tests that exercise the
    real store opt into the live CORE pool via ``@job_store_test``; that fixture
    (``embed_core_pool``) additionally clears ``aio_embed_jobs`` and wires
    ``jobs.get_core_pool``.
    """
    from server.app.embed import jobs as jobs_mod

    jobs_mod.reset_embed_job_manager()
    jobs_mod._PINNED_POOLS.clear()
    yield
    jobs_mod.reset_embed_job_manager()
    jobs_mod._PINNED_POOLS.clear()


# ---------------------------------------------------------------------------
# Job-status polling helper
# ---------------------------------------------------------------------------


async def _poll_until_terminal(
    app_client,
    job_id: str,
    headers: dict,
    *,
    timeout_seconds: float = 5.0,
    interval_seconds: float = 0.02,
) -> dict:
    """Poll GET /v1/embed/jobs/{job_id} until the job reaches terminal state.

    Mirrors how a real client would consume the job-oriented endpoint —
    the inline split-and-embed flow used to return the result on the
    POST itself, so tests now read the same fields off the polled
    status response. The interval is short so background tasks driven
    by mocked stages finish quickly; the deadline guards against tests
    that forget to mock something heavy and hang the suite.
    """
    import asyncio
    import time

    deadline = time.monotonic() + timeout_seconds
    last: dict = {}
    while time.monotonic() < deadline:
        resp = await app_client.get(f"/v1/embed/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last["status"] in ("succeeded", "failed"):
            return last
        await asyncio.sleep(interval_seconds)
    raise AssertionError(f"Job {job_id} did not reach terminal status; last={last}")


# ---------------------------------------------------------------------------
# Auth tests — 403 without API key
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_drop_vs_no_auth(app_client):
    """DELETE /{vs} rejects requests without API key."""
    resp = await app_client.delete("/v1/embed/test_vs")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_get_files_no_auth(app_client):
    """GET /{vs}/files rejects requests without API key."""
    resp = await app_client.get("/v1/embed/test_vs/files")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_comment_no_auth(app_client):
    """PATCH /comment rejects requests without API key."""
    resp = await app_client.patch("/v1/embed/comment", json={})
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_sql_store_no_auth(app_client):
    """POST /sql/store rejects requests without API key."""
    resp = await app_client.post("/v1/embed/sql/store", json={"query": "SELECT 1"})
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_web_store_no_auth(app_client):
    """POST /web/store rejects requests without API key."""
    resp = await app_client.post("/v1/embed/web/store", json=["https://example.com"])
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_local_store_no_auth(app_client):
    """POST /local/store rejects requests without API key."""
    resp = await app_client.post("/v1/embed/local/store")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_split_embed_no_auth(app_client):
    """POST / rejects requests without API key."""
    resp = await app_client.post("/v1/embed/", json={})
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_embed_oci_store_no_auth(app_client):
    """POST /oci/store rejects requests without API key."""
    resp = await app_client.post("/v1/embed/oci/store", json={})
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_refresh_no_auth(app_client):
    """POST /refresh rejects requests without API key."""
    resp = await app_client.post("/v1/embed/refresh", json={})
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_list_jobs_no_auth(app_client):
    """GET /jobs rejects requests without API key."""
    resp = await app_client.get("/v1/embed/jobs")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_get_job_no_auth(app_client):
    """GET /jobs/{job_id} rejects requests without API key."""
    resp = await app_client.get("/v1/embed/jobs/abc123")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /{vs}
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_drop_vs(app_client, auth_headers):
    """Successfully drops a vector store."""
    with (
        patch(
            "server.app.api.v1.endpoints.embed.execute_sql",
            new_callable=AsyncMock,
            return_value=[(1,)],
        ),
        patch(
            "server.app.api.v1.endpoints.embed.drop_vector_store",
            new_callable=AsyncMock,
        ),
        patch(
            "server.app.api.v1.endpoints.embed.discover_vector_stores",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        resp = await app_client.delete("/v1/embed/MY_VS", headers=auth_headers)
    assert resp.status_code == 200
    assert "MY_VS" in resp.json()["message"]


# ---------------------------------------------------------------------------
# GET /{vs}/files
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_files(app_client, auth_headers):
    """Returns file list from vector store."""
    mock_data = {
        "vector_store": "MY_VS",
        "total_files": 1,
        "total_chunks": 10,
        "orphaned_chunks": 0,
        "files": [{"filename": "test.pdf", "chunk_count": 10, "etag": None, "time_modified": None, "size": 1024}],
    }
    with patch(
        "server.app.api.v1.endpoints.embed.get_vector_store_files",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        resp = await app_client.get("/v1/embed/MY_VS/files", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_files"] == 1
    assert body["files"][0]["filename"] == "test.pdf"


# ---------------------------------------------------------------------------
# PATCH /comment
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_comment_vs(app_client, auth_headers):
    """Successfully updates a vector store comment."""
    with patch(
        "server.app.api.v1.endpoints.embed.update_vs_comment",
        new_callable=AsyncMock,
    ):
        resp = await app_client.patch(
            "/v1/embed/comment",
            json={
                "vector_store": "MY_VS",
                "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "distance_strategy": "COSINE",
                "alias": "test_alias",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert "updated" in resp.json()["message"]


# ---------------------------------------------------------------------------
# POST /sql/store
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sql_store(app_client, auth_headers):
    """Successfully stores SQL query results."""
    with (
        patch(
            "server.app.api.v1.endpoints.embed.run_sql_query",
            new_callable=AsyncMock,
            return_value="/tmp/test/result.csv",
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=MagicMock(),
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/sql/store",
            json={"query": "SELECT col FROM my_table"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert "result.csv" in resp.json()[0]


@pytest.mark.anyio
async def test_sql_store_with_db_alias(app_client, auth_headers, mock_client_db):
    """Successfully stores SQL query results using an explicit db_alias."""
    _, _, mock_cfg = mock_client_db
    with (
        patch(
            "server.app.api.v1.endpoints.embed.get_database_settings",
            return_value=mock_cfg,
        ),
        patch(
            "server.app.api.v1.endpoints.embed.run_sql_query",
            new_callable=AsyncMock,
            return_value="/tmp/test/result.csv",
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=MagicMock(),
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/sql/store",
            json={"query": "SELECT col FROM my_table", "db_alias": "TESTDB"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert "result.csv" in resp.json()[0]


@pytest.mark.anyio
async def test_sql_store_acquires_client_lock(app_client, auth_headers):
    """[P2] /embed/sql/store must serialise on _client_lock so a
    concurrent /embed/ retry-restore sees a stable shared dir.

    Reviewer concern: the 503 restore path moves the prior corpus
    back to the shared embedding directory while holding
    ``_client_lock(client)``. If a same-client store endpoint does
    not also take that lock, it can land a different-named file in
    shared mid-restore — the restore loop only skips same-name
    conflicts, so the next embed claims a mix of stale and newly
    stored files. Closing the race requires every shared-dir writer
    to acquire the lock too.

    The test spies on ``_client_lock`` and asserts that the endpoint
    enters it for the request's client. ``where in the endpoint`` it
    enters is a code-quality concern; the contract that closes the
    race is simply that the lock is acquired at all (any cover of
    the file-write path is sufficient — concurrent writers will then
    serialise behind it).
    """
    from server.app.api.v1.endpoints import embed as embed_module

    acquisitions: list[str] = []
    real_client_lock = embed_module._client_lock

    @asynccontextmanager
    async def _spy_client_lock(client: str):
        acquisitions.append(client)
        async with real_client_lock(client):
            yield

    with (
        patch.object(embed_module, "_client_lock", _spy_client_lock),
        patch(
            "server.app.api.v1.endpoints.embed.run_sql_query",
            new_callable=AsyncMock,
            return_value="/tmp/test/result.csv",
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=MagicMock(),
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/sql/store",
            json={"query": "SELECT col FROM my_table"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    assert "server" in acquisitions, (
        "/embed/sql/store did not acquire _client_lock; a concurrent "
        "/embed/ retry restore could observe a new file appearing in "
        "shared mid-restore"
    )


@pytest.mark.anyio
async def test_web_store_acquires_client_lock(app_client, auth_headers):
    """[P2] /embed/web/store must serialise on _client_lock — same race
    as /embed/sql/store (see that test for the full reasoning).
    """
    from server.app.api.v1.endpoints import embed as embed_module

    acquisitions: list[str] = []
    real_client_lock = embed_module._client_lock

    @asynccontextmanager
    async def _spy_client_lock(client: str):
        acquisitions.append(client)
        async with real_client_lock(client):
            yield

    # Stub the network fetch so the endpoint completes quickly
    # without hitting example.com.
    @asynccontextmanager
    async def _stub_safe_client(*_args, **_kwargs):
        stub = MagicMock()
        stub.stream = MagicMock()
        # Make .stream() return a context manager whose body is a
        # mock response that 422s — the endpoint then short-circuits
        # without trying to parse a real fetch. The point of the
        # test is only to verify the lock was taken on entry.
        stream_cm = MagicMock()

        async def _aenter(*_a, **_kw):
            response = MagicMock()
            response.raise_for_status = MagicMock(side_effect=HTTPException(status_code=422, detail="stub"))
            response.headers = {"Content-Type": "application/octet-stream"}

            async def _aiter():
                # The unreachable ``yield`` is what makes this function
                # an async generator (so ``async for`` over it is a
                # zero-iteration loop). Suppressed: the ruff/F-series
                # check has no specific code for "unreachable, but
                # required by the protocol".
                return
                yield  # type: ignore[unreachable]

            response.aiter_bytes = _aiter
            return response

        stream_cm.__aenter__ = AsyncMock(side_effect=_aenter)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        stub.stream.return_value = stream_cm
        yield stub

    with (
        patch.object(embed_module, "_client_lock", _spy_client_lock),
        patch(
            "server.app.api.v1.endpoints.embed.SafeAsyncClient",
            _stub_safe_client,
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=MagicMock(),
        ),
        # The stub is wired to short-circuit the fetch so the
        # endpoint returns quickly; we don't care about the response
        # shape, only that the lock was acquired on entry.
        contextlib.suppress(BaseException),
    ):
        await app_client.post(
            "/v1/embed/web/store",
            json=["https://example.com"],
            headers=auth_headers,
        )

    assert "server" in acquisitions, (
        "/embed/web/store did not acquire _client_lock; a concurrent "
        "/embed/ retry restore could observe a new file appearing in "
        "shared mid-restore"
    )


@pytest.mark.anyio
async def test_oci_download_serializes_colliding_destinations(app_client, auth_headers):
    """[P2] Bucket keys that flatten to the same local filename must
    not download concurrently.

    Reviewer concern: ``flatten_bucket_key`` collapses ``/`` to ``_``,
    so ``a/b.txt`` and ``a_b.txt`` both target ``a_b.txt`` on disk.
    A naive ``asyncio.gather`` opens the same path twice with
    ``"wb"`` — writes interleave or truncate, leaving a corrupt
    file for the embed pipeline to claim.
    """
    import threading
    import time

    from server.app.api.v1.endpoints import embed as embed_module
    from server.app.api.v1.endpoints import oci as oci_module

    in_flight: dict[str, int] = {}
    max_in_flight: dict[str, int] = {}
    in_flight_lock = threading.Lock()

    def _instrumented_download(directory, name, bucket, profile):
        flat = name.replace("/", "_").lstrip("_")
        with in_flight_lock:
            in_flight[flat] = in_flight.get(flat, 0) + 1
            max_in_flight[flat] = max(max_in_flight.get(flat, 0), in_flight[flat])
        # Sleep so a concurrent call would observably overlap.
        time.sleep(0.05)
        with in_flight_lock:
            in_flight[flat] -= 1
        return f"{directory}/{flat}"

    @asynccontextmanager
    async def _passthrough_client_lock(_client: str):
        yield

    with (
        patch.object(embed_module, "_client_lock", _passthrough_client_lock),
        patch.object(oci_module, "_find_oci_profile", return_value=MagicMock()),
        patch(
            "server.app.oci.bucket.download_object",
            side_effect=_instrumented_download,
        ),
        patch(
            "server.app.api.v1.endpoints.oci.get_temp_directory",
            return_value=MagicMock(),
        ),
    ):
        resp = await app_client.post(
            "/v1/oci/objects/download/test-bucket/TESTPROFILE",
            json=["a/b.txt", "a_b.txt", "other.txt"],
            headers=auth_headers,
        )

    assert resp.status_code == 200
    # The colliding pair must not have overlapped on the same path.
    assert max_in_flight.get("a_b.txt", 0) == 1, (
        f"Two downloads for the same destination 'a_b.txt' ran "
        f"concurrently (max in-flight: {max_in_flight.get('a_b.txt')}); "
        f"they would have raced on ``open(..., 'wb')`` and produced "
        f"a corrupt file"
    )
    # Non-colliding downloads still got at least one in-flight call.
    assert max_in_flight.get("other.txt", 0) >= 1


@pytest.mark.anyio
async def test_oci_download_offloads_blocking_sdk_to_thread(app_client, auth_headers):
    """[P2] OCI download must run the blocking SDK call in a worker thread.

    Reviewer concern: ``download_object`` is a synchronous OCI SDK
    call that streams the entire object before returning. Running
    it on the FastAPI event loop blocks every other coroutine on
    the same pod — including the embed-job heartbeat. In a multi-
    replica deployment, a download longer than the stale threshold
    can let other replicas' reapers mark this pod's still-running
    jobs failed; the later terminal write cannot flip them back
    (the reaper write already moved them to a terminal state).
    The refresh path already offloads via ``asyncio.to_thread``
    (see ``server.app.embed.refresh``); this endpoint must too.
    """
    import threading

    from server.app.api.v1.endpoints import embed as embed_module
    from server.app.api.v1.endpoints import oci as oci_module

    main_thread_id = threading.get_ident()
    download_thread_ids: list[int] = []

    def _capturing_download(temp_dir, name, bucket, profile):
        download_thread_ids.append(threading.get_ident())
        return f"{temp_dir}/{name}"

    @asynccontextmanager
    async def _passthrough_client_lock(_client: str):
        yield

    with (
        patch.object(embed_module, "_client_lock", _passthrough_client_lock),
        patch.object(oci_module, "_find_oci_profile", return_value=MagicMock()),
        patch(
            "server.app.oci.bucket.download_object",
            side_effect=_capturing_download,
        ),
        patch(
            "server.app.api.v1.endpoints.oci.get_temp_directory",
            return_value=MagicMock(),
        ),
    ):
        resp = await app_client.post(
            "/v1/oci/objects/download/test-bucket/TESTPROFILE",
            json=["object-name.pdf"],
            headers=auth_headers,
        )

    assert resp.status_code == 200
    assert download_thread_ids, "download_object was not invoked"
    assert all(tid != main_thread_id for tid in download_thread_ids), (
        "download_object ran on the event loop thread; a long "
        "synchronous SDK download would block the embed-job "
        "heartbeat and let sibling reapers mark this pod's "
        "running jobs failed"
    )


@pytest.mark.anyio
async def test_oci_download_objects_acquires_client_lock(app_client, auth_headers):
    """[P2] OCI's /objects/download endpoint must serialise on
    _client_lock — same race as the embed store endpoints
    (see ``test_sql_store_acquires_client_lock`` for the full
    reasoning).
    """
    from server.app.api.v1.endpoints import oci as oci_module

    acquisitions: list[str] = []
    real_client_lock = oci_module._client_lock

    @asynccontextmanager
    async def _spy_client_lock(client: str):
        acquisitions.append(client)
        async with real_client_lock(client):
            yield

    # ``oci`` imports ``_client_lock`` from ``server.app.core.client_locks``
    # at module scope, so patch the binding the endpoint actually uses.
    with (
        patch.object(oci_module, "_client_lock", _spy_client_lock),
        patch.object(oci_module, "_find_oci_profile", return_value=MagicMock()),
        patch(
            "server.app.oci.bucket.download_object",
            return_value="/tmp/test/object.pdf",
        ),
        patch(
            "server.app.api.v1.endpoints.oci.get_temp_directory",
            return_value=MagicMock(),
        ),
    ):
        resp = await app_client.post(
            "/v1/oci/objects/download/test-bucket/TESTPROFILE",
            json=["object-name.pdf"],
            headers=auth_headers,
        )

    assert resp.status_code == 200
    assert "server" in acquisitions, (
        "/oci/objects/download did not acquire _client_lock; a "
        "concurrent /embed/ retry restore could observe a new file "
        "appearing in shared mid-restore"
    )


@pytest.mark.anyio
async def test_sql_store_invalid_db_alias(app_client, auth_headers):
    """Returns 503 when db_alias refers to an unavailable database."""
    with patch(
        "server.app.api.v1.endpoints.embed.get_database_settings",
        return_value=None,
    ):
        resp = await app_client.post(
            "/v1/embed/sql/store",
            json={"query": "SELECT col FROM my_table", "db_alias": "NONEXISTENT"},
            headers=auth_headers,
        )
    assert resp.status_code == 503


@pytest.mark.anyio
async def test_sql_store_failure(app_client, auth_headers):
    """Returns 400 when SQL query fails."""
    with (
        patch(
            "server.app.api.v1.endpoints.embed.run_sql_query",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=MagicMock(),
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/sql/store",
            json={"query": "INVALID SQL"},
            headers=auth_headers,
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /local/store
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_local_store(app_client, auth_headers):
    """Successfully stores an uploaded file."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=tmp_path,
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[("files", ("test.txt", io.BytesIO(b"Hello world"), "text/plain"))],
                headers=auth_headers,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert "test.txt" in body


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path_like_name,expected_basename",
    [
        ("../../../up/file", "file"),
        ("/abs/launch.py", "launch.py"),
        ("subdir/../sibling.sh", "sibling.sh"),
    ],
)
async def test_local_store_uses_upload_basename(app_client, auth_headers, path_like_name, expected_basename):
    """Uploads with path-like filenames must land inside temp_directory only.

    The store path runs upload filenames through `safe_filename()`; this
    test asserts the uploaded bytes appear under the expected basename
    inside the temporary directory.
    """
    import tempfile
    from pathlib import Path

    payload = b"sample-payload"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=tmp_path,
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[("files", (path_like_name, io.BytesIO(payload), "text/plain"))],
                headers=auth_headers,
            )
        assert resp.status_code == 200
        # File landed at the expected basename, inside temp_directory.
        safe_path = tmp_path / expected_basename
        assert safe_path.exists()
        assert safe_path.read_bytes() == payload
        # The payload was written only under temp_directory.
        for candidate in (
            Path("/up/file"),
            Path("/abs/launch.py"),
            tmp_path.parent / expected_basename,
        ):
            if candidate.exists():
                assert candidate.read_bytes() != payload, f"Path resolved outside temp_directory to {candidate}"


# ---------------------------------------------------------------------------
# POST / (split and embed)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_split_embed_no_files(app_client, auth_headers):
    """Empty corpus is a synchronous 404 — file claiming runs in the handler.

    The reviewer's P2 concern: claiming files in the background lets a
    follow-up upload leak into this job. Fix: claim files under the
    per-client lock *before* the response. Side-effect: an empty
    shared dir surfaces as 404 on the POST itself, not as a 'failed'
    job — which matches the original inline-flow semantics.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return work_dir if unique else shared_dir

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
    assert resp.status_code == 404
    assert "no files found" in resp.json()["detail"].lower()


@job_store_test
@pytest.mark.anyio
async def test_split_embed_success(app_client, auth_headers):
    """POST schedules a job; polling returns the populated EmbedProcessingResult."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        # Each unique=True call lands a fresh subdirectory, so let the
        # real `get_temp_directory` create the work_dir under tmp_path.
        work_parent = tmp_path / "work_parent"
        work_parent.mkdir()
        # Create a test file in the shared dir (store endpoints put files here)
        test_file = shared_dir / "test.txt"
        test_file.write_text("Hello world content for embedding")

        mock_results = {
            "processed_files": [{"filename": "test.txt", "chunks": 1}],
            "skipped_files": [],
            "total_chunks": 1,
        }

        import tempfile as _tf

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared_dir

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 202
            accepted = resp.json()
            assert accepted["status"] in ("queued", "running")
            assert accepted["location"].endswith(accepted["job_id"])
            terminal = await _poll_until_terminal(app_client, accepted["job_id"], auth_headers)

    assert terminal["status"] == "succeeded"
    assert terminal["result"]["total_chunks"] == 1
    assert terminal["result"]["processed_files"] == [{"filename": "test.txt", "chunks": 1}]


@pytest.mark.anyio
async def test_filename_grouped_pipeline_finalizes_completed_store_before_later_failure(mock_client_db, tmp_path):
    """A later store failure must not leave an earlier store without metadata."""
    from server.app.api.v1.endpoints import embed as embed_module
    from server.app.embed.jobs import JobFailure

    _conn, _pool, db_config = mock_client_db
    handle = MagicMock()
    handle.set_progress = AsyncMock()
    request = VectorStoreConfig(
        embedding_model=ModelIdentity(provider="openai", id=TEST_OPENAI_EMBED_ID),
        chunk_size=1000,
        chunk_overlap=100,
        distance_strategy=DistanceStrategy.COSINE,
        split_by_filename=True,
    )
    chunks = [
        DoclingDocumentChunk("a", {"source": "/work/a.pdf"}, "a"),
        DoclingDocumentChunk("b", {"source": "/work/b.pdf"}, "b"),
    ]

    async def _populate(*, vector_store, **_kwargs):
        if vector_store.alias == "B":
            raise RuntimeError("second store failed")

    with (
        patch.object(embed_module, "get_oci_profile", return_value=MagicMock()),
        patch.object(embed_module, "get_client_embed", return_value=MagicMock()),
        patch.object(
            embed_module,
            "load_and_split_documents",
            return_value=(
                chunks,
                [],
                {"processed_files": [], "skipped_files": [], "total_chunks": 2},
            ),
        ),
        patch.object(embed_module, "populate_vs", side_effect=_populate),
        patch.object(embed_module, "update_vs_comment", new_callable=AsyncMock) as update_comment,
        pytest.raises(JobFailure),
    ):
        await embed_module._run_split_embed_pipeline(
            handle,
            request,
            0,
            "client",
            tmp_path,
            [],
            None,
            db_config,
        )

    assert update_comment.await_count == 1
    assert update_comment.await_args is not None
    assert update_comment.await_args.args[1].alias == "A"


# ---------------------------------------------------------------------------
# POST /oci/store (single-call OCI download + embed)
# ---------------------------------------------------------------------------


def _embed_oci_store_payload(**overrides) -> dict:
    payload = {
        "bucket_name": "rag-source",
        "auth_profile": "DEFAULT",
        "alias": "PRODUCT_DOCS",
        "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
        "chunk_size": 1000,
        "chunk_overlap": 100,
        "distance_strategy": "COSINE",
    }
    payload.update(overrides)
    return payload


@job_store_test
@pytest.mark.anyio
async def test_embed_oci_store_with_explicit_objects(app_client, auth_headers):
    """POST /oci/store downloads listed objects and schedules a job."""
    import tempfile
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_module

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        work_parent = tmp_path / "work_parent"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            import tempfile as _tf

            return Path(_tf.mkdtemp(dir=work_parent)) if unique else tmp_path

        downloaded_into: list[Path] = []

        async def _fake_download_to_dir(target_dir, profile, bucket, names):
            target_dir = Path(str(target_dir))
            downloaded_into.append(target_dir)
            written = []
            for name in names:
                local = target_dir / name.replace("/", "_")
                local.write_text(f"content of {name}")
                written.append(local.name)
            return written, []

        mock_results = {
            "processed_files": [{"filename": "a.pdf", "chunks": 2}],
            "skipped_files": [],
            "total_chunks": 2,
        }

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed._find_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch.object(
                embed_module,
                "download_bucket_objects_to_dir",
                side_effect=_fake_download_to_dir,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/oci/store",
                json=_embed_oci_store_payload(objects=["a.pdf", "nested/b.csv"]),
                headers=auth_headers,
            )
            assert resp.status_code == 202, resp.text
            accepted = resp.json()
            assert accepted["status"] in ("queued", "running")
            assert accepted["location"].endswith(accepted["job_id"])
            terminal = await _poll_until_terminal(app_client, accepted["job_id"], auth_headers)

    assert terminal["status"] == "succeeded", terminal
    assert terminal["result"]["total_chunks"] == 2

    # Downloads landed in the per-request work_dir (under work_parent),
    # not the shared client temp dir — single-call semantics demand the
    # job only embeds objects from this bucket.
    assert downloaded_into, "download_bucket_objects_to_dir was never called"
    assert all(work_parent in p.parents for p in downloaded_into), (
        f"download landed outside the unique work_dir: {downloaded_into}"
    )


@job_store_test
@pytest.mark.anyio
async def test_embed_oci_store_lists_bucket_when_objects_omitted(app_client, auth_headers):
    """When ``objects`` is omitted, every supported bucket object is downloaded."""
    import tempfile
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_module

    bucket_listing = ["report.pdf", "notes.md", "image.bin", "skip.exe", "data.csv"]
    captured_names: list[list[str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        work_parent = tmp_path / "work_parent"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            import tempfile as _tf

            return Path(_tf.mkdtemp(dir=work_parent)) if unique else tmp_path

        async def _fake_download_to_dir(target_dir, profile, bucket, names):
            captured_names.append(list(names))
            target_dir = Path(str(target_dir))
            for name in names:
                (target_dir / name.replace("/", "_")).write_text("data")
            return [n.replace("/", "_") for n in names], []

        mock_results = {
            "processed_files": [],
            "skipped_files": [],
            "total_chunks": 0,
        }

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed._find_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_bucket_object_names",
                return_value=bucket_listing,
            ),
            patch.object(
                embed_module,
                "download_bucket_objects_to_dir",
                side_effect=_fake_download_to_dir,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/oci/store",
                json=_embed_oci_store_payload(),
                headers=auth_headers,
            )
            assert resp.status_code == 202, resp.text
            accepted = resp.json()
            await _poll_until_terminal(app_client, accepted["job_id"], auth_headers)

    # Unsupported extensions (.bin, .exe) must be filtered before download.
    assert captured_names, "download helper not invoked"
    assert sorted(captured_names[0]) == ["data.csv", "notes.md", "report.pdf"]


@pytest.mark.anyio
async def test_embed_oci_store_invalid_auth_profile(app_client, auth_headers):
    """Unknown auth_profile is rejected synchronously with 404 — no job is created."""
    with patch(
        "server.app.api.v1.endpoints.embed._find_oci_profile",
        side_effect=HTTPException(status_code=404, detail="OCI profile config not found: NOPE"),
    ):
        resp = await app_client.post(
            "/v1/embed/oci/store",
            json=_embed_oci_store_payload(auth_profile="NOPE"),
            headers=auth_headers,
        )
    assert resp.status_code == 404
    assert "OCI profile" in resp.json()["detail"]


@pytest.mark.anyio
async def test_embed_oci_store_empty_bucket_returns_404(app_client, auth_headers):
    """Bucket with no supported objects → 404; no job is scheduled."""
    with (
        patch(
            "server.app.api.v1.endpoints.embed._find_oci_profile",
            return_value=MagicMock(),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_oci_profile",
            return_value=MagicMock(),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_bucket_object_names",
            return_value=["unknown.bin", "skip.exe"],
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/oci/store",
            json=_embed_oci_store_payload(),
            headers=auth_headers,
        )
    assert resp.status_code == 404
    assert "No supported objects" in resp.json()["detail"]


@pytest.mark.anyio
async def test_embed_oci_store_rejects_partial_download(app_client, auth_headers):
    """[P2] Single-call OCI must not embed a partial corpus.

    ``download_bucket_objects_to_dir`` logs failures and drops them
    from the returned basenames. The two-step ``/v1/oci/objects/download``
    flow is fine with that — the caller sees the diff between request
    and response. But the single-call endpoint replies 202 + job_id and
    has no response path for the caller to detect a missing object, so
    it must fail synchronously when any requested object failed to
    download.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_module

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        work_parent = tmp_path / "work_parent"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else tmp_path

        def _flaky_download(directory, name, bucket, profile):
            # Simulate a typoed key / transient SDK failure for one
            # specific object in the request.
            if name == "missing.pdf":
                raise RuntimeError("OCI 404 NotFound")
            local = Path(directory) / name.replace("/", "_")
            local.write_text(f"data {name}")
            return str(local)

        @asynccontextmanager
        async def _passthrough_client_lock(_client: str):
            yield

        # ``manager.submit`` should never be reached on this path.
        from server.app.embed import jobs as jobs_mod

        submit_called = False
        original_submit = jobs_mod.EmbedJobManager.submit

        async def _spy_submit(self, *args, **kwargs):
            nonlocal submit_called
            submit_called = True
            return await original_submit(self, *args, **kwargs)

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed._find_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch.object(embed_module, "_client_lock", _passthrough_client_lock),
            patch("server.app.oci.bucket.download_object", side_effect=_flaky_download),
            patch.object(jobs_mod.EmbedJobManager, "submit", _spy_submit),
        ):
            resp = await app_client.post(
                "/v1/embed/oci/store",
                json=_embed_oci_store_payload(objects=["good.pdf", "missing.pdf"]),
                headers=auth_headers,
            )

        assert resp.status_code == 502, resp.text
        detail = resp.json()["detail"]
        assert "missing.pdf" in str(detail), f"Expected the failed key in the error detail; got: {detail!r}"
        assert not submit_called, (
            "Embed job was scheduled despite a partial-download failure — "
            "single-call endpoint must reject synchronously before submit."
        )
        # work_dir is rmtreed on failure, so nothing remains under work_parent.
        leftover = list(work_parent.iterdir())
        assert leftover == [], f"work_dir remained after partial-download rejection: {leftover}"


@job_store_test
@pytest.mark.anyio
async def test_embed_oci_store_dedupes_colliding_flattened_paths(app_client, auth_headers):
    """[P2] Colliding flattened OCI keys must not be passed to the pipeline twice.

    Bucket keys ``a/b.txt`` and ``a_b.txt`` both flatten to ``a_b.txt``
    on disk; the download helper writes them sequentially with
    last-writer-wins semantics but returns the same basename once per
    key. Building the pipeline's file list naively from that return
    duplicates the same local path, which would feed
    ``load_and_split_documents`` the same file twice and double the
    chunks for that object.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_module

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        work_parent = tmp_path / "work_parent"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else tmp_path

        def _real_flatten_download(directory, name, bucket, profile):
            # Mirror the production flatten + last-writer-wins write so
            # both colliding inputs hit the same on-disk file.
            local = Path(directory) / name.replace("/", "_").lstrip("_")
            local.write_text(f"data from {name}")
            return str(local)

        @asynccontextmanager
        async def _passthrough_client_lock(_client: str):
            yield

        captured_files: list[list[Path]] = []

        def _capture_files(files, *args, **kwargs):
            captured_files.append(list(files))
            return ([], [], {"processed_files": [], "skipped_files": [], "total_chunks": 0})

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed._find_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch.object(embed_module, "_client_lock", _passthrough_client_lock),
            patch("server.app.oci.bucket.download_object", side_effect=_real_flatten_download),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                side_effect=_capture_files,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/oci/store",
                json=_embed_oci_store_payload(objects=["a/b.txt", "a_b.txt"]),
                headers=auth_headers,
            )
            assert resp.status_code == 202, resp.text
            await _poll_until_terminal(app_client, resp.json()["job_id"], auth_headers)

        assert captured_files, "load_and_split_documents was never called"
        files_seen = captured_files[0]
        assert len(files_seen) == len(set(map(str, files_seen))), (
            f"Pipeline received duplicate file paths from colliding "
            f"flattened OCI keys; got {[str(p) for p in files_seen]}. "
            f"After flatten, 'a/b.txt' and 'a_b.txt' both target the "
            f"same local file — the endpoint must pass each path once."
        )


@pytest.mark.anyio
async def test_embed_oci_store_retryable_submit_does_not_restore_to_shared(app_client, auth_headers):
    """[P2] Retryable submit failure must NOT restore per-request bucket
    downloads into the client's shared embedding directory.

    Single-call contract: ``/v1/embed/oci/store`` downloads bucket
    objects into a per-request ``work_dir`` and does not consume
    shared staging. If a transient CORE/DB blip during
    ``manager.submit`` triggered the two-step flow's restore-to-shared
    cleanup, those OCI files would persist as staged input for the
    next two-step ``POST /v1/embed/`` request and would be embedded
    even though the user did not stage them.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_module
    from server.app.embed import jobs as jobs_mod

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        # Shared starts empty — single-call OCI does not stage anything
        # into it; any file appearing in shared after this request was
        # restored from work_dir.
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        async def _fake_download_to_dir(target_dir, profile, bucket, names):
            target_dir = Path(str(target_dir))
            written = []
            for name in names:
                local = target_dir / name.replace("/", "_")
                local.write_text(f"bucket payload {name}")
                written.append(local.name)
            return written, []

        async def _timing_out_submit(*_args, **_kwargs):
            raise TimeoutError("CORE pool.acquire timed out")

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed._find_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch.object(
                embed_module,
                "download_bucket_objects_to_dir",
                side_effect=_fake_download_to_dir,
            ),
            patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _timing_out_submit,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/oci/store",
                json=_embed_oci_store_payload(objects=["bucket-only.pdf"]),
                headers=auth_headers,
            )

        assert resp.status_code == 503, resp.text
        restored = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert restored == [], (
            f"OCI bucket downloads were restored into shared staging on "
            f"retryable failure: {restored}. The single-call endpoint must "
            f"not restore its per-request work_dir into the shared client "
            f"embedding dir."
        )


@pytest.mark.anyio
async def test_embed_oci_store_failure_preserves_staged_sql(app_client, auth_headers):
    """[P2] Failed /v1/embed/oci/store must NOT delete staged SQL scratch files.

    The single-call endpoint uses a per-request work_dir and does not
    consume staged sources, so any pre-claim error must leave the
    user's staged SQL CSVs intact. Sweeping them on an OCI-only error
    would remove work the user staged via ``/embed/sql/store``.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        sql_csv = shared / "_sqlsrc_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.csv"
        sql_csv.write_text("col1,col2\n1,2\n")

        def _fake_get_temp(_client, _function, *, unique=False):
            return shared if not unique else (tmp_path / "work")

        # Trigger a synchronous HTTPException via an unknown auth_profile.
        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed._find_oci_profile",
                side_effect=HTTPException(status_code=404, detail="OCI profile config not found: NOPE"),
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/oci/store",
                json=_embed_oci_store_payload(auth_profile="NOPE"),
                headers=auth_headers,
            )

        assert resp.status_code == 404
        assert sql_csv.exists(), (
            "OCI-only error path swept the user's staged SQL CSV out of "
            "shared. The single-call endpoint never claims staged files, "
            "so it must leave them in place on failure."
        )


@pytest.mark.anyio
async def test_embed_oci_store_missing_required_fields(app_client, auth_headers):
    """Missing embedding_model / distance_strategy → 400 (same guard as POST /embed/)."""
    with (
        patch(
            "server.app.api.v1.endpoints.embed._find_oci_profile",
            return_value=MagicMock(),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_oci_profile",
            return_value=MagicMock(),
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/oci/store",
            json={
                "bucket_name": "rag-source",
                "auth_profile": "DEFAULT",
                "alias": "PRODUCT_DOCS",
                "objects": ["a.pdf"],
            },
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert "embedding_model" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_refresh_no_changes(app_client, auth_headers):
    """Returns success with no-changes message."""
    mock_vs = VectorStoreConfig(
        vector_store="MY_VS",
        embedding_model=ModelIdentity(provider="openai", id=TEST_OPENAI_EMBED_ID),
        chunk_size=1000,
        chunk_overlap=100,
    )
    with (
        patch(
            "server.app.api.v1.endpoints.embed.get_oci_profile",
            return_value=MagicMock(),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_vector_store_by_alias",
            new_callable=AsyncMock,
            return_value=mock_vs,
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_bucket_objects_with_metadata",
            return_value=[{"name": "test.pdf", "etag": "abc", "time_modified": "2026-01-01", "size": 100}],
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_processed_objects_metadata",
            new_callable=AsyncMock,
            return_value={"test.pdf": {"etag": "abc", "time_modified": "2026-01-01", "size": 100}},
        ),
        patch(
            "server.app.api.v1.endpoints.embed.detect_changed_objects",
            return_value=([], []),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_total_chunks_count",
            new_callable=AsyncMock,
            return_value=50,
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/refresh",
            json={"vector_store_alias": "test", "bucket_name": "my-bucket"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["total_chunks_in_store"] == 50


@pytest.mark.anyio
async def test_refresh_uses_request_auth_profile(app_client, auth_headers):
    """Refresh endpoint uses auth_profile from the request body, not the client default."""
    custom_profile = MagicMock()
    custom_profile.auth_profile = "CUSTOM_PROFILE"
    default_profile = MagicMock()
    default_profile.auth_profile = "DEFAULT"

    mock_vs = VectorStoreConfig(
        vector_store="MY_VS",
        embedding_model=ModelIdentity(provider="openai", id=TEST_OPENAI_EMBED_ID),
        chunk_size=1000,
        chunk_overlap=100,
    )
    with (
        patch(
            "server.app.api.v1.endpoints.embed._find_oci_profile",
            return_value=custom_profile,
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_vector_store_by_alias",
            new_callable=AsyncMock,
            return_value=mock_vs,
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_bucket_objects_with_metadata",
        ) as mock_get_objects,
        patch(
            "server.app.api.v1.endpoints.embed.get_processed_objects_metadata",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "server.app.api.v1.endpoints.embed.detect_changed_objects",
            return_value=([], []),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_total_chunks_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        mock_get_objects.return_value = []
        resp = await app_client.post(
            "/v1/embed/refresh",
            json={
                "vector_store_alias": "test",
                "bucket_name": "my-bucket",
                "auth_profile": "CUSTOM_PROFILE",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200
    # Verify the custom profile was passed to get_bucket_objects_with_metadata
    mock_get_objects.assert_called_once_with("my-bucket", custom_profile)


@pytest.mark.anyio
async def test_refresh_invalid_auth_profile(app_client, auth_headers):
    """Returns 404 when requested auth_profile does not exist."""

    with patch(
        "server.app.api.v1.endpoints.embed._find_oci_profile",
        side_effect=HTTPException(status_code=404, detail="OCI profile config not found: NONEXISTENT"),
    ):
        resp = await app_client.post(
            "/v1/embed/refresh",
            json={
                "vector_store_alias": "test",
                "bucket_name": "my-bucket",
                "auth_profile": "NONEXISTENT",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 404
    assert "NONEXISTENT" in resp.json()["detail"]


@pytest.mark.anyio
async def test_refresh_not_found(app_client, auth_headers):
    """Returns 400 when vector store alias not found."""
    with (
        patch(
            "server.app.api.v1.endpoints.embed.get_oci_profile",
            return_value=MagicMock(),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_vector_store_by_alias",
            new_callable=AsyncMock,
            side_effect=ValueError("Vector store with alias 'missing' not found"),
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/refresh",
            json={"vector_store_alias": "missing", "bucket_name": "my-bucket"},
            headers=auth_headers,
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DB unavailable
# ---------------------------------------------------------------------------


@job_store_test
@pytest.mark.anyio
async def test_split_embed_concurrent_no_interference(app_client, auth_headers):
    """Concurrent POSTs: one claims files (202), the other gets a sync 404.

    File claiming now runs synchronously under the per-client lock so
    only the first POST through the lock can hand its corpus to the
    background pipeline. The second POST finds the shared dir empty
    and returns 404 on the POST itself — a 202 with a doomed job
    would be misleading because the failure is a precondition issue,
    not a pipeline error.
    """
    import asyncio
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        # Create a test file in the shared dir
        (shared_dir / "test.txt").write_text("content for embedding")

        work_counter = 0

        def _fake_get_temp(_client, _function, *, unique=False):
            nonlocal work_counter
            if unique:
                work_counter += 1
                wd = tmp_path / f"work_{work_counter}"
                wd.mkdir(exist_ok=True)
                return wd
            return shared_dir

        mock_results = {
            "processed_files": [{"filename": "test.txt", "chunks": 1}],
            "skipped_files": [],
            "total_chunks": 1,
        }

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
        ):
            req_json = {
                "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "distance_strategy": "COSINE",
            }
            r1, r2 = await asyncio.gather(
                app_client.post("/v1/embed/", json=req_json, headers=auth_headers),
                app_client.post("/v1/embed/", json=req_json, headers=auth_headers),
            )
            statuses = sorted([r1.status_code, r2.status_code])
            assert statuses == [202, 404]
            # Drain the accepted job so we don't leak a background task.
            accepted = next(r for r in (r1, r2) if r.status_code == 202)
            terminal = await _poll_until_terminal(app_client, accepted.json()["job_id"], auth_headers)
            assert terminal["status"] == "succeeded"


@pytest.mark.anyio
async def test_split_embed_race_restores_files(app_client, auth_headers):
    """Files already moved into work_dir are restored to shared_dir on race collision."""
    import shutil
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        # Place two files in shared_dir
        (shared_dir / "a.txt").write_text("aaa")
        (shared_dir / "b.txt").write_text("bbb")

        original_move = shutil.move
        move_count = 0
        failed = False

        def _move_then_fail(src, dst, **kwargs):
            """Allow the first move, raise FileNotFoundError on second, then allow rescues."""
            nonlocal move_count, failed
            move_count += 1
            if failed:
                # After the race error, allow rescue moves
                return original_move(src, dst, **kwargs)
            if move_count == 1:
                return original_move(src, dst, **kwargs)
            failed = True
            raise FileNotFoundError(f"Simulated race: {src}")

        def _fake_get_temp(_client, _function, *, unique=False):
            return work_dir if unique else shared_dir

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.shutil.move",
                side_effect=_move_then_fail,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        # File claiming runs synchronously now, so the restore happens
        # on the request thread and surfaces as a sync 404.
        assert resp.status_code == 404
        # The file that was successfully moved must be restored to shared_dir
        restored_files = sorted(f.name for f in shared_dir.iterdir() if f.is_file())
        assert "a.txt" in restored_files, f"Expected a.txt restored in shared_dir, got: {restored_files}"
        # work_dir should be cleaned up
        assert not work_dir.exists()


@pytest.mark.anyio
async def test_drop_vs_db_unavailable(app_client, auth_headers):
    """Returns 503 when database is not available."""
    with patch(
        "server.app.api.v1.endpoints.embed._get_client_db_config",
        side_effect=HTTPException(status_code=503, detail="Database is not available"),
    ):
        resp = await app_client.delete("/v1/embed/MY_VS", headers=auth_headers)
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /web/store — streaming
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_web_store_pdf_streaming(app_client, auth_headers):
    """PDF download streams chunks to disk instead of buffering."""
    import tempfile
    from pathlib import Path

    pdf_chunks = [b"%PDF-1.4 chunk1", b" chunk2", b" chunk3"]

    mock_response = AsyncMock()
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_response.raise_for_status = MagicMock()

    async def _aiter_bytes():
        for c in pdf_chunks:
            yield c

    mock_response.aiter_bytes = _aiter_bytes

    @asynccontextmanager
    async def _fake_stream(_method, _url, **_kwargs):
        yield mock_response

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                return_value=tmp_path,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.validate_structural",
                return_value="https://example.com/report.pdf",
            ),
            patch(
                "server.app.api.v1.endpoints.embed.SafeAsyncClient.stream",
                side_effect=_fake_stream,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/web/store",
                json=["https://example.com/report.pdf"],
                headers=auth_headers,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "report.pdf" in body
        written = (tmp_path / "report.pdf").read_bytes()
        assert written == b"".join(pdf_chunks)


# ---------------------------------------------------------------------------
# _extract_zip — size-cap and nested-archive guard tests
#
# The helper enforces declared-size caps and skips nested archive members.
# These tests pin the cap values and the nested-archive skip so a future
# refactor cannot silently remove them.
# ---------------------------------------------------------------------------


def _make_zip(path, members):
    """Build a real ZIP at *path* from (name, bytes) pairs — returns *path*."""
    import zipfile

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return path


def _fake_zipinfo(name, file_size):
    """Return a ZipInfo-like stub whose ``file_size`` is the declared value.

    `_extract_zip`'s three size caps read `file_size` off ``infolist()``
    entries, so patching that method with stubs is enough to drive the
    caps without writing gigabyte-sized fixtures.
    """
    import zipfile

    info = zipfile.ZipInfo(name)
    info.file_size = file_size
    return info


def test_extract_zip_happy_path(tmp_path):
    """Valid archive: members extracted, metadata populated, bytes intact."""
    from server.app.embed.staging import _extract_zip

    src = _make_zip(tmp_path / "ok.zip", [("a.txt", b"hello"), ("b.txt", b"world")])
    dest = tmp_path / "out"
    dest.mkdir()

    metadata = _extract_zip(src, dest)

    assert (dest / "a.txt").read_bytes() == b"hello"
    assert (dest / "b.txt").read_bytes() == b"world"
    assert set(metadata) == {"a.txt", "b.txt"}
    assert metadata["a.txt"]["size"] == 5
    assert "time_modified" in metadata["a.txt"]


def test_extract_zip_rejects_too_many_members(tmp_path):
    """More than _ZIP_MAX_FILES members → 400 before any write."""
    import zipfile as _zf

    from server.app.embed.staging import _ZIP_MAX_FILES, _extract_zip

    src = _make_zip(tmp_path / "many.zip", [("seed.txt", b"x")])
    dest = tmp_path / "out"
    dest.mkdir()

    fake = [_fake_zipinfo(f"f{i}.txt", 10) for i in range(_ZIP_MAX_FILES + 1)]
    with (
        patch.object(_zf.ZipFile, "infolist", return_value=fake),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)
    assert exc.value.status_code == 400
    assert "max file count" in exc.value.detail.lower()
    # Nothing extracted.
    assert list(dest.iterdir()) == []


def test_extract_zip_rejects_oversize_total(tmp_path):
    """Sum of declared file_size > _ZIP_MAX_TOTAL_BYTES → 400."""
    import zipfile as _zf

    from server.app.embed.staging import _ZIP_MAX_TOTAL_BYTES, _extract_zip

    src = _make_zip(tmp_path / "total.zip", [("seed.txt", b"x")])
    dest = tmp_path / "out"
    dest.mkdir()

    # Six chunks each under the per-file cap but summing above the total cap.
    chunk = _ZIP_MAX_TOTAL_BYTES // 5  # 5 chunks = _ZIP_MAX_TOTAL_BYTES; 6 = 120%
    fake = [_fake_zipinfo(f"chunk{i}.bin", chunk) for i in range(6)]
    with (
        patch.object(_zf.ZipFile, "infolist", return_value=fake),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)
    assert exc.value.status_code == 400
    assert "decompressed size exceeds limit" in exc.value.detail.lower()
    assert list(dest.iterdir()) == []


def test_extract_zip_rejects_oversize_single_file(tmp_path):
    """Declared per-file size > _ZIP_MAX_FILE_BYTES → 400."""
    import zipfile as _zf

    from server.app.embed.staging import _ZIP_MAX_FILE_BYTES, _extract_zip

    src = _make_zip(tmp_path / "single.zip", [("seed.txt", b"x")])
    dest = tmp_path / "out"
    dest.mkdir()

    # One bloated declaration — sits below the total cap but above per-file.
    fake = [_fake_zipinfo("huge.bin", _ZIP_MAX_FILE_BYTES + 1)]
    with (
        patch.object(_zf.ZipFile, "infolist", return_value=fake),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)
    assert exc.value.status_code == 400
    assert "per-file size limit" in exc.value.detail.lower()
    assert list(dest.iterdir()) == []


@pytest.mark.parametrize("bad_ext", [".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar"])
def test_extract_zip_skips_nested_archives(tmp_path, bad_ext):
    """Nested-archive members are silently skipped, not extracted."""
    from server.app.embed.staging import _extract_zip

    src = _make_zip(
        tmp_path / "nested.zip",
        [("good.txt", b"ok"), (f"bomb{bad_ext}", b"nested-archive-bytes")],
    )
    dest = tmp_path / "out"
    dest.mkdir()

    metadata = _extract_zip(src, dest)

    # Only the non-archive member landed on disk.
    extracted = {p.name for p in dest.iterdir()}
    assert extracted == {"good.txt"}
    assert set(metadata) == {"good.txt"}


@pytest.mark.anyio
async def test_local_store_rolls_back_batch_when_later_zip_fails(app_client, auth_headers):
    """Mixed batch: earlier uploads are discarded when a later ZIP fails.

    Request-level staging makes the batch atomic: either every upload in
    the batch is promoted into the shared embedding temp directory, or
    none of them are.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Pre-existing file from a previous /local/store request that
        # must survive this request's rollback.
        (tmp_path / "prior.txt").write_bytes(b"prior content")

        with patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=tmp_path,
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[
                    ("files", ("good.txt", io.BytesIO(b"this-request content"), "text/plain")),
                    ("files", ("bad.zip", io.BytesIO(b"not a zip"), "application/zip")),
                ],
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert (tmp_path / "prior.txt").read_bytes() == b"prior content"
        # good.txt from this (failed) request is not left behind.
        assert not (tmp_path / "good.txt").exists()
        # No staging residue.
        assert {p.name for p in tmp_path.iterdir() if p.is_file()} == {"prior.txt"}


@pytest.mark.parametrize(
    "exc_to_raise",
    [
        NotImplementedError("That compression method is not supported"),
        RuntimeError("unsupported extract version"),
        OSError("truncated file"),
    ],
    ids=["unsupported_version", "runtime_error", "os_error"],
)
def test_extract_zip_translates_constructor_errors_to_400(tmp_path, exc_to_raise):
    """ZipFile(...) constructor failures for user-controlled bad archives surface as 400.

    The stdlib can raise NotImplementedError (e.g. unsupported extract
    version / compression method signalled in the central directory),
    RuntimeError, or OSError from the ZipFile constructor itself, before
    any infolist/open call is reached. These all represent user-input
    errors and must translate to HTTP 400 rather than a generic 500.
    """
    import zipfile as _zf

    from server.app.embed.staging import _extract_zip

    src = tmp_path / "archive.zip"
    src.write_bytes(b"any-bytes")  # content irrelevant — constructor is mocked
    dest = tmp_path / "dest"
    dest.mkdir()

    real_init = _zf.ZipFile.__init__

    def flaky_init(self, file, mode="r", *args, **kwargs):
        raise exc_to_raise

    with (
        patch.object(_zf.ZipFile, "__init__", new=flaky_init),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)
    assert exc.value.status_code == 400
    # No staging residue left in dest.
    assert [p for p in dest.iterdir()] == []

    del real_init  # silence unused-name lint


@pytest.mark.parametrize(
    "exc_to_raise",
    [
        RuntimeError("File 'a.txt' is encrypted, password required for extraction"),
        NotImplementedError("compression type 14 (lzma) is not supported"),
        OSError("corrupt local file header"),
    ],
    ids=["encrypted", "unsupported_compression", "corrupt_local_header"],
)
def test_extract_zip_translates_member_open_errors_to_400(tmp_path, exc_to_raise):
    """zip_ref.open(info) failures for user-controlled bad archives surface as 400.

    Password-protected archives raise RuntimeError, unsupported
    compression methods raise NotImplementedError, and certain header
    corruptions raise OSError before any decompression begins. All
    three are user-input issues and must translate to HTTP 400 rather
    than a generic 500.
    """
    import zipfile as _zf

    from server.app.embed.staging import _extract_zip

    src = _make_zip(tmp_path / "archive.zip", [("a.txt", b"hi")])
    dest = tmp_path / "dest"
    dest.mkdir()

    def flaky_open(self, info, *args, **kwargs):
        raise exc_to_raise

    with (
        patch.object(_zf.ZipFile, "open", new=flaky_open),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)
    assert exc.value.status_code == 400


class _ExplodingZipSource:
    """Fake zipfile.ZipExtFile whose .read() raises *exc* — simulates a corrupt member.

    The real ZipExtFile streams through a decompressor, so a corrupted
    DEFLATE/BZIP2/LZMA payload raises from ``read``. We can drive the
    same code path by patching ``ZipFile.open`` to return one of these.
    """

    def __init__(self, exc):
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _n=-1):
        raise self._exc

    def close(self):
        return None


@pytest.mark.parametrize(
    "exc_factory,exc_id",
    [
        (lambda: __import__("zlib").error("synthetic DEFLATE corruption"), "zlib_error"),
        (lambda: OSError("Invalid bzip2 data stream"), "bz2_oserror"),
        (lambda: __import__("lzma").LZMAError("Corrupt input data"), "lzma_error"),
    ],
    ids=["zlib_error", "bz2_oserror", "lzma_error"],
)
def test_extract_zip_translates_decompressor_read_errors_to_400(tmp_path, exc_factory, exc_id):
    """Decompressor read failures surface as 400 across DEFLATE / bzip2 / LZMA.

    ZIPs using bzip2 or LZMA compression raise ``OSError`` or
    ``lzma.LZMAError`` (respectively) from the decompressor on corrupt
    member data — neither is a ``BadZipFile`` nor a ``zlib.error``.
    Without explicit translation those would surface from
    ``store_local_file`` as 500 for user-controlled bad uploads. The
    read side of the per-member streaming copy catches
    ``OSError | zlib.error | lzma.LZMAError`` and re-raises as HTTP 400.
    """
    import zipfile as _zf

    from server.app.embed.staging import _extract_zip

    del exc_id  # parametrize id only — exc is built fresh per case

    src = _make_zip(tmp_path / "archive.zip", [("a.txt", b"hello")])
    dest = tmp_path / "dest"
    dest.mkdir()

    def fake_open(self, info, *args, **kwargs):
        return _ExplodingZipSource(exc_factory())

    with (
        patch.object(_zf.ZipFile, "open", new=fake_open),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)
    assert exc.value.status_code == 400
    # No staging residue.
    assert list(dest.iterdir()) == []


def test_extract_zip_target_write_oserror_remains_500(tmp_path):
    """Disk-write OSError is NOT translated to 400 — that's a real server failure.

    The read-side wrapper for decompressor errors must not accidentally
    catch write-side OSError (e.g. disk full, ENOSPC, EROFS). Those are
    legitimate 500s and the caller should see them surface as such.
    """
    from pathlib import Path

    from server.app.embed.staging import _extract_zip

    src = _make_zip(tmp_path / "archive.zip", [("a.txt", b"hello")])
    dest = tmp_path / "dest"
    dest.mkdir()

    real_path_open = Path.open

    def flaky_path_open(self, mode="r", *args, **kwargs):
        # Only fail the staging path's binary write; let every other
        # open (metadata json, mkdtemp internals) proceed unhurt.
        if mode == "wb" and ".zipextract_" in str(self):
            handle = real_path_open(self, mode, *args, **kwargs)

            def _bad_write(_data):
                raise OSError("ENOSPC: no space left on device")

            handle.write = _bad_write
            return handle
        return real_path_open(self, mode, *args, **kwargs)

    with patch.object(Path, "open", new=flaky_path_open), pytest.raises(OSError, match="ENOSPC"):
        _extract_zip(src, dest)


def test_extract_zip_translates_infolist_error_to_400(tmp_path):
    """A corrupt central directory (BadZipFile from infolist) surfaces as 400."""
    import zipfile as _zf

    from server.app.embed.staging import _extract_zip

    src = _make_zip(tmp_path / "archive.zip", [("a.txt", b"hi")])
    dest = tmp_path / "dest"
    dest.mkdir()

    def exploding_infolist(self):
        raise _zf.BadZipFile("synthetic corrupt central directory")

    with (
        patch.object(_zf.ZipFile, "infolist", new=exploding_infolist),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)
    assert exc.value.status_code == 400


def test_extract_zip_handles_member_named_like_backup_prefix(tmp_path):
    """A member called `.backup_<other>` does not collide with backup storage.

    The backup-naming scheme used during promotion must not collide with
    archive members whose name happens to start with `.backup_`. If an
    archive contains both `foo.txt` and `.backup_foo.txt` and dest
    already holds `foo.txt`, both members must land with their archive
    bytes intact.
    """
    from server.app.embed.staging import _extract_zip

    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "foo.txt").write_bytes(b"prior foo")

    src = _make_zip(
        tmp_path / "archive.zip",
        [
            ("foo.txt", b"new foo from zip"),
            (".backup_foo.txt", b"legit user member"),
        ],
    )

    metadata = _extract_zip(src, dest)

    assert (dest / "foo.txt").read_bytes() == b"new foo from zip"
    assert (dest / ".backup_foo.txt").read_bytes() == b"legit user member"
    assert set(metadata) == {"foo.txt", ".backup_foo.txt"}


@pytest.mark.anyio
async def test_local_store_locks_before_creating_staging_dir(app_client, auth_headers):
    """The per-client lock must be acquired *before* the staging directory exists.

    Holding the lock only around `_promote_atomically` would leave a
    window where the staging directory is being populated but nothing
    has appeared in temp_directory. A concurrent `split_embed` on the
    same client could enter `_prepare_work_dir`, see no files, and
    return 404 even though the upload is mid-flight. Taking the lock at
    the top of `store_local_file` serialises producer/consumer across
    the entire upload.
    """
    import tempfile
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_mod

    call_log: list[tuple[str, object]] = []
    real_client_lock = embed_mod._client_lock
    real_mkdtemp = embed_mod.tempfile.mkdtemp

    @asynccontextmanager
    async def logging_client_lock(client):
        call_log.append(("get_lock", client))
        async with real_client_lock(client):
            yield

    def logging_mkdtemp(*args, **kwargs):
        call_log.append(("mkdtemp", kwargs.get("prefix")))
        return real_mkdtemp(*args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                return_value=tmp_path,
            ),
            patch.object(embed_mod, "_client_lock", logging_client_lock),
            patch.object(embed_mod.tempfile, "mkdtemp", side_effect=logging_mkdtemp),
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[("files", ("a.txt", io.BytesIO(b"alpha"), "text/plain"))],
                headers={**auth_headers, "Client": "lock-scope"},
            )
    assert resp.status_code == 200
    lock_idx = next(i for i, (op, _) in enumerate(call_log) if op == "get_lock")
    request_staging_idx = next(
        i for i, (op, prefix) in enumerate(call_log) if op == "mkdtemp" and prefix == ".request_"
    )
    assert lock_idx < request_staging_idx, (
        f"lock must be acquired before .request_ staging dir is created; got {call_log}"
    )


def test_extract_zip_rejects_directory_collision_in_dest(tmp_path):
    """A pre-existing directory at dest/<member-name> must not be replaced.

    Backup-and-rename of a directory would silently move a live work
    tree out from under whichever request created it. Surfacing this as
    a 409 matches the open("wb") behaviour (IsADirectoryError) and
    protects concurrent split_embed work_dirs.
    """
    from server.app.embed.staging import _extract_zip

    dest = tmp_path / "dest"
    dest.mkdir()
    # Pre-existing directory at dest/a.txt — could be e.g. a live
    # work_dir from split_embed that happened to share the name.
    (dest / "a.txt").mkdir()
    (dest / "a.txt" / "live-work-file").write_bytes(b"sentinel")

    src = _make_zip(tmp_path / "archive.zip", [("a.txt", b"new bytes")])

    with pytest.raises(HTTPException) as exc:
        _extract_zip(src, dest)
    assert exc.value.status_code == 409
    # Directory survives intact.
    assert (dest / "a.txt").is_dir()
    assert (dest / "a.txt" / "live-work-file").read_bytes() == b"sentinel"


@pytest.mark.anyio
async def test_local_store_rejects_directory_collision(app_client, auth_headers):
    """An upload whose basename collides with a pre-existing directory is rejected."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "foo").mkdir()  # could be a concurrent split_embed work_dir
        (tmp_path / "foo" / "marker").write_bytes(b"keep me")

        with patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=tmp_path,
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[("files", ("foo", io.BytesIO(b"new bytes"), "application/octet-stream"))],
                headers={**auth_headers, "Client": "dir-collide"},
            )
        assert resp.status_code == 409
        assert (tmp_path / "foo").is_dir()
        assert (tmp_path / "foo" / "marker").read_bytes() == b"keep me"


@pytest.mark.anyio
async def test_client_lock_evicts_lru_when_full(monkeypatch):
    """The lock registry caps at settings.max_clients, evicting the LRU first.

    `_client_promotion_locks` is bounded with the same LRU pattern as
    `_client_store` so an unbounded sequence of Client header values
    cannot accumulate process state until restart.
    """
    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.core import client_locks
    from server.app.core.settings import settings as core_settings

    client_locks._client_promotion_locks.clear()
    monkeypatch.setattr(core_settings, "max_clients", 3)

    async with embed_mod._client_lock("a"):
        pass
    async with embed_mod._client_lock("b"):
        pass
    async with embed_mod._client_lock("c"):
        pass
    # Touch "a" so it becomes most-recently-used; "b" should now be
    # eligible for eviction.
    async with embed_mod._client_lock("a"):
        pass
    async with embed_mod._client_lock("d"):
        pass

    keys = list(client_locks._client_promotion_locks)
    assert keys == ["c", "a", "d"], f"expected LRU order [c, a, d]; got {keys}"
    assert len(client_locks._client_promotion_locks) == 3


@pytest.mark.anyio
async def test_client_lock_skips_in_use_entry_during_eviction(monkeypatch):
    """In-use entries (holder or queued waiter) are not evicted."""
    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.core import client_locks
    from server.app.core.settings import settings as core_settings

    client_locks._client_promotion_locks.clear()
    monkeypatch.setattr(core_settings, "max_clients", 2)

    # Pre-populate "held" and "spare" entries (users == 0 after exit).
    async with embed_mod._client_lock("held"):
        pass
    async with embed_mod._client_lock("spare"):
        pass

    # Occupy "held" while a fresh _client_lock("new") is requested:
    # eviction must NOT cull "held" — pick the next-oldest unused
    # entry ("spare") instead.
    async with embed_mod._client_lock("held"), embed_mod._client_lock("new"):
        pass

    assert "held" in client_locks._client_promotion_locks
    assert "spare" not in client_locks._client_promotion_locks
    assert "new" in client_locks._client_promotion_locks


@pytest.mark.anyio
async def test_client_lock_skips_entry_with_queued_waiter(monkeypatch):
    """A registry entry with users>0 from a queued waiter survives eviction.

    Between `release()` (which clears `_locked`) and the woken waiter
    resuming, the underlying ``asyncio.Lock`` reports
    ``locked() == False`` even though a queued waiter is about to
    acquire it. A registry that gated eviction on ``locked()`` could
    cull such an entry under client pressure; a subsequent request for
    the same client would then create a *second* Lock and run
    concurrently with the still-pending waiter, defeating the per-client
    serialisation. Refcounting holders + waiters under
    ``_client_locks_guard`` closes that window.
    """
    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.core import client_locks
    from server.app.core.settings import settings as core_settings

    client_locks._client_promotion_locks.clear()
    monkeypatch.setattr(core_settings, "max_clients", 1)

    # Holder enters first and stays inside the context until we release
    # the gate. While it's inside, fire a waiter that will queue on the
    # same key — both bump `users` while their work is pending.
    holder_inside = asyncio.Event()
    waiter_queued = asyncio.Event()
    let_holder_finish = asyncio.Event()

    async def holder():
        async with embed_mod._client_lock("client_a"):
            holder_inside.set()
            await let_holder_finish.wait()

    async def waiter():
        # The single registry entry is in use by `holder`. Waiter must
        # increment `users` under the guard, then await `entry.lock`.
        waiter_queued.set()
        async with embed_mod._client_lock("client_a"):
            pass

    holder_task = asyncio.create_task(holder())
    await holder_inside.wait()
    waiter_task = asyncio.create_task(waiter())
    await waiter_queued.wait()
    # Yield so waiter actually progresses to its `_client_lock` call
    # and increments users before we observe.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    entry = client_locks._client_promotion_locks["client_a"]
    assert entry.users >= 2, f"holder + waiter must both count toward users; got {entry.users}"

    # Trigger the eviction path: cap is 1, "client_a" is in use.
    # Request a new client — eviction must not cull "client_a"; it
    # should instead allow temporary growth past the cap.
    async with embed_mod._client_lock("client_b"):
        registry_keys = set(client_locks._client_promotion_locks)
        assert "client_a" in registry_keys, f"in-use entry was evicted despite queued waiter; got {registry_keys}"

    let_holder_finish.set()
    await asyncio.gather(holder_task, waiter_task)


@pytest.mark.anyio
async def test_client_lock_normalizes_key():
    """Two raw client strings that resolve to the same temp dir share one lock.

    `get_temp_directory(client, ...)` normalizes *client* via
    `safe_filename` (= `Path(client).name`), so `Client: team/a` and
    `Client: a` both write to `<base>/a/embedding`. If `_client_lock`
    keys by the raw header value, those two requests would take
    *different* locks while operating on the *same* on-disk files —
    defeating the serialisation guarantee. The lock key uses the same
    canonicalisation the filesystem does.
    """
    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.core import client_locks

    client_locks._client_promotion_locks.clear()

    async with embed_mod._client_lock("a"):
        entry_a = client_locks._client_promotion_locks["a"]
    async with embed_mod._client_lock("team/a"):
        entry_team_a = client_locks._client_promotion_locks["a"]
    async with embed_mod._client_lock("foo/bar/a"):
        entry_subdir_a = client_locks._client_promotion_locks["a"]
    assert entry_a is entry_team_a
    assert entry_a is entry_subdir_a


@pytest.mark.anyio
async def test_local_store_acquires_per_client_lock(app_client, auth_headers):
    """`store_local_file` must take the per-client promotion lock.

    Without serialization, the staging→temp_directory backup/rename
    sequence in `_promote_atomically` would race with another concurrent
    caller that touches the same basename, losing the newer upload or
    raising FileNotFoundError after a TOCTOU exists() check.
    """
    import tempfile
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_mod

    locks_acquired: list[str] = []
    real_client_lock = embed_mod._client_lock

    @asynccontextmanager
    async def recording_client_lock(client):
        locks_acquired.append(client)
        async with real_client_lock(client):
            yield

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                return_value=tmp_path,
            ),
            patch.object(embed_mod, "_client_lock", recording_client_lock),
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[("files", ("a.txt", io.BytesIO(b"alpha"), "text/plain"))],
                headers={**auth_headers, "Client": "lock-client-a"},
            )
    assert resp.status_code == 200
    assert "lock-client-a" in locks_acquired


@pytest.mark.anyio
async def test_split_embed_acquires_per_client_lock(app_client, auth_headers):
    """`split_embed` must take the same per-client promotion lock as store_local_file.

    `_prepare_work_dir` empties the shared temp_directory; without
    serialization on the same lock, it can race with a concurrent
    `store_local_file` promotion phase on the same basenames.
    """
    import tempfile
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_mod

    locks_acquired: list[str] = []
    real_client_lock = embed_mod._client_lock
    submit_mock = AsyncMock(side_effect=HTTPException(status_code=404, detail="Stop after claiming files"))

    @asynccontextmanager
    async def recording_client_lock(client):
        locks_acquired.append(client)
        async with real_client_lock(client):
            yield

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Pre-populate so _prepare_work_dir has something to move.
        (tmp_path / "doc.txt").write_bytes(b"x")

        def _fake_get_temp(_client, _function, *, unique=False):
            return tmp_path / "work_unique" if unique else tmp_path

        # Stop after the synchronous claim phase. This test only verifies
        # lock acquisition and must not submit a real background embed job.
        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch("server.app.api.v1.endpoints.embed.get_oci_profile", return_value=MagicMock()),
            patch.object(embed_mod, "_client_lock", recording_client_lock),
            patch.object(embed_mod, "_submit_split_embed_under_lock", submit_mock),
        ):
            (tmp_path / "work_unique").mkdir()
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers={**auth_headers, "Client": "lock-client-b"},
            )
    del resp  # status irrelevant — this test only pins the lock acquisition
    assert "lock-client-b" in locks_acquired
    submit_mock.assert_awaited_once()


@pytest.mark.anyio
async def test_local_store_promotes_metadata_last(app_client, auth_headers):
    """`.file_metadata.json` is the final move into temp_directory.

    Promoting metadata last means a concurrent consumer either sees no
    metadata yet (and waits) or sees metadata with every document
    already in place. A sort that placed the dot-prefixed metadata first
    would open a race with a concurrent ``_prepare_work_dir`` call on
    the shared embedding temp directory: it could snapshot the directory
    while only the metadata had landed, decide "no files found", delete
    the work dir, and return 404.
    """
    import tempfile
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_mod

    move_order: list[str] = []
    real_move = embed_mod.shutil.move

    def recording_move(src, dst):
        src_s = str(src)
        dst_s = str(dst)
        # Only record the staging → temp_directory promotion moves —
        # not the backup staging or any inner _extract_zip moves.
        if ".request_" in src_s and ".request_" not in dst_s and ".backup_" not in src_s:
            move_order.append(Path(dst_s).name)
        return real_move(src_s, dst_s)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                return_value=tmp_path,
            ),
            patch.object(embed_mod.shutil, "move", side_effect=recording_move),
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[
                    ("files", ("a.txt", io.BytesIO(b"alpha"), "text/plain")),
                    ("files", ("b.txt", io.BytesIO(b"beta"), "text/plain")),
                ],
                headers=auth_headers,
            )
    assert resp.status_code == 200
    assert move_order, "no promotion moves recorded"
    assert move_order[-1] == ".file_metadata.json", f"metadata must promote last; got order={move_order}"


@pytest.mark.anyio
async def test_local_store_restores_overwritten_file_on_promotion_failure(app_client, auth_headers):
    """Pre-existing files in temp_directory are byte-identical after a rollback.

    If this batch's promotion phase overwrites a file that was already
    in temp_directory and a later shutil.move raises OSError, rolling
    back by moving the new file back into staging is not sufficient —
    the pre-existing content was already replaced by the atomic rename.
    Backups of colliding destinations must be captured before the move
    so the original can be restored.
    """
    import tempfile
    from pathlib import Path

    from server.app.api.v1.endpoints import embed as embed_mod

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "report.txt").write_bytes(b"prior content")
        (tmp_path / ".file_metadata.json").write_bytes(b'{"report.txt": {"size": 14}}')

        forward_moves = 0
        real_move = embed_mod.shutil.move

        def flaky_move(src_path, dst_path):
            """Let backup moves and rollback moves succeed; fail the 2nd promotion move."""
            nonlocal forward_moves
            src_s = str(src_path)
            dst_s = str(dst_path)
            # Forward promotion moves go from .request_* → temp_directory
            # (dst is tmp_path itself, not a sub-directory).
            is_promotion = ".request_" in src_s and ".request_" not in dst_s
            if is_promotion:
                forward_moves += 1
                if forward_moves == 2:
                    raise OSError("synthetic promotion failure")
            return real_move(src_path, dst_path)

        with (
            patch("server.app.api.v1.endpoints.embed.get_temp_directory", return_value=tmp_path),
            patch.object(embed_mod.shutil, "move", side_effect=flaky_move),
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[
                    ("files", ("report.txt", io.BytesIO(b"new content"), "text/plain")),
                    ("files", ("other.txt", io.BytesIO(b"sibling"), "text/plain")),
                ],
                headers=auth_headers,
            )

        assert resp.status_code == 500
        # Pre-existing content restored byte-for-byte.
        assert (tmp_path / "report.txt").read_bytes() == b"prior content"
        # Pre-existing metadata also restored.
        assert (tmp_path / ".file_metadata.json").read_bytes() == b'{"report.txt": {"size": 14}}'
        # This-request's "other.txt" is not in temp_directory.
        assert not (tmp_path / "other.txt").exists()
        # No staging residue.
        assert {p.name for p in tmp_path.iterdir()} == {"report.txt", ".file_metadata.json"}


def test_extract_zip_restores_overwritten_destination_on_promotion_failure(tmp_path):
    """_extract_zip restores a pre-existing dest file if its own promotion phase fails.

    Mirrors the store_local_file guarantee at the ZIP level: the inner
    staging→dest promotion must not leave dest with either the new
    archive's content or nothing — the pre-existing bytes must be
    restored on any mid-promotion OSError.
    """
    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.embed.staging import _extract_zip

    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "a.txt").write_bytes(b"prior a content")

    src = _make_zip(tmp_path / "archive.zip", [("a.txt", b"zip a"), ("b.txt", b"zip b")])

    forward_moves = 0
    real_move = embed_mod.shutil.move

    def flaky_move(src_path, dst_path):
        nonlocal forward_moves
        src_s = str(src_path)
        dst_s = str(dst_path)
        # Count only .zipextract_* → dest moves; let backup + rollback moves succeed.
        is_promotion = ".zipextract_" in src_s and ".zipextract_" not in dst_s
        if is_promotion:
            forward_moves += 1
            if forward_moves == 2:
                raise OSError("synthetic promotion failure")
        return real_move(src_path, dst_path)

    with (
        patch.object(embed_mod.shutil, "move", side_effect=flaky_move),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)

    assert exc.value.status_code == 500
    # Pre-existing a.txt restored.
    assert (dest / "a.txt").read_bytes() == b"prior a content"
    # b.txt (never pre-existed) is not present.
    assert not (dest / "b.txt").exists()


def test_extract_zip_returns_500_on_promotion_failure(tmp_path):
    """shutil.move failures during promotion surface as HTTPException(500).

    A generic-exception path in store_local_file would swallow OSError
    from mid-promotion moves and return 200 even though the archive was
    only partially applied. Raising HTTPException forces the caller to
    propagate the failure.
    """
    import zipfile as _zf

    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.embed.staging import _extract_zip

    del _zf  # linting — imported for the side-effect of ensuring the module is loaded
    src = _make_zip(tmp_path / "archive.zip", [("a.txt", b"hi"), ("b.txt", b"bye")])
    dest = tmp_path / "dest"
    dest.mkdir()

    forward_moves = 0
    real_move = embed_mod.shutil.move

    def flaky_move(src_path, dst_path):
        nonlocal forward_moves
        # Count only staging → dest moves; let rollback moves succeed.
        if ".zipextract_" in str(src_path) and ".zipextract_" not in str(dst_path):
            forward_moves += 1
            if forward_moves == 2:
                raise OSError("synthetic promotion failure")
        return real_move(src_path, dst_path)

    with (
        patch.object(embed_mod.shutil, "move", side_effect=flaky_move),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)

    assert exc.value.status_code == 500
    # Best-effort rollback: a.txt was promoted then moved back; with the
    # staging dir rmtree'd in finally, dest should be empty.
    assert [p for p in dest.iterdir() if p.is_file()] == []


@pytest.mark.anyio
async def test_local_store_rejects_corrupt_zip(app_client, auth_headers):
    """POST /v1/embed/local/store surfaces corrupt ZIP uploads as 400.

    A generic except-block that logged BadZipFile and returned 200 would
    leave any partially-extracted members in temp_directory for a
    subsequent embed pass to ingest. The endpoint must surface the
    failure as 400 with no on-disk residue.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch(
            "server.app.api.v1.endpoints.embed.get_temp_directory",
            return_value=tmp_path,
        ):
            resp = await app_client.post(
                "/v1/embed/local/store",
                files=[("files", ("fake.zip", io.BytesIO(b"this is not a zip"), "application/zip"))],
                headers=auth_headers,
            )
        assert resp.status_code == 400
        # No residue: the corrupt .zip is unlinked and nothing was extracted.
        assert list(tmp_path.iterdir()) == []


def test_extract_zip_overwrites_preexisting_file_on_success(tmp_path):
    """Happy path still replaces pre-existing basenames.

    Staging-and-promote must not regress the prior overwrite-on-success
    behaviour: a successful extraction of `report.txt` replaces the
    pre-existing `report.txt` in *dest* rather than creating a duplicate
    or leaving the old content.
    """
    from server.app.embed.staging import _extract_zip

    dest = tmp_path / "shared"
    dest.mkdir()
    (dest / "report.txt").write_bytes(b"old content")

    src = _make_zip(tmp_path / "archive.zip", [("report.txt", b"new content")])
    _extract_zip(src, dest)

    assert (dest / "report.txt").read_bytes() == b"new content"
    # No staging residue left behind.
    staging_dirs = [p for p in dest.iterdir() if p.is_dir()]
    assert staging_dirs == []


class _PartialThenBadZipFile:
    """Returns *prefix* on first read; raises BadZipFile on second.

    Mimics a real ``ZipExtFile`` whose decompressor yielded some bytes
    before detecting CRC corruption. With the streaming extraction
    loop, those partial bytes have already been written to the staging
    target file when the next read raises — exactly the pre-failure
    partial-write scenario the rollback machinery has to clean up.
    """

    def __init__(self, prefix=b"partial-"):
        self._prefix = prefix
        self._sent = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _n=-1):
        if not self._sent:
            self._sent = True
            return self._prefix
        import zipfile as _zf

        raise _zf.BadZipFile("synthetic CRC failure")

    def close(self):
        return None


def test_extract_zip_preserves_preexisting_file_on_failure(tmp_path):
    """Pre-existing files in *dest* survive a failed extraction intact.

    The shared embedding temp directory accumulates files across
    multipart uploads and prior /local/store calls. If a corrupt ZIP
    member happens to share a basename with one of those pre-existing
    files, the rollback must not touch it — neither the bytes nor the
    mtime should change.
    """
    import zipfile as _zf

    from server.app.embed.staging import _extract_zip

    dest = tmp_path / "shared"
    dest.mkdir()
    preexisting = dest / "report.txt"
    preexisting.write_bytes(b"original user content")
    original_mtime = preexisting.stat().st_mtime

    src = _make_zip(
        tmp_path / "archive.zip",
        [("report.txt", b"from-archive"), ("bomb.bin", b"x")],
    )

    real_open = _zf.ZipFile.open
    call_count = 0

    def flaky_open(self, info, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return _PartialThenBadZipFile()
        return real_open(self, info, *args, **kwargs)

    with (
        patch.object(_zf.ZipFile, "open", new=flaky_open),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)

    assert exc.value.status_code == 400
    # Pre-existing content is byte-for-byte intact.
    assert preexisting.read_bytes() == b"original user content"
    assert preexisting.stat().st_mtime == original_mtime
    # The corrupt member is not present.
    assert not (dest / "bomb.bin").exists()


def test_extract_zip_rolls_back_on_mid_member_failure(tmp_path):
    """Streaming extraction must stay atomic across CRC / decompression failures.

    A malformed member can fail its integrity check after the streaming
    read has already written partial bytes to the staging file, while a
    previous member already extracted successfully. Both the partial
    member AND the earlier-extracted file must be removed before the
    exception propagates.
    """
    import zipfile as _zf

    from server.app.embed.staging import _extract_zip

    src = _make_zip(
        tmp_path / "archive.zip",
        [("first.txt", b"hello"), ("second.txt", b"world")],
    )
    dest = tmp_path / "out"
    dest.mkdir()

    real_open = _zf.ZipFile.open
    call_count = 0

    def flaky_open(self, info, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return _PartialThenBadZipFile()
        return real_open(self, info, *args, **kwargs)

    with (
        patch.object(_zf.ZipFile, "open", new=flaky_open),
        pytest.raises(HTTPException) as exc,
    ):
        _extract_zip(src, dest)

    assert exc.value.status_code == 400
    # Both the successfully-extracted first member AND the partial second
    # member must be gone from disk.
    assert not (dest / "first.txt").exists(), "prior member should be rolled back"
    assert not (dest / "second.txt").exists(), "partial member should be cleaned up"


def test_extract_zip_raises_400_for_non_zip_input(tmp_path):
    """Non-ZIP uploads surface as HTTPException(400) rather than BadZipFile.

    A caller's generic `except Exception` would otherwise swallow
    BadZipFile and return success even though extraction never happened
    (and could leave artefacts behind under other failure modes).
    """
    from server.app.embed.staging import _extract_zip

    src = tmp_path / "notazip.zip"
    src.write_bytes(b"this is not a zip file")
    dest = tmp_path / "out"
    dest.mkdir()

    with pytest.raises(HTTPException) as exc:
        _extract_zip(src, dest)
    assert exc.value.status_code == 400


def test_extract_zip_stdlib_bounds_lying_file_size(tmp_path):
    """Stdlib bounds per-member output at ZipInfo.file_size.

    Even when a central-directory entry's declared file_size disagrees
    with the actual decompressed payload (passing our pre-check),
    ZipExtFile._read1 truncates each chunk to `self._left`. In practice
    CRC-32 validation then detects the mismatch and raises BadZipFile
    before the full decompressed stream can be materialised in memory.
    Either outcome bounds the damage; this test pins that guarantee so
    a future refactor that removes the pre-checks on the assumption
    "caller will bound the output" still fails loudly instead of
    silently OOMing.
    """
    import zipfile

    payload = b"\x00" * (1024 * 1024)  # 1 MiB compresses to <1 KB
    src = tmp_path / "liar.zip"
    with zipfile.ZipFile(src, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("blob.bin", payload)

    with zipfile.ZipFile(src, "r") as zf:
        info = zf.infolist()[0]
        assert info.file_size == len(payload)
        info.file_size = 16  # lie: claim 16 bytes, archive holds 1 MiB
        with zf.open(info) as src_member, pytest.raises(zipfile.BadZipFile):
            src_member.read()


# ---------------------------------------------------------------------------
# Fallback response details
# ---------------------------------------------------------------------------


_SOURCE_DETAIL_TOKENS = ("marker-alpha", "marker-beta", "marker-gamma")


@job_store_test
@pytest.mark.anyio
async def test_split_embed_runtime_error_returns_fallback_detail(app_client, auth_headers):
    """RuntimeError paths return the configured fallback detail."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        (shared_dir / "test.txt").write_text("content")

        work_counter = 0

        def _fake_get_temp(_client, _function, *, unique=False):
            nonlocal work_counter
            if unique:
                work_counter += 1
                wd = tmp_path / f"work_{work_counter}"
                wd.mkdir(exist_ok=True)
                return wd
            return shared_dir

        raised = RuntimeError("marker-alpha marker-beta marker-gamma")
        mock_results = {"processed_files": [], "skipped_files": [], "total_chunks": 0}
        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch("server.app.api.v1.endpoints.embed.get_oci_profile", return_value=MagicMock()),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            patch("server.app.api.v1.endpoints.embed.get_client_embed", return_value=MagicMock()),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
                side_effect=raised,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 202
            terminal = await _poll_until_terminal(
                app_client,
                resp.json()["job_id"],
                auth_headers,
            )

    assert terminal["status"] == "failed"
    error = terminal["error"]
    assert error
    # Source detail markers should not appear in the user-visible job error;
    # the same normalization that covered the inline 500 detail still
    # applies on the failed-job path.
    for token in _SOURCE_DETAIL_TOKENS:
        assert token not in error


@pytest.mark.anyio
async def test_refresh_value_error_returns_fallback_detail(app_client, auth_headers):
    """The refresh path returns the configured fallback detail."""
    raised = ValueError("marker-alpha marker-beta marker-gamma")
    with (
        patch("server.app.api.v1.endpoints.embed.get_oci_profile", return_value=MagicMock()),
        patch(
            "server.app.api.v1.endpoints.embed.get_vector_store_by_alias",
            new_callable=AsyncMock,
            side_effect=raised,
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/refresh",
            json={"vector_store_alias": "test", "bucket_name": "my-bucket"},
            headers=auth_headers,
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail
    for token in _SOURCE_DETAIL_TOKENS:
        assert token not in detail


@pytest.mark.anyio
async def test_refresh_bucket_value_error_returns_fallback_detail(app_client, auth_headers):
    """The bucket refresh path returns the configured fallback detail."""
    mock_vs = VectorStoreConfig(
        vector_store="MY_VS",
        embedding_model=ModelIdentity(provider="openai", id=TEST_OPENAI_EMBED_ID),
        chunk_size=1000,
        chunk_overlap=100,
    )
    raised = ValueError("marker-alpha marker-beta marker-gamma")
    with (
        patch("server.app.api.v1.endpoints.embed.get_oci_profile", return_value=MagicMock()),
        patch(
            "server.app.api.v1.endpoints.embed.get_vector_store_by_alias",
            new_callable=AsyncMock,
            return_value=mock_vs,
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_bucket_objects_with_metadata",
            return_value=[{"name": "x.pdf", "etag": "a", "time_modified": "2026-01-01", "size": 1}],
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_processed_objects_metadata",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "server.app.api.v1.endpoints.embed.detect_changed_objects",
            return_value=([{"name": "x.pdf"}], []),
        ),
        patch(
            "server.app.api.v1.endpoints.embed.refresh_vector_store_from_bucket",
            new_callable=AsyncMock,
            side_effect=raised,
        ),
    ):
        resp = await app_client.post(
            "/v1/embed/refresh",
            json={"vector_store_alias": "test", "bucket_name": "my-bucket"},
            headers=auth_headers,
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail
    for token in _SOURCE_DETAIL_TOKENS:
        assert token not in detail


# ---------------------------------------------------------------------------
# GET /jobs and GET /jobs/{job_id}
# ---------------------------------------------------------------------------


@job_store_test
@pytest.mark.anyio
async def test_get_job_unknown_id_returns_404(app_client, auth_headers):
    """Polling an unknown id returns 404, not a fabricated 'queued' record."""
    resp = await app_client.get("/v1/embed/jobs/not-a-real-job", headers=auth_headers)
    assert resp.status_code == 404
    assert "not-a-real-job" in resp.json()["detail"]


@job_store_test
@pytest.mark.anyio
async def test_jobs_scoped_per_client(app_client, auth_headers):
    """A job created under one Client header is invisible to another."""
    import tempfile
    import tempfile as _tf
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "test.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        mock_results = {
            "processed_files": [{"filename": "test.txt", "chunks": 1}],
            "skipped_files": [],
            "total_chunks": 1,
        }

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
        ):
            client_a = {**auth_headers, "Client": "client-a"}
            client_b = {**auth_headers, "Client": "client-b"}
            post_a = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=client_a,
            )
            assert post_a.status_code == 202
            job_id = post_a.json()["job_id"]

            # Client B cannot see client A's job — the client header
            # check is applied on every read so a leaked job id can't
            # be polled across client boundaries.
            cross = await app_client.get(f"/v1/embed/jobs/{job_id}", headers=client_b)
            assert cross.status_code == 404
            list_b = await app_client.get("/v1/embed/jobs", headers=client_b)
            assert list_b.status_code == 200
            assert list_b.json() == []

            # Client A sees the job in both the detail and the list view.
            detail = await app_client.get(f"/v1/embed/jobs/{job_id}", headers=client_a)
            assert detail.status_code == 200
            assert detail.json()["job_id"] == job_id
            list_a = await app_client.get("/v1/embed/jobs", headers=client_a)
            assert list_a.status_code == 200
            assert any(j["job_id"] == job_id for j in list_a.json())

            await _poll_until_terminal(app_client, job_id, client_a)


@job_store_test
@pytest.mark.anyio
async def test_list_jobs_active_only_excludes_terminal_rows(app_client, auth_headers):
    """``GET /v1/embed/jobs?active_only=true`` returns only non-terminal jobs.

    The status panel polls every 2 seconds; without this filter every
    poll pulls every still-tracked terminal row's full ``result``
    payload (``processed_files`` / ``skipped_files``). After a large
    embedding run that's hundreds of kB of JSON repeatedly decoded
    just to be discarded.

    Filtering on the server keeps the polling path lean: a steady
    state of "no jobs running" returns an empty array regardless of
    how many large completed jobs the client has in CORE.
    """
    import datetime as _dt

    from server.app.api.v1.schemas.embed import EmbedJobStatus
    from server.app.embed import jobs as jobs_mod

    client_header = {**auth_headers, "Client": "filter-client"}
    now = _dt.datetime.now(_dt.timezone.utc)

    def _row(job_id: str, status: EmbedJobStatus) -> jobs_mod._JobRow:
        return jobs_mod._JobRow(
            target_db="CORE",
            job_id=job_id,
            client="filter-client",
            owner_pod="pod-1",
            status=status,
            progress=None,
            result=None,
            error=None,
            created=now,
            updated=now,
        )

    # Seed directly through the store so we don't have to drive the
    # full pipeline just to land rows in different statuses.
    await jobs_mod._store_create(_row("active-1", EmbedJobStatus.RUNNING))
    await jobs_mod._store_create(_row("active-2", EmbedJobStatus.QUEUED))
    await jobs_mod._store_create(_row("done-1", EmbedJobStatus.SUCCEEDED))
    await jobs_mod._store_create(_row("done-2", EmbedJobStatus.FAILED))

    # Default: every still-tracked row, terminal blobs included.
    full = await app_client.get("/v1/embed/jobs", headers=client_header)
    assert full.status_code == 200
    assert {j["job_id"] for j in full.json()} == {
        "active-1",
        "active-2",
        "done-1",
        "done-2",
    }

    # active_only=true: only queued/running.
    lean = await app_client.get("/v1/embed/jobs?active_only=true", headers=client_header)
    assert lean.status_code == 200
    assert {j["job_id"] for j in lean.json()} == {"active-1", "active-2"}


@job_store_test
@pytest.mark.anyio
async def test_split_embed_returns_immediately_with_slow_pipeline(app_client, auth_headers):
    """POST returns 202 even when the pipeline body would block for a long time.

    This is the failure mode the refactor exists to fix: the LB times
    out a synchronous request long before the embedding model warms up.
    Substituting a slow ``populate_vs`` and asserting the POST still
    returns sub-second pins that property in regression tests.
    """
    import asyncio
    import tempfile
    import tempfile as _tf
    import time
    from pathlib import Path

    async def _slow_populate(*_args, **_kwargs):
        await asyncio.sleep(5)  # simulate cold model / slow embedder

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "test.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        mock_results = {
            "processed_files": [{"filename": "test.txt", "chunks": 1}],
            "skipped_files": [],
            "total_chunks": 1,
        }

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
                side_effect=_slow_populate,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
        ):
            t0 = time.monotonic()
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            elapsed = time.monotonic() - t0
            assert resp.status_code == 202
            # Sub-second is the contractual requirement; allow a generous
            # ceiling for slow CI runners but well below the 5s slow pipeline.
            assert elapsed < 2.0, f"POST blocked for {elapsed:.2f}s; pipeline must run off-request"

            status = await app_client.get(
                f"/v1/embed/jobs/{resp.json()['job_id']}",
                headers=auth_headers,
            )
            assert status.status_code == 200
            assert status.json()["status"] in ("queued", "running")

            # Cancel the lingering background task so we don't burn 5s
            # of test time waiting for the simulated cold embedder.
            from server.app.embed import jobs as jobs_mod

            mgr = jobs_mod.get_embed_job_manager()
            cancelled = await mgr.cancel_local(resp.json()["job_id"])
            assert cancelled, "background task should still be running locally"


@job_store_test
@pytest.mark.anyio
async def test_split_embed_claims_files_before_returning_202(app_client, auth_headers):
    """Files added after the POST returns must NOT land in this job's corpus.

    The shared client embedding directory is mutated by ``store_local_file``
    and friends. If ``_prepare_work_dir`` runs *after* the response, an
    upload that completes in the gap before the background task acquires
    the per-client lock would silently get embedded into this job — the
    user thinks they're submitting one corpus but the server processes
    a superset. Files must be claimed under the lock before the 202.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path

    captured_filenames: list[list[str]] = []

    def _capture_files(files, *_args, **_kwargs):
        captured_filenames.append(sorted(f.name for f in files))
        return ([], [], {"processed_files": [], "skipped_files": [], "total_chunks": 0})

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "intended.txt").write_text("part of this job")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                side_effect=_capture_files,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
            ),
            patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 202
            # Synchronously simulate a follow-up upload landing in the
            # shared client dir before the background task could possibly
            # have run `_prepare_work_dir`. With proper synchronous
            # claiming this file arrives too late for the current job.
            (shared / "intruder.txt").write_text("uploaded after submit; must NOT be embedded")

            terminal = await _poll_until_terminal(
                app_client,
                resp.json()["job_id"],
                auth_headers,
            )

    assert terminal["status"] == "succeeded", terminal
    assert captured_filenames, "load_and_split_documents was not invoked"
    assert "intruder.txt" not in captured_filenames[0], (
        f"Background job claimed a post-202 upload: {captured_filenames[0]}"
    )
    assert "intended.txt" in captured_filenames[0]


@pytest.mark.anyio
async def test_split_embed_503_restores_uploaded_files_to_shared_dir(app_client, auth_headers):
    """A 503 from CORE-side submission must NOT discard the uploaded corpus.

    P2: the previous fix translates ``oracledb.Error`` from
    ``manager.submit`` into a 503 and the client is expected to
    retry. But ``_prepare_work_dir`` already moved the files out
    of the shared client temp directory, and the failure-cleanup
    rmtree's the work_dir. A retry then hits "no files found".
    Restoration on the 503 path means a retry can succeed without
    re-uploading the corpus.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    import oracledb as _oracledb

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        # Two files to confirm restoration is per-file, not just a marker.
        (shared / "alpha.txt").write_text("first chunk")
        (shared / "beta.txt").write_text("second chunk")
        original_names = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert original_names == ["alpha.txt", "beta.txt"]
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        from server.app.embed import jobs as jobs_mod

        async def _failing_submit(*_args, **_kwargs):
            raise _oracledb.DatabaseError("CORE blip mid-INSERT")

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _failing_submit,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 503
        # Files are back in the shared directory, ready for the client's
        # retry to pick them up.
        restored = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert restored == original_names, f"Expected uploaded files restored to shared dir; got {restored}"
        assert (shared / "alpha.txt").read_text() == "first chunk"
        assert (shared / "beta.txt").read_text() == "second chunk"


@pytest.mark.anyio
async def test_split_embed_503_restores_user_uploaded_uuid_named_csv(app_client, auth_headers):
    """[P3] A user-uploaded CSV with a UUID-shaped basename must NOT be
    dropped by the SQL-detection branch.

    Reviewer concern: the previous fix detected SQL-generated CSVs by
    UUID4 filename pattern alone. A user can legitimately upload a
    CSV whose basename happens to be a UUID (e.g. exported from a
    pipeline that names by run id); under the regex-only check the
    503 restore would silently drop that file, and a retry would
    404 ("no files found") or be missing a document. The source of
    a file cannot be inferred from its name — SQL temp files need
    an explicit marker so user uploads with the same shape are not
    collateral damage.
    """
    import tempfile
    import tempfile as _tf
    import uuid as _uuid
    from pathlib import Path
    from unittest.mock import patch as _patch

    import oracledb as _oracledb

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        # User-uploaded CSV whose basename happens to look like a UUID
        # (e.g. exported from another pipeline that names by run id).
        # Real path: ``store_local_file`` would have placed it here;
        # we drop it directly because the test is about the restore
        # contract, not the upload path.
        user_uuid_csv_name = f"{_uuid.uuid4()}.csv"
        (shared / user_uuid_csv_name).write_text("col1,col2\nx,y\n")
        original_user_files = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert user_uuid_csv_name in original_user_files

        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        from server.app.embed import jobs as jobs_mod

        async def _failing_submit(*_args, **_kwargs):
            raise _oracledb.DatabaseError("CORE blip mid-INSERT")

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _failing_submit,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 503
        restored = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert user_uuid_csv_name in restored, (
            f"User-uploaded CSV {user_uuid_csv_name!r} was dropped by the "
            f"SQL detection — the source of a file cannot be inferred "
            f"from a UUID-shaped basename alone, so SQL temp files need "
            f"an explicit marker"
        )
        assert (shared / user_uuid_csv_name).read_text() == "col1,col2\nx,y\n"


@job_store_test
@pytest.mark.anyio
async def test_tear_down_post_submit_request_does_not_yank_workdir_during_task(tmp_path):
    """[P2] ``_tear_down_post_submit_request`` must not rmtree
    ``work_dir`` while the background task may still be reading or
    writing it.

    Reviewer concern: ``Task.cancel()`` only requests cancellation;
    work already running inside ``asyncio.to_thread`` keeps executing
    in a worker thread until either the synchronous body returns or
    the cancel propagates at the next coroutine ``await``. Removing
    ``work_dir`` before the task has actually finished can yank
    files out from under an in-flight read or partially-written
    vector store, turning a started job into corrupted output.

    Contract: rmtree happens *after* ``submission.task`` is done.
    """
    from server.app.api.v1.endpoints.embed import _tear_down_post_submit_request
    from server.app.embed import jobs as jobs_mod

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "in-use.bin").write_bytes(b"data")

    blocker: asyncio.Future = asyncio.Future()

    async def _hangs(_handle: jobs_mod.JobHandle):
        try:
            await blocker
        finally:
            # Pipeline-body finally would normally rmtree work_dir
            # here, but we deliberately do NOT — to test that the
            # request handler's deferred rmtree is what does it
            # (covering the production scenario where the body's
            # finally hasn't run yet).
            pass
        return jobs_mod.EmbedProcessingResult(
            message="ok",
            total_chunks=0,
            processed_files=[],
            skipped_files=[],
        )

    pod = jobs_mod.EmbedJobManager(pod_id="pod-1")
    sub = await pod.submit(client="x", coro_factory=_hangs, target_db="CORE")
    # Let the task reach its first await so it's truly "running"
    # (not just registered).
    for _ in range(5):
        await asyncio.sleep(0)

    _tear_down_post_submit_request(sub, work_dir)

    # Immediately after teardown: cancel is in flight but the task
    # hasn't yet processed it. ``work_dir`` MUST still exist —
    # rmtree'ing now would race the running task.
    assert work_dir.exists(), (
        "work_dir was removed immediately after task.cancel() — a "
        "concurrently running task could observe missing files mid-"
        "read or mid-write"
    )

    # Drain the cancellation.
    with contextlib.suppress(BaseException):
        await sub.task

    # Allow the deferred rmtree to fire.
    for _ in range(50):
        await asyncio.sleep(0)

    assert not work_dir.exists(), "deferred rmtree did not fire after task completion — work_dir remained on disk"


@pytest.mark.anyio
async def test_split_embed_post_submit_cancellation_cleans_up_when_task_never_starts(app_client, auth_headers):
    """[P2] If the inner task is cancelled before its first event-loop
    step, ``_run``'s ``try/finally`` never runs — the request
    handler must clean up ``_tasks`` and ``work_dir`` explicitly,
    not rely on the background coroutine.

    Reviewer concern: ``asyncio.Task.cancel()`` on a task that has
    not yet been stepped causes the runtime to send the
    ``CancelledError`` BEFORE any user code in the coroutine body
    runs (verified: a fresh ``coro.throw(...)`` raises at the
    function entry point with no statements executed). That means:

    * ``_run``'s outer ``finally`` never pops ``_tasks`` — the
      heartbeat keeps refreshing the QUEUED row indefinitely and
      the reaper, seeing fresh ``updated`` timestamps, never marks
      it failed.
    * The pipeline body's ``finally`` never rmtree's ``work_dir``,
      so the claimed corpus stays on disk.

    The fix is to mirror what the task's finallys would have done,
    in the request handler's ``except BaseException`` branch.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    from server.app.api.v1.schemas.embed import EmbedJobStatus
    from server.app.embed import jobs as jobs_mod

    captured: dict[str, Any] = {"submission": None}

    async def _fake_submit(self, *_args, target_db: str = "", **_kwargs):
        # Simulate ``manager.submit`` returning successfully with a
        # task that has been cancelled before any event-loop step —
        # in production this is what happens when ``Task.cancel()``
        # arrives before the loop has run the new task's coroutine
        # at all (``CancelledError`` fires at function entry,
        # neither ``_run``'s outer finally nor the pipeline body's
        # finally execute). The contract this pins is: the request
        # handler must do the cleanup itself.
        job_id = "test-pre-step-cancel-job"

        async def _never_runs():
            return None

        real_task = asyncio.create_task(_never_runs())
        real_task.cancel()
        # Mirror real submit: register in ``_tasks`` so a missing
        # explicit pop here is visible at the end of the test.
        self._tasks[job_id] = real_task
        sub = jobs_mod.JobSubmission(
            job_id=job_id,
            status=EmbedJobStatus.QUEUED,
            task=real_task,
        )
        captured["submission"] = sub
        return sub

    class _CancellingExitLock:
        async def __aenter__(self):
            from server.app.core.settings import _settings_lock as real

            await real.__aenter__()
            return self

        async def __aexit__(self, exc_type, exc, tb):
            from server.app.core.settings import _settings_lock as real

            await real.__aexit__(exc_type, exc, tb)
            if exc is None:
                raise asyncio.CancelledError("simulated post-submit cancellation")

    work_dirs_created: list[Path] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            if unique:
                wd = Path(_tf.mkdtemp(dir=work_parent))
                work_dirs_created.append(wd)
                return wd
            return shared

        manager = jobs_mod.get_embed_job_manager()
        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed._settings_lock",
                _CancellingExitLock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _fake_submit,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=(
                    [],
                    [],
                    {
                        "processed_files": [{"filename": "doc.txt", "chunks": 1}],
                        "skipped_files": [],
                        "total_chunks": 1,
                    },
                ),
            ),
            contextlib.suppress(BaseException),
        ):
            await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        sub = captured["submission"]
        assert sub is not None, "fake submit was not invoked"
        # ``_tasks`` was popped eagerly so the heartbeat stops
        # refreshing immediately (the queued row would otherwise
        # be refreshed forever and the reaper would never sweep it).
        assert sub.job_id not in manager._tasks, (
            f"_tasks still contains {sub.job_id!r}; the request "
            f"handler did not pop it eagerly, so the heartbeat "
            f"would refresh the queued row indefinitely"
        )
        # Drain the cancellation, then yield enough turns for the
        # deferred rmtree to fire after the task is done.
        with contextlib.suppress(BaseException):
            await sub.task
        for _ in range(50):
            await asyncio.sleep(0)
        assert sub.task.done(), "task did not reach a terminal state"
        assert work_dirs_created, "no work_dir was created"
        for wd in work_dirs_created:
            assert not wd.exists(), (
                f"work_dir {wd} survived the post-submit cancellation; the deferred rmtree did not fire"
            )


@job_store_test
@pytest.mark.anyio
async def test_split_embed_post_submit_cancellation_cancels_task(app_client, auth_headers):
    """[P2] If the request is cancelled after manager.submit returns,
    the BaseException handler must cancel the background task — not
    rmtree work_dir under it.

    Reviewer concern: once submission succeeds the background task is
    registered and reads from work_dir. If a cancellation arrives at
    a subsequent await (e.g. ``_settings_lock.__aexit__`` between
    submit returning and the response being sent) the catch-all
    BaseException handler would otherwise rmtree work_dir while the
    task is still running, and the accepted job starts with missing
    files and fails. Either skip the cleanup once submission
    succeeds, or cancel the task explicitly so its own ``finally``
    handles teardown.

    This test models the cancellation-during-lock-release window by
    wrapping ``_settings_lock`` with an exit hook that raises
    ``CancelledError`` after the body completes — i.e. after
    ``manager.submit`` has already returned a JobSubmission.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    from server.app.api.v1.schemas.embed import EmbedProcessingResult
    from server.app.core.settings import _settings_lock as real_settings_lock
    from server.app.embed import jobs as jobs_mod

    captured: dict[str, Any] = {"submission": None}

    real_submit = jobs_mod.EmbedJobManager.submit

    async def _capturing_submit(self, *args, **kwargs):
        sub = await real_submit(self, *args, **kwargs)
        captured["submission"] = sub
        return sub

    class _CancellingExitLock:
        """Releases the underlying lock cleanly, then raises CancelledError.

        Models cancellation arriving at the lock's ``__aexit__`` await
        — a real-world client-disconnect / shutdown propagation point
        between submit returning and the response being sent.
        """

        async def __aenter__(self):
            await real_settings_lock.__aenter__()
            return self

        async def __aexit__(self, exc_type, exc, tb):
            await real_settings_lock.__aexit__(exc_type, exc, tb)
            if exc is None:
                raise asyncio.CancelledError("simulated post-submit cancellation")

    pipeline_started = asyncio.Event()

    async def _slow_pipeline(*_args, **_kwargs) -> EmbedProcessingResult:
        # If this body runs the bug is present: the request handler
        # rmtree'd work_dir but the task got far enough to start
        # populating. With the fix the task is cancelled before
        # populate_vs is reached.
        pipeline_started.set()
        await asyncio.sleep(2.0)
        return EmbedProcessingResult(
            message="should-not-complete",
            total_chunks=0,
            processed_files=[],
            skipped_files=[],
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed._settings_lock",
                _CancellingExitLock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _capturing_submit,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                side_effect=_slow_pipeline,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=(
                    [],
                    [],
                    {
                        "processed_files": [{"filename": "doc.txt", "chunks": 1}],
                        "skipped_files": [],
                        "total_chunks": 1,
                    },
                ),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            # The request will fail with a 500 because the cancellation
            # propagates out of the handler. We don't care about the
            # response shape here — only that the task got cancelled
            # rather than have its work_dir yanked.
            contextlib.suppress(BaseException),
        ):
            await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        sub = captured["submission"]
        assert sub is not None, (
            "manager.submit did not return — the test cannot exercise "
            "the post-submit cancellation window without a JobSubmission"
        )

        # Drain the cancelled task — wait for it to reach a terminal
        # state. With the fix the task is cancelled cleanly; without
        # it the task keeps running against a yanked work_dir.
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(sub.task, timeout=2.0)

        assert sub.task.done(), "task did not reach terminal state"
        # The pipeline body must NOT have run to completion: the task
        # was cancelled before populate_vs got past its sleep.
        # ``pipeline_started`` may be set if cancellation arrived
        # mid-sleep, but the sleep never completes — populate_vs
        # would only return after 2s of sleep.
        # Strict assertion: the task is cancelled (clean teardown
        # via ``Task.cancel()``) rather than crashed against a
        # missing work_dir.
        assert sub.task.cancelled(), (
            "task did not end in a cancelled state; the request "
            "handler must cancel the task (clean teardown) instead "
            "of rmtree'ing work_dir under it"
        )


@pytest.mark.anyio
async def test_split_embed_pre_claim_503_drops_sql_scratch_files(app_client, auth_headers):
    """[P2] A pre-claim 503 must sweep ``_sqlsrc_*.csv`` from shared.

    Reviewer concern: ``/embed/sql/store`` writes a unique
    ``_sqlsrc_<uuid>.csv`` to the shared embedding directory before
    the user submits. If a precondition guard inside ``POST /embed/``
    (e.g. ``_require_core_pool`` during a CORE outage) raises 503
    BEFORE ``_prepare_work_dir`` claims those files, the existing
    claim/restore path doesn't run — the SQL scratch CSV stays in
    shared. The Streamlit retry path always re-runs
    ``/embed/sql/store`` before retrying, generating a *new*
    ``_sqlsrc_<uuid>.csv`` (fresh UUID every call). The next
    successful embed then claims both, embedding the query results
    twice.

    The pre-claim error paths must drop the prior SQL scratch
    files for the same reason the restore path does — these
    are ephemeral, regenerated on every retry, and the marker
    prefix exists precisely so the embed handler can identify
    them safely.
    """
    import tempfile
    import tempfile as _tf
    import uuid as _uuid
    from pathlib import Path
    from unittest.mock import patch as _patch

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        # Pre-existing SQL scratch CSV (modelling what
        # /embed/sql/store left behind on the user's last attempt).
        sql_csv_name = f"_sqlsrc_{_uuid.uuid4()}.csv"
        (shared / sql_csv_name).write_text("col1\nvalue\n")
        # And a user-uploaded file that must NOT be swept — only the
        # marker-prefixed SQL scratch files are ephemeral.
        (shared / "user-doc.pdf").write_bytes(b"%PDF-1.4 stub")
        original = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert sql_csv_name in original
        assert "user-doc.pdf" in original

        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            # Force the early CORE-availability guard to 503.
            _patch(
                "server.app.api.v1.endpoints.embed.get_core_pool",
                return_value=None,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 503
        remaining = sorted(p.name for p in shared.iterdir() if p.is_file())
        # The SQL scratch file is gone — the retry's /embed/sql/store
        # will regenerate it under a fresh UUID, no accumulation.
        assert sql_csv_name not in remaining, (
            f"SQL scratch CSV {sql_csv_name!r} survived the pre-claim "
            f"503; the retry would land a new _sqlsrc_*.csv alongside, "
            f"and the next embed would claim both"
        )
        # The user's actual upload is preserved — only marker-prefixed
        # SQL scratch files are dropped.
        assert "user-doc.pdf" in remaining, (
            "user upload was swept by the SQL scratch sweeper; only _sqlsrc_*.csv files are ephemeral"
        )


@pytest.mark.anyio
async def test_split_embed_503_does_not_restore_sql_generated_csv(app_client, auth_headers):
    """[P2] Retryable 503 must NOT restore SQL-generated UUID CSVs.

    Reviewer concern: ``/embed/sql/store`` writes the query result as
    ``<uuid>.csv`` in the shared embedding directory. When the
    Streamlit retry path (``_process_populate_request``) hits a 503
    on POST ``/embed/`` it always re-runs ``/embed/sql/store`` first
    before retrying — and ``run_sql_query`` allocates a *fresh* UUID
    each call. If the failure path moved the previous UUID CSV back
    to shared, the next embed would claim *both* the restored CSV
    and the new one, embedding the query results twice.

    The fix: SQL-generated CSVs are ephemeral and identified by a
    UUID4 filename pattern; the restore helper must drop them
    instead of moving them back. User-uploaded files (which use
    deterministic, source-derived names) are still restored so a
    retry doesn't have to re-upload.
    """
    import tempfile
    import tempfile as _tf
    import uuid as _uuid
    from pathlib import Path
    from unittest.mock import patch as _patch

    import oracledb as _oracledb

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        # One user-uploaded file (deterministic name) — must be
        # restored on 503 so the client's retry doesn't re-upload.
        (shared / "user.txt").write_text("user content")
        # One SQL-generated CSV — modelling what ``run_sql_query``
        # writes (``_sqlsrc_<uuid>.csv``). Must NOT be restored: the
        # client's retry path will re-run ``/embed/sql/store`` and
        # generate a new SQL CSV; restoring this one would let the
        # next embed claim both.
        sql_csv_name = f"_sqlsrc_{_uuid.uuid4()}.csv"
        (shared / sql_csv_name).write_text("col1\nvalue\n")
        original_user_files = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert "user.txt" in original_user_files
        assert sql_csv_name in original_user_files

        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        from server.app.embed import jobs as jobs_mod

        async def _failing_submit(*_args, **_kwargs):
            raise _oracledb.DatabaseError("CORE blip mid-INSERT")

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _failing_submit,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 503
        restored = sorted(p.name for p in shared.iterdir() if p.is_file())
        # The user upload is back so the retry doesn't have to re-upload.
        assert "user.txt" in restored
        assert (shared / "user.txt").read_text() == "user content"
        # The SQL-generated CSV is NOT back — the retry's /embed/sql/store
        # will generate a fresh one and we don't want both claimed.
        assert sql_csv_name not in restored, (
            f"SQL-generated CSV {sql_csv_name!r} was restored to "
            f"shared; the retry's /embed/sql/store will produce a new "
            f"UUID, and embedding both would duplicate the query results"
        )


@pytest.mark.anyio
async def test_split_embed_restores_files_when_locked_db_snapshot_raises_503(app_client, auth_headers):
    """[P2] A 503 from the under-lock DB re-snapshot must NOT discard the corpus.

    Reviewer concern: the rotation-race fix re-resolves the DB config
    inside ``_settings_lock`` before ``manager.submit``. If the
    client's database is removed or becomes unusable between the
    early availability probe and the locked snapshot,
    ``_get_client_db_config`` raises ``HTTPException(503)`` *after*
    ``_prepare_work_dir`` has moved the corpus out of the shared
    directory. Falling through to ``except BaseException`` rmtree's
    the work_dir, so the user has to re-upload everything before
    they can retry.

    The 503 from the locked snapshot is the same retry contract as
    the CORE submission failures — restore the corpus to shared so
    the client's retry succeeds without a re-upload.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "alpha.txt").write_text("first chunk")
        (shared / "beta.txt").write_text("second chunk")
        original_names = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert original_names == ["alpha.txt", "beta.txt"]
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        # First call is the early probe (succeeds). Second call is
        # the under-lock re-snapshot — this is where the DB has gone
        # away mid-request and the helper raises 503. The endpoint
        # must catch that and restore the files.
        cfg = MagicMock()
        cfg.alias = "TEST"
        cfg.pool = MagicMock()
        cfg.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        cfg.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        cfg.usable = True
        cfg.vector_stores = []
        cfg.model_copy.return_value = cfg

        call_count = {"n": 0}

        def _evolving_db_config(_client):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return cfg, cfg.pool
            raise HTTPException(status_code=503, detail="Database is not available: TEST")

        with (
            _patch(
                "server.app.api.v1.endpoints.embed._get_client_db_config",
                side_effect=_evolving_db_config,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 503
        # Files must be back in the shared directory so the client's
        # retry (after the admin restores the DB) can pick them up.
        restored = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert restored == original_names, f"Expected uploaded files restored to shared dir; got {restored}"
        assert (shared / "alpha.txt").read_text() == "first chunk"
        assert (shared / "beta.txt").read_text() == "second chunk"


@pytest.mark.anyio
async def test_split_embed_holds_client_lock_through_submission(app_client, auth_headers):
    """[P2] ``manager.submit`` must run inside the per-client lock.

    Reviewer concern: if the lock is released after ``_prepare_work_dir``
    and re-acquired only inside ``_restore_claimed_files_to_shared``, a
    same-client upload landing in shared during the unlocked window
    leaves shared non-empty when restoration runs. The current restore
    only skips *same-name* conflicts, so files with different names
    get merged into the new corpus and the next embed request claims a
    mix of stale and newly-uploaded files. Holding the lock from claim
    through submit eliminates the race window: a concurrent
    ``store_local_file`` for the same client cannot land in shared
    until restoration (or the success path) has fully completed.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    import oracledb as _oracledb

    from server.app.api.v1.endpoints import embed as embed_endpoints
    from server.app.embed import jobs as jobs_mod

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "old.txt").write_text("first batch")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        # Side coroutine racing for the same client lock — if the
        # endpoint releases it during ``submit`` this acquires
        # immediately; if the endpoint holds it through ``submit``
        # this blocks until the handler returns.
        side_started = asyncio.Event()
        side_acquired = asyncio.Event()
        side_can_release = asyncio.Event()

        async def _side_acquirer():
            side_started.set()
            async with embed_endpoints._client_lock("server"):
                side_acquired.set()
                await side_can_release.wait()

        async def _failing_submit(*_args, **_kwargs):
            asyncio.create_task(_side_acquirer())
            await side_started.wait()
            # Yield repeatedly so the side task has every chance to
            # acquire if the lock has been released. ``asyncio.Lock``
            # is FIFO, so a freed lock would be granted on the next
            # loop iteration; ten iterations is comfortably enough.
            for _ in range(10):
                await asyncio.sleep(0)
            assert not side_acquired.is_set(), (
                "client lock was released during submit — concurrent "
                "same-client upload could land in shared and the "
                "restore path would merge it with the failed corpus"
            )
            raise _oracledb.DatabaseError("CORE blip mid-INSERT")

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _failing_submit,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            # Once the handler returned, the lock is released and the
            # side acquirer should be able to acquire.
            try:
                await asyncio.wait_for(side_acquired.wait(), timeout=2.0)
            finally:
                side_can_release.set()

        assert resp.status_code == 503
        contents = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert contents == ["old.txt"], f"expected restored corpus to be ['old.txt']; got {contents}"


@pytest.mark.anyio
async def test_split_embed_translates_core_submit_failure_to_503(app_client, auth_headers):
    """A CORE blip on the INSERT during ``manager.submit`` must yield 503.

    Symmetric to ``GET /v1/embed/jobs[/{id}]``: those endpoints already
    wrap ``oracledb.Error`` from CORE reads as 503. The POST handler
    must do the same so polling clients (which only retry 503) don't
    abandon the request on a transient submission error. Cleanup of
    the claimed work_dir must still run before the translated 503 is
    returned, otherwise the corpus is stranded on disk.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    import oracledb as _oracledb

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        created_work_dirs: list[Path] = []

        def _fake_get_temp(_client, _function, *, unique=False):
            if unique:
                wd = Path(_tf.mkdtemp(dir=work_parent))
                created_work_dirs.append(wd)
                return wd
            return shared

        from server.app.embed import jobs as jobs_mod

        async def _failing_submit(*_args, **_kwargs):
            raise _oracledb.DatabaseError("ORA-12541: CORE listener refused mid-INSERT")

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _failing_submit,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()
    # Cleanup still happens before the 503 is raised.
    assert created_work_dirs, "expected a work_dir to be created"
    for wd in created_work_dirs:
        assert not wd.exists(), f"submission failure left {wd} behind"


@pytest.mark.anyio
async def test_split_embed_cleans_work_dir_when_submit_fails(app_client, auth_headers):
    """A submission failure must remove the populated work_dir.

    P2: ``_prepare_work_dir`` moves the uploaded corpus out of the
    shared client directory before ``manager.submit`` is called. If
    submission then raises (e.g. CORE write failure), no background
    task is started and the task's ``finally`` cleanup never runs.
    Without the request-side cleanup the corpus is stranded on disk.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        created_work_dirs: list[Path] = []

        def _fake_get_temp(_client, _function, *, unique=False):
            if unique:
                wd = Path(_tf.mkdtemp(dir=work_parent))
                created_work_dirs.append(wd)
                return wd
            return shared

        from server.app.embed import jobs as jobs_mod

        async def _failing_submit(*_args, **_kwargs):
            raise RuntimeError("synthetic CORE write failure")

        # The TestClient propagates unhandled server exceptions out of
        # the call by default, so we observe the failure via
        # ``pytest.raises`` rather than via a 500 response.
        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _failing_submit,
            ),
            pytest.raises(RuntimeError, match="synthetic CORE write failure"),
        ):
            await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

    # Work dir was created during _prepare_work_dir but must be cleaned
    # up by the request handler when submission fails.
    assert created_work_dirs, "expected a work_dir to be created"
    for wd in created_work_dirs:
        assert not wd.exists(), f"submission failure left {wd} behind"


@job_store_test
@pytest.mark.anyio
async def test_split_embed_pipeline_uses_submission_time_db_config(app_client, auth_headers):
    """[P2] The pipeline must use the db_config captured at POST time.

    Reviewer concern: if a client's database settings are edited after
    POST 202 but before the background task runs, re-resolving
    ``client`` mid-pipeline could redirect the in-flight job to a
    *different* usable database than the one validated at submission.
    The corpus would land in a DB the user never authorised this
    submission against. Capture once during ``split_embed`` and pass
    the snapshot into the task; the pipeline must not re-resolve.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    db_config_calls: list[str] = []
    populate_vs_db_configs: list[Any] = []
    update_vs_pools: list[Any] = []

    def _make_cfg(label: str):
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        cfg = MagicMock()
        cfg.alias = label
        cfg.pool = pool
        cfg.usable = True
        cfg.vector_stores = []
        # The handler now snapshots via ``live_cfg.model_copy()``.
        # For these reference-identity assertions, returning the
        # same mock from ``model_copy()`` is enough — see the
        # separate ``test_split_embed_snapshots_db_config_against_in_place_mutation``
        # test for the model_copy semantics, which uses a real
        # ``DatabaseConfig`` instance instead of a MagicMock.
        cfg.model_copy.return_value = cfg
        return cfg, pool

    cfg_at_submit, pool_at_submit = _make_cfg("submission-time")
    cfg_after_rotation, pool_after_rotation = _make_cfg("post-rotation")

    def _evolving_db_config(client):
        # First two calls happen synchronously inside ``split_embed``:
        # an early DB-availability probe, then a re-snapshot under
        # ``_settings_lock`` (the latter closes the rotation race).
        # Any *third* call would be the pipeline body re-resolving —
        # exactly what this test forbids: the pipeline must use the
        # snapshot it received as a parameter.
        db_config_calls.append(client)
        if len(db_config_calls) <= 2:
            return cfg_at_submit, pool_at_submit
        return cfg_after_rotation, pool_after_rotation

    async def _capture_populate_vs(*, db_config, **_kwargs):
        populate_vs_db_configs.append(db_config)

    async def _capture_update_vs_comment(conn, *_args, **_kwargs):
        # ``conn`` itself isn't easily mapped back to a pool; record
        # the call so we can sanity-check the comment was written via
        # the captured pool's ``acquire()`` (the pipeline opens the
        # connection from ``db_config.pool``).
        update_vs_pools.append(conn)

    mock_results = {
        "processed_files": [{"filename": "doc.txt", "chunks": 1}],
        "skipped_files": [],
        "total_chunks": 1,
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        with (
            _patch(
                "server.app.api.v1.endpoints.embed._get_client_db_config",
                side_effect=_evolving_db_config,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                side_effect=_capture_populate_vs,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                side_effect=_capture_update_vs_comment,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.discover_vector_stores",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 202
            terminal = await _poll_until_terminal(
                app_client,
                resp.json()["job_id"],
                auth_headers,
            )

    assert terminal["status"] == "succeeded", terminal
    assert populate_vs_db_configs, "populate_vs was not invoked by pipeline"
    assert populate_vs_db_configs[0] is cfg_at_submit, (
        f"pipeline used a re-resolved db_config (alias="
        f"{populate_vs_db_configs[0].alias}); expected submission-time snapshot"
    )
    assert len(db_config_calls) <= 2, (
        f"_get_client_db_config called {len(db_config_calls)} times; "
        "pipeline body must use the captured snapshot, not re-resolve "
        "(two synchronous calls during split_embed are allowed: the "
        "early probe and the under-_settings_lock re-snapshot)"
    )


@job_store_test
@pytest.mark.anyio
async def test_split_embed_snapshots_db_config_against_in_place_mutation(app_client, auth_headers):
    """[P2] In-place mutation of the live DatabaseConfig must not retarget an in-flight job.

    Reviewer follow-up: the previous fix captured the *reference*
    returned by ``_get_client_db_config`` — but ``settings.database_configs``
    holds Pydantic models that the database-update endpoint mutates
    in place via ``setattr`` (and the registry rebinds ``.pool`` on
    pool rotation). Closing over the mutable live object means an
    admin editing the same client's DB after POST 202 can re-credential
    or redirect the running pipeline. The fix is to ``model_copy`` so
    the snapshot has its own attribute storage, and to capture the
    pool reference at submission time so a post-submit ``.pool =
    new_pool`` cannot retarget the job either.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    from server.app.database.schemas import DatabaseConfig

    pool_at_submit = MagicMock()
    pool_at_submit.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    pool_at_submit.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    pool_after_rotation = MagicMock()
    pool_after_rotation.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    pool_after_rotation.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    # Build a real DatabaseConfig so model_copy semantics are exercised
    # (a MagicMock's attribute access doesn't reflect Pydantic copy
    # behaviour). The autouse ``mock_client_db`` fixture patches
    # _get_client_db_config to return a MagicMock; we override that
    # with the live Pydantic instance below.
    live_cfg = DatabaseConfig(
        alias="test-db",
        username="user_at_submit",
        password=SecretStr("password_at_submit"),
        dsn="//submit.example.com:1521/SUBMIT",
        usable=True,
    )
    live_cfg.pool = pool_at_submit

    submit_started = asyncio.Event()
    pipeline_can_finish = asyncio.Event()
    captured_credentials: list[dict] = []

    def _reveal(secret):
        # Handle both ``SecretStr`` (snapshot path) and plain ``str``
        # (the buggy path where ``live_cfg.password = "..."`` rebound
        # the attribute to an unwrapped string). The test wants to
        # assert on the *value* either way, not crash on type.
        if secret is None:
            return None
        if hasattr(secret, "get_secret_value"):
            return secret.get_secret_value()
        return secret

    async def _slow_populate_vs(*, db_config, **_kwargs):
        # Signal the test that the pipeline reached populate_vs, then
        # block. The test mutates live_cfg during that wait — so when
        # we then read ``db_config.username`` etc. below, the buggy
        # "captured live reference" code would observe the mutated
        # values, while the correct ``model_copy`` snapshot would
        # still report the submission-time values.
        submit_started.set()
        await pipeline_can_finish.wait()
        captured_credentials.append(
            {
                "username": db_config.username,
                "password_value": _reveal(db_config.password),
                "dsn": db_config.dsn,
                "pool_is_submit": db_config.pool is pool_at_submit,
                "pool_is_rotated": db_config.pool is pool_after_rotation,
            }
        )

    mock_results = {
        "processed_files": [{"filename": "doc.txt", "chunks": 1}],
        "skipped_files": [],
        "total_chunks": 1,
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        def _resolve_real_cfg(_client):
            return live_cfg, live_cfg.pool

        with (
            _patch(
                "server.app.api.v1.endpoints.embed._get_client_db_config",
                side_effect=_resolve_real_cfg,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                side_effect=_slow_populate_vs,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.discover_vector_stores",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 202

            # Wait for the pipeline to reach populate_vs, then mutate
            # the live config in place — the same shape the database-
            # update endpoint produces via ``setattr(cfg, field, val)``.
            # populate_vs has already sampled credentials before this,
            # so the captured snapshot must reflect submission-time
            # values regardless of what we do here.
            await asyncio.wait_for(submit_started.wait(), timeout=5.0)
            live_cfg.username = "user_after_rotation"
            live_cfg.password = SecretStr("password_after_rotation")
            live_cfg.dsn = "//rotated.example.com:1521/ROTATED"
            live_cfg.pool = pool_after_rotation

            pipeline_can_finish.set()
            terminal = await _poll_until_terminal(
                app_client,
                resp.json()["job_id"],
                auth_headers,
            )

    assert terminal["status"] == "succeeded", terminal
    assert captured_credentials, "populate_vs was not invoked"
    seen = captured_credentials[0]
    assert seen["username"] == "user_at_submit", (
        f"pipeline observed post-rotation username {seen['username']!r}; "
        "live mutation leaked into the supposedly captured snapshot"
    )
    assert seen["password_value"] == "password_at_submit", (
        "pipeline observed post-rotation password; credentials must be snapshotted at submission time"
    )
    assert seen["dsn"] == "//submit.example.com:1521/SUBMIT", "pipeline observed post-rotation DSN"
    # Now verify the post-submit mutation went somewhere: the live
    # config must reflect the rotation (proves the mutation actually
    # happened — i.e. the test isn't passing trivially).
    assert live_cfg.username == "user_after_rotation"
    assert live_cfg.pool is pool_after_rotation
    # And the pipeline must have used the submission-time pool, not
    # whatever ``.pool`` got rebound to mid-flight. ``populate_vs``
    # is mocked so this only asserts on the snapshot it received.
    assert seen["pool_is_submit"], (
        "pipeline saw the rotated pool reference; submission-time pool must travel with the snapshot"
    )
    assert not seen["pool_is_rotated"]


@job_store_test
@pytest.mark.anyio
async def test_pipeline_refreshes_live_vector_store_cache_on_success(app_client, auth_headers):
    """[P1] After successful populate, the live ``settings.database_configs``
    cache must reflect the newly created vector store.

    Reviewer concern: the submission-time snapshot fix copied ``db_config`` via
    ``model_copy()``, so ``db_config.vector_stores = list(live_stores)``
    inside the pipeline now writes to the throwaway snapshot.
    ``/v1/settings`` and the Streamlit selectors read
    ``settings.database_configs`` directly — they would otherwise
    show no newly created store until an unrelated rediscovery /
    restart updates the live cache.

    The pipeline must look up the live config by alias and update
    *that* one's ``vector_stores`` list (when it still exists), so
    refresh-after-create stays a no-op for the user.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    from server.app.core.settings import settings as live_settings
    from server.app.database.schemas import DatabaseConfig

    # Build a real DatabaseConfig and register it on the live settings
    # object so the cache update has a real target to write to. The
    # autouse ``mock_client_db`` fixture only patches
    # ``_get_client_db_config``; the live registry is otherwise
    # untouched, so we have to put the alias there explicitly.
    pool_at_submit = MagicMock()
    pool_at_submit.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    pool_at_submit.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    target_alias = "live-cache-target"
    live_cfg = DatabaseConfig(
        alias=target_alias,
        username="user",
        password=SecretStr("pw"),
        dsn="//host:1521/SERVICE",
        usable=True,
    )
    live_cfg.pool = pool_at_submit
    live_cfg.vector_stores = []  # cache empty before this run

    saved_db_configs = list(live_settings.database_configs)
    live_settings.database_configs = [*saved_db_configs, live_cfg]

    # The freshly populated set discovered after the run.
    new_store = VectorStoreConfig(
        vector_store="VS_NEW_TABLE",
        alias="vs-new",
        embedding_model=ModelIdentity(provider="openai", id=TEST_OPENAI_EMBED_ID),
        chunk_size=1000,
        chunk_overlap=100,
        distance_strategy=DistanceStrategy.COSINE,
        index_type="HNSW",
    )

    mock_results = {
        "processed_files": [{"filename": "doc.txt", "chunks": 1}],
        "skipped_files": [],
        "total_chunks": 1,
    }

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shared = tmp_path / "shared"
            shared.mkdir()
            (shared / "doc.txt").write_text("payload")
            work_parent = tmp_path / "work"
            work_parent.mkdir()

            def _fake_get_temp(_client, _function, *, unique=False):
                return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

            def _resolve_real_cfg(_client):
                return live_cfg, live_cfg.pool

            with (
                _patch(
                    "server.app.api.v1.endpoints.embed._get_client_db_config",
                    side_effect=_resolve_real_cfg,
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.get_temp_directory",
                    side_effect=_fake_get_temp,
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.get_oci_profile",
                    return_value=MagicMock(),
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.load_and_split_documents",
                    return_value=([], [], mock_results),
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.get_client_embed",
                    return_value=MagicMock(),
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.populate_vs",
                    new_callable=AsyncMock,
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.update_vs_comment",
                    new_callable=AsyncMock,
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.discover_vector_stores",
                    new_callable=AsyncMock,
                    return_value=[new_store],
                ),
            ):
                resp = await app_client.post(
                    "/v1/embed/",
                    json={
                        "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                        "chunk_size": 1000,
                        "chunk_overlap": 100,
                        "distance_strategy": "COSINE",
                    },
                    headers=auth_headers,
                )
                assert resp.status_code == 202
                terminal = await _poll_until_terminal(
                    app_client,
                    resp.json()["job_id"],
                    auth_headers,
                )

        assert terminal["status"] == "succeeded", terminal
        # The live config — the same object ``/v1/settings`` and the
        # Streamlit selectors read — must now reflect the newly
        # created vector store. Writing to the snapshot only is the
        # bug we're fixing; the assertion below pins the contract.
        live_aliases = [vs.alias for vs in live_cfg.vector_stores]
        assert "vs-new" in live_aliases, (
            f"live cache not refreshed; expected 'vs-new' in live_cfg.vector_stores aliases, got {live_aliases}"
        )
    finally:
        live_settings.database_configs = saved_db_configs


@job_store_test
@pytest.mark.anyio
async def test_pipeline_skips_live_cache_refresh_after_pool_rotation(app_client, auth_headers):
    """[P2] If the live config is rotated mid-job, do not publish stale stores into it.

    Reviewer concern: my previous P1 fix looks up the live config by
    alias and writes the discovered ``vector_stores`` to it. But the
    discovery ran against the captured pool; if an admin updated /
    re-created the same alias mid-pipeline (a fresh ``DatabaseConfig``
    with a different pool / different DB), publishing the captured-
    pool discovery results into that rotated config would put stale
    table names into ``settings.database_configs``. The live cache
    update must verify the live config still represents the same
    pool we discovered against; on mismatch, leave the live cache
    alone so the next discovery against the new pool catches up.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    from server.app.core.settings import settings as live_settings
    from server.app.database.schemas import DatabaseConfig

    captured_pool = MagicMock()
    captured_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    captured_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    rotated_pool = MagicMock()
    rotated_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    rotated_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    target_alias = "rotated-cache-target"
    live_cfg = DatabaseConfig(
        alias=target_alias,
        username="user",
        password=SecretStr("pw"),
        dsn="//host:1521/SERVICE",
        usable=True,
    )
    live_cfg.pool = captured_pool
    live_cfg.vector_stores = []

    saved_db_configs = list(live_settings.database_configs)
    live_settings.database_configs = [*saved_db_configs, live_cfg]

    discovered_store = VectorStoreConfig(
        vector_store="VS_FROM_OLD_POOL",
        alias="vs-from-old-pool",
        embedding_model=ModelIdentity(provider="openai", id=TEST_OPENAI_EMBED_ID),
        chunk_size=1000,
        chunk_overlap=100,
        distance_strategy=DistanceStrategy.COSINE,
        index_type="HNSW",
    )

    discovery_started = asyncio.Event()
    rotation_done = asyncio.Event()

    async def _slow_discover(_conn):
        # Signal the test we've reached discovery; block until the
        # test rotates the live pool. After we return, the pipeline
        # will fall through to the cache update — *that* is the
        # window the fix must guard.
        discovery_started.set()
        await rotation_done.wait()
        return [discovered_store]

    mock_results = {
        "processed_files": [{"filename": "doc.txt", "chunks": 1}],
        "skipped_files": [],
        "total_chunks": 1,
    }

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shared = tmp_path / "shared"
            shared.mkdir()
            (shared / "doc.txt").write_text("payload")
            work_parent = tmp_path / "work"
            work_parent.mkdir()

            def _fake_get_temp(_client, _function, *, unique=False):
                return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

            def _resolve_real_cfg(_client):
                return live_cfg, live_cfg.pool

            with (
                _patch(
                    "server.app.api.v1.endpoints.embed._get_client_db_config",
                    side_effect=_resolve_real_cfg,
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.get_temp_directory",
                    side_effect=_fake_get_temp,
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.get_oci_profile",
                    return_value=MagicMock(),
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.load_and_split_documents",
                    return_value=([], [], mock_results),
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.get_client_embed",
                    return_value=MagicMock(),
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.populate_vs",
                    new_callable=AsyncMock,
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.update_vs_comment",
                    new_callable=AsyncMock,
                ),
                _patch(
                    "server.app.api.v1.endpoints.embed.discover_vector_stores",
                    side_effect=_slow_discover,
                ),
            ):
                resp = await app_client.post(
                    "/v1/embed/",
                    json={
                        "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                        "chunk_size": 1000,
                        "chunk_overlap": 100,
                        "distance_strategy": "COSINE",
                    },
                    headers=auth_headers,
                )
                assert resp.status_code == 202

                # Wait until the pipeline reaches discovery, then rotate
                # the live config's pool — the same shape the registry
                # produces during a pool rebuild on a config update.
                await asyncio.wait_for(discovery_started.wait(), timeout=5.0)
                live_cfg.pool = rotated_pool
                rotation_done.set()

                terminal = await _poll_until_terminal(
                    app_client,
                    resp.json()["job_id"],
                    auth_headers,
                )

        assert terminal["status"] == "succeeded", terminal
        # The live config has been rotated to a different pool; the
        # discovery results came from the *previous* pool's database,
        # so publishing them into the rotated config would corrupt
        # ``settings.database_configs`` with stale table names. The
        # cache update must skip when the pool identity has changed.
        assert live_cfg.vector_stores == [], (
            f"stale discovery results published into rotated config; "
            f"live_cfg.vector_stores={[vs.alias for vs in live_cfg.vector_stores]}"
        )
        # And the rotation must have actually happened (proves the
        # test isn't passing trivially because the pipeline failed
        # to discover anything).
        assert live_cfg.pool is rotated_pool
    finally:
        live_settings.database_configs = saved_db_configs


@job_store_test
@pytest.mark.anyio
async def test_pipeline_cleans_work_dir_when_oci_lookup_fails(app_client, auth_headers):
    """Precondition lookups inside the pipeline body must clean up too.

    P2: the pipeline still re-resolves the OCI profile after accepting
    the submission — the request was already 202'd, so a later OCI
    profile removal turns into a job failure rather than an HTTP
    error. The ``try/finally`` around the body must wrap that
    re-resolution so a failure there still rmtree's work_dir.

    (Database config is captured at submission time and passed into
    the task — see ``test_split_embed_pipeline_uses_submission_time_db_config``
    — so DB lookup no longer happens in the pipeline body. OCI is
    the remaining re-resolution path; this test pins the cleanup
    contract for it.)
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        created_work_dirs: list[Path] = []

        def _fake_get_temp(_client, _function, *, unique=False):
            if unique:
                wd = Path(_tf.mkdtemp(dir=work_parent))
                created_work_dirs.append(wd)
                return wd
            return shared

        # Toggle: the FIRST ``get_oci_profile`` call (precondition in
        # the request handler) must succeed; the SECOND (inside the
        # pipeline body, after 202) raises.
        call_count = {"n": 0}

        def _flaky_oci(_client):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock()
            raise HTTPException(status_code=503, detail="OCI profile rotated mid-pipeline")

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                side_effect=_flaky_oci,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 202
            terminal = await _poll_until_terminal(
                app_client,
                resp.json()["job_id"],
                auth_headers,
            )

    assert terminal["status"] == "failed"
    assert created_work_dirs, "expected a work_dir to be created"
    for wd in created_work_dirs:
        assert not wd.exists(), f"""
            pipeline precondition failure left {wd} behind;
            the body's try/finally must wrap re-resolution lookups too
            """


@pytest.mark.anyio
async def test_get_job_returns_503_when_core_read_fails(app_client, auth_headers):
    """A transient CORE read error must surface as 503, not 500.

    P2: ``manager.get`` ultimately calls ``pool.acquire`` + SELECT.
    When CORE is up but momentarily unreachable (network blip, brief
    pool starvation) the resulting ``oracledb`` error used to
    propagate as a generic 500. The Streamlit poll loop only retries
    503s, so a 500 here aborted the UI even though the background
    task was still running. The status read path must wrap these
    failures as the documented 503.
    """
    import oracledb as _oracledb

    from server.app.embed import jobs as jobs_mod

    async def _failing_get(*_args, **_kwargs):
        raise _oracledb.DatabaseError("ORA-12541: connection refused")

    with patch.object(jobs_mod.EmbedJobManager, "get", _failing_get):
        resp = await app_client.get(
            "/v1/embed/jobs/some-id",
            headers=auth_headers,
        )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_list_jobs_returns_503_when_core_read_fails(app_client, auth_headers):
    """Same 503 conversion applies to the list endpoint."""
    import oracledb as _oracledb

    from server.app.embed import jobs as jobs_mod

    async def _failing_list(*_args, **_kwargs):
        raise _oracledb.DatabaseError("ORA-12541: connection refused")

    with patch.object(jobs_mod.EmbedJobManager, "list_for_client", _failing_list):
        resp = await app_client.get("/v1/embed/jobs", headers=auth_headers)
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_split_embed_submits_under_settings_lock(app_client, auth_headers):
    """[P2] Submission must serialise with CORE rotation via ``_settings_lock``.

    Reviewer concern: ``count_active_embed_jobs`` is a point-in-time
    snapshot. If a POST /v1/embed/ runs concurrently with a CORE
    rotation handler, the snapshot can return 0 *just before* the
    POST inserts and pins a row in the old CORE pool. The rotation
    then closes the old pool and the freshly-pinned row becomes
    unreachable — its terminal writes target a closed pool and
    pollers see CORE errors. Submissions must therefore hold
    ``_settings_lock`` across the manager.submit() call so the
    rotation handler's check + close happens atomically with respect
    to any in-flight INSERT/pin.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    from server.app.core.settings import _settings_lock
    from server.app.embed import jobs as jobs_mod

    # Records whether ``_settings_lock`` was held when manager.submit
    # was invoked. ``asyncio.Lock.locked()`` is True iff held by
    # *some* task in this event loop — since tests run in a single
    # loop, this is exactly the contract we need.
    submit_lock_state: dict[str, Optional[bool]] = {"held": None}

    async def _capturing_submit(self, *, client, coro_factory, target_db=""):
        submit_lock_state["held"] = _settings_lock.locked()

        # Synthesise a minimal submission so the endpoint can build
        # its 202 response. The factory's coroutine is created and
        # cancelled inline — we don't run the real pipeline.
        async def _noop():
            return None

        task = asyncio.create_task(_noop())
        return jobs_mod.JobSubmission(
            job_id="lock-test-job",
            status=jobs_mod.EmbedJobStatus.QUEUED,
            task=task,
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _capturing_submit,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

    assert resp.status_code == 202, resp.json()
    assert submit_lock_state["held"] is True, (
        "manager.submit was called outside _settings_lock — a "
        "concurrent CORE rotation could close the old pool between "
        "the rotation guard's count check and the INSERT/pin, "
        "stranding the accepted job"
    )


@pytest.mark.anyio
async def test_split_embed_translates_core_timeout_to_503(app_client, auth_headers):
    """A CORE pool acquire/INSERT ``TimeoutError`` must yield 503 + restore.

    P2: ``oracledb`` async pools raise the *built-in* ``TimeoutError``
    on ``pool.acquire`` deadlines and SELECT/INSERT timeouts — not
    ``oracledb.DatabaseError``. The submission path must treat that as
    a transient CORE-availability failure (same as ``oracledb.Error``):
    return 503 so polling clients retry, and restore the claimed
    corpus to the shared dir so the retry doesn't hit "no files
    found". Without this branch the next ``except BaseException``
    deletes the corpus and surfaces 500.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "alpha.txt").write_text("payload")
        original_names = sorted(p.name for p in shared.iterdir() if p.is_file())
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        from server.app.embed import jobs as jobs_mod

        async def _timing_out_submit(*_args, **_kwargs):
            # Built-in TimeoutError — what oracledb.AsyncConnectionPool
            # raises when ``pool.acquire`` exceeds the wait_timeout, and
            # what asyncio raises if the surrounding code wraps the
            # call in ``asyncio.wait_for``.
            raise TimeoutError("CORE pool.acquire timed out")

        with (
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch.object(
                jobs_mod.EmbedJobManager,
                "submit",
                _timing_out_submit,
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()
        # Restoration must run on the timeout path the same way it does
        # on the oracledb.Error path — otherwise the retry hits 404.
        restored = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert restored == original_names, f"Expected uploaded files restored to shared dir; got {restored}"


@pytest.mark.anyio
async def test_get_job_returns_503_when_core_read_times_out(app_client, auth_headers):
    """A transient CORE read ``TimeoutError`` must surface as 503.

    P2: same root cause as the submission path — ``pool.acquire`` on
    a saturated pool raises the built-in ``TimeoutError`` rather than
    ``oracledb.Error``. The Streamlit poller only retries on 503, so
    if this 500'd it would abandon a job that may still be running.
    """
    from server.app.embed import jobs as jobs_mod

    async def _timing_out_get(*_args, **_kwargs):
        raise TimeoutError("CORE acquire timed out")

    with patch.object(jobs_mod.EmbedJobManager, "get", _timing_out_get):
        resp = await app_client.get(
            "/v1/embed/jobs/some-id",
            headers=auth_headers,
        )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_list_jobs_returns_503_when_core_read_times_out(app_client, auth_headers):
    """Same 503 conversion for the list endpoint on ``TimeoutError``."""
    from server.app.embed import jobs as jobs_mod

    async def _timing_out_list(*_args, **_kwargs):
        raise TimeoutError("CORE acquire timed out")

    with patch.object(jobs_mod.EmbedJobManager, "list_for_client", _timing_out_list):
        resp = await app_client.get("/v1/embed/jobs", headers=auth_headers)
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_job_returns_503_when_core_unavailable(app_client, auth_headers):
    """GET /v1/embed/jobs/{id} surfaces a 503 when CORE is unavailable.

    P2: without CORE, the manager would fall back to the per-process
    in-memory store, which after a restart or on a sibling replica is
    empty. A None return would be reported as 404 'job not found',
    misleading the polling client into thinking a real job that lives
    in ``aio_embed_jobs`` has vanished. Surface 503 so the client
    retries instead.
    """
    with patch(
        "server.app.api.v1.endpoints.embed.get_core_pool",
        return_value=None,
    ):
        resp = await app_client.get(
            "/v1/embed/jobs/some-job-id",
            headers=auth_headers,
        )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_list_jobs_returns_503_when_core_unavailable(app_client, auth_headers):
    """GET /v1/embed/jobs surfaces a 503 when CORE is unavailable.

    Same rationale as the detail endpoint: returning an empty list
    from local memory would imply 'this client has no jobs', which
    is wrong if jobs already exist in the shared store.
    """
    with patch(
        "server.app.api.v1.endpoints.embed.get_core_pool",
        return_value=None,
    ):
        resp = await app_client.get("/v1/embed/jobs", headers=auth_headers)
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_split_embed_requires_core_database(app_client, auth_headers):
    """POST /v1/embed/ must refuse submissions when CORE is unavailable.

    P2: job state lives in CORE so any replica can serve the status
    endpoint. Without CORE, the in-memory fallback would let the POST
    return 202 with a job tracked only in this pod's process memory —
    polls routed to another replica would 404, and once CORE comes
    back the local row would never reach DB. Refuse the submission
    with a synchronous 503 instead.
    """
    with patch(
        "server.app.api.v1.endpoints.embed.get_core_pool",
        return_value=None,
    ):
        resp = await app_client.post(
            "/v1/embed/",
            json={
                "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "distance_strategy": "COSINE",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@job_store_test
@pytest.mark.anyio
async def test_split_embed_records_target_db_alias_on_job_row(app_client, auth_headers):
    """[P2] The submitted job row must record the target DB alias.

    Reviewer concern: blocking non-CORE rotations while jobs target
    the alias requires the rotation guard to know each job's target
    database. We persist that alias on the job row so the guard can
    filter ``aio_embed_jobs`` by ``target_db`` from any replica.

    Test contract: post a split-embed job with a known captured
    config, then read the persisted row and assert ``target_db``
    matches the captured alias. The autouse ``mock_client_db``
    fixture's mock has ``alias`` (default MagicMock alias); we patch
    in a real alias so the assertion is meaningful.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    from server.app.embed import jobs as jobs_mod

    target_alias = "TARGET-ALIAS"

    cfg = MagicMock()
    cfg.alias = target_alias
    cfg.pool = MagicMock()
    cfg.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    cfg.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    cfg.usable = True
    cfg.vector_stores = []
    cfg.model_copy.return_value = cfg

    mock_results = {
        "processed_files": [{"filename": "doc.txt", "chunks": 1}],
        "skipped_files": [],
        "total_chunks": 1,
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        with (
            _patch(
                "server.app.api.v1.endpoints.embed._get_client_db_config",
                return_value=(cfg, cfg.pool),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                new_callable=AsyncMock,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.discover_vector_stores",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]
            terminal = await _poll_until_terminal(app_client, job_id, auth_headers)

    assert terminal["status"] == "succeeded", terminal
    # The rotation guard contract: ``target_db`` on the persisted row
    # equals the captured client-db alias.
    row = await jobs_mod._store_get(job_id)
    assert row is not None, f"job row {job_id} missing from store"
    assert getattr(row, "target_db", None) == target_alias, (
        f"row.target_db={getattr(row, 'target_db', None)!r}; expected "
        f"{target_alias!r} so the per-alias rotation guard can filter "
        "rows by target database"
    )


@pytest.mark.anyio
async def test_split_embed_db_unavailable_returns_503_synchronously(app_client, auth_headers):
    """Database precondition failures still surface synchronously, not as a job."""
    with patch(
        "server.app.api.v1.endpoints.embed._get_client_db_config",
        side_effect=HTTPException(status_code=503, detail="Database is not available"),
    ):
        resp = await app_client.post(
            "/v1/embed/",
            json={
                "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "distance_strategy": "COSINE",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 503


@job_store_test
@pytest.mark.anyio
async def test_split_embed_resnapshots_db_config_under_settings_lock(app_client, auth_headers):
    """[P2] DB snapshot must be captured under ``_settings_lock`` to close
    the CORE-rotation race.

    Reviewer concern: the early ``_get_client_db_config`` snapshot at
    the top of ``split_embed`` is taken *outside* any lock. If a CORE
    rotation runs between that snapshot and the ``_settings_lock``
    that gates ``manager.submit``, the rotation handler observes zero
    active job rows (no INSERT yet) and closes the captured pool. The
    202 then returns a job pinned to a closed pool.

    The fix re-resolves the DB config under ``_settings_lock`` so the
    snapshot the pipeline runs against is whatever was live at submit
    time — which the rotation handler held the same lock across, so
    the two paths are mutually exclusive.

    Test: serve ``_get_client_db_config`` with two distinct values for
    the first vs second call. The first is the early probe (taken
    pre-lock); the second is the under-lock snapshot. Assert the
    pipeline received the second-call value — that's the under-lock
    one. Without the fix only one call happens and the pipeline sees
    the pre-lock value.
    """
    import tempfile
    import tempfile as _tf
    from pathlib import Path
    from unittest.mock import patch as _patch

    pool_pre_rotation = MagicMock()
    pool_pre_rotation.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    pool_pre_rotation.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    pool_post_rotation = MagicMock()
    pool_post_rotation.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    pool_post_rotation.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    def _make_cfg(label: str, pool):
        cfg = MagicMock()
        cfg.alias = label
        cfg.pool = pool
        cfg.usable = True
        cfg.vector_stores = []
        cfg.model_copy.return_value = cfg
        return cfg

    cfg_pre = _make_cfg("pre-rotation", pool_pre_rotation)
    cfg_post = _make_cfg("post-rotation", pool_post_rotation)

    db_config_calls: list[str] = []
    populate_db_configs: list[Any] = []

    def _evolving(_client):
        db_config_calls.append(_client)
        # Call 1: early probe (pre-lock).
        # Call 2: under-_settings_lock snapshot — modelling a rotation
        # that landed between the probe and the lock acquire.
        if len(db_config_calls) == 1:
            return cfg_pre, pool_pre_rotation
        return cfg_post, pool_post_rotation

    async def _capture_populate_vs(*, db_config, **_kwargs):
        populate_db_configs.append(db_config)

    mock_results = {
        "processed_files": [{"filename": "doc.txt", "chunks": 1}],
        "skipped_files": [],
        "total_chunks": 1,
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "doc.txt").write_text("payload")
        work_parent = tmp_path / "work"
        work_parent.mkdir()

        def _fake_get_temp(_client, _function, *, unique=False):
            return Path(_tf.mkdtemp(dir=work_parent)) if unique else shared

        with (
            _patch(
                "server.app.api.v1.endpoints.embed._get_client_db_config",
                side_effect=_evolving,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_oci_profile",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.load_and_split_documents",
                return_value=([], [], mock_results),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.get_client_embed",
                return_value=MagicMock(),
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.populate_vs",
                side_effect=_capture_populate_vs,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.update_vs_comment",
                new_callable=AsyncMock,
            ),
            _patch(
                "server.app.api.v1.endpoints.embed.discover_vector_stores",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": TEST_OPENAI_EMBED_ID},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 202
            terminal = await _poll_until_terminal(
                app_client,
                resp.json()["job_id"],
                auth_headers,
            )

    assert terminal["status"] == "succeeded", terminal
    assert len(db_config_calls) >= 2, (
        f"_get_client_db_config called only {len(db_config_calls)} time(s); "
        "the handler must re-resolve under _settings_lock so a rotation "
        "between the early probe and submit cannot leak a stale pool"
    )
    assert populate_db_configs, "populate_vs was not invoked"
    assert populate_db_configs[0] is cfg_post, (
        f"pipeline used pre-lock snapshot (alias="
        f"{populate_db_configs[0].alias}); the snapshot must be taken "
        "under _settings_lock so a rotation observed between the probe "
        "and the lock acquire is captured"
    )
