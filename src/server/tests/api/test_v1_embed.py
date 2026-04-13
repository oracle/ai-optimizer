"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for embed API endpoints.
"""
# spell-checker:disable

import io
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from server.app.embed.schemas import VectorStoreConfig
from server.app.models.schemas import ModelIdentity
from server.tests.api.conftest import _create_mock_pool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_client_db():
    """Mock the database config resolution for all embed tests."""
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    mock_cfg = MagicMock()
    mock_cfg.pool = pool
    mock_cfg.usable = True
    mock_cfg.username = "testuser"
    mock_cfg.password = "testpass"
    mock_cfg.dsn = "//localhost:1521/TEST"
    mock_cfg.wallet_location = None
    mock_cfg.config_dir = None
    with patch(
        "server.app.api.v1.endpoints.embed._get_client_db_config",
        return_value=(mock_cfg, pool),
    ):
        yield conn, pool, mock_cfg


# ---------------------------------------------------------------------------
# Auth tests — 403 without API key
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_drop_vs_no_auth(app_client):
    """DELETE /{vs} rejects requests without API key."""
    resp = await app_client.delete("/v1/embed/test_vs")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_files_no_auth(app_client):
    """GET /{vs}/files rejects requests without API key."""
    resp = await app_client.get("/v1/embed/test_vs/files")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_comment_no_auth(app_client):
    """PATCH /comment rejects requests without API key."""
    resp = await app_client.patch("/v1/embed/comment", json={})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_sql_store_no_auth(app_client):
    """POST /sql/store rejects requests without API key."""
    resp = await app_client.post("/v1/embed/sql/store", json={"query": "SELECT 1"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_web_store_no_auth(app_client):
    """POST /web/store rejects requests without API key."""
    resp = await app_client.post("/v1/embed/web/store", json=["https://example.com"])
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_local_store_no_auth(app_client):
    """POST /local/store rejects requests without API key."""
    resp = await app_client.post("/v1/embed/local/store")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_split_embed_no_auth(app_client):
    """POST / rejects requests without API key."""
    resp = await app_client.post("/v1/embed/", json={})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_refresh_no_auth(app_client):
    """POST /refresh rejects requests without API key."""
    resp = await app_client.post("/v1/embed/refresh", json={})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /{vs}
# ---------------------------------------------------------------------------


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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
                "embedding_model": {"provider": "openai", "id": "text-embedding-3-small"},
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


# ---------------------------------------------------------------------------
# POST / (split and embed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_split_embed_no_files(app_client, auth_headers):
    """Returns 404 when no files are found."""
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
                    "embedding_model": {"provider": "openai", "id": "text-embedding-3-small"},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_split_embed_success(app_client, auth_headers):
    """Successfully splits and embeds documents."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        # Create a test file in the shared dir (store endpoints put files here)
        test_file = shared_dir / "test.txt"
        test_file.write_text("Hello world content for embedding")

        mock_results = {
            "processed_files": [{"filename": "test.txt", "chunks": 1}],
            "skipped_files": [],
            "total_chunks": 1,
        }

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
                    "embedding_model": {"provider": "openai", "id": "text-embedding-3-small"},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_chunks"] == 1


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_refresh_no_changes(app_client, auth_headers):
    """Returns success with no-changes message."""
    mock_vs = VectorStoreConfig(
        vector_store="MY_VS",
        embedding_model=ModelIdentity(provider="openai", id="text-embedding-3-small"),
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


@pytest.mark.unit
@pytest.mark.anyio
async def test_refresh_uses_request_auth_profile(app_client, auth_headers):
    """Refresh endpoint uses auth_profile from the request body, not the client default."""
    custom_profile = MagicMock()
    custom_profile.auth_profile = "CUSTOM_PROFILE"
    default_profile = MagicMock()
    default_profile.auth_profile = "DEFAULT"

    mock_vs = VectorStoreConfig(
        vector_store="MY_VS",
        embedding_model=ModelIdentity(provider="openai", id="text-embedding-3-small"),
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
@pytest.mark.anyio
async def test_split_embed_concurrent_no_interference(app_client, auth_headers):
    """Two concurrent split_embed calls must not cause ENOENT from shared cleanup."""
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
                "embedding_model": {"provider": "openai", "id": "text-embedding-3-small"},
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "distance_strategy": "COSINE",
            }
            r1, r2 = await asyncio.gather(
                app_client.post("/v1/embed/", json=req_json, headers=auth_headers),
                app_client.post("/v1/embed/", json=req_json, headers=auth_headers),
            )

    statuses = sorted([r1.status_code, r2.status_code])
    # One succeeds (200), the other finds no files (404). Neither should 500.
    assert 500 not in statuses
    # First call claims the file; second finds shared dir empty
    assert statuses == [200, 404]


@pytest.mark.unit
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
                    "embedding_model": {"provider": "openai", "id": "text-embedding-3-small"},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 404
        # The file that was successfully moved must be restored to shared_dir
        restored_files = sorted(f.name for f in shared_dir.iterdir() if f.is_file())
        assert "a.txt" in restored_files, f"Expected a.txt restored in shared_dir, got: {restored_files}"
        # work_dir should be cleaned up
        assert not work_dir.exists()


@pytest.mark.unit
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


@pytest.mark.unit
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
            patch("httpx.AsyncClient.stream", side_effect=_fake_stream),
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
