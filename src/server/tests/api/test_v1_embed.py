"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for embed API endpoints.
"""
# spell-checker:disable

import asyncio
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


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    "path_like_name,expected_basename",
    [
        ("../../../up/file", "file"),
        ("/abs/launch.py", "launch.py"),
        ("subdir/../sibling.sh", "sibling.sh"),
    ],
)
async def test_local_store_uses_sanitized_upload_basename(
    app_client, auth_headers, path_like_name, expected_basename
):
    """Uploads with path-like filenames must land inside temp_directory only.

    The store path runs upload filenames through `safe_filename()`; this
    test asserts the uploaded bytes appear only under the sanitised
    basename inside the sandboxed temp directory.
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
        # File landed at the sanitised basename, inside temp_directory.
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
                assert candidate.read_bytes() != payload, (
                    f"Path resolved outside temp_directory to {candidate}"
                )


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


@pytest.mark.unit
def test_extract_zip_happy_path(tmp_path):
    """Valid archive: members extracted, metadata populated, bytes intact."""
    from server.app.api.v1.endpoints.embed import _extract_zip

    src = _make_zip(tmp_path / "ok.zip", [("a.txt", b"hello"), ("b.txt", b"world")])
    dest = tmp_path / "out"
    dest.mkdir()

    metadata = _extract_zip(src, dest)

    assert (dest / "a.txt").read_bytes() == b"hello"
    assert (dest / "b.txt").read_bytes() == b"world"
    assert set(metadata) == {"a.txt", "b.txt"}
    assert metadata["a.txt"]["size"] == 5
    assert "time_modified" in metadata["a.txt"]


@pytest.mark.unit
def test_extract_zip_rejects_too_many_members(tmp_path):
    """More than _ZIP_MAX_FILES members → 400 before any write."""
    import zipfile as _zf

    from server.app.api.v1.endpoints.embed import _ZIP_MAX_FILES, _extract_zip

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


@pytest.mark.unit
def test_extract_zip_rejects_oversize_total(tmp_path):
    """Sum of declared file_size > _ZIP_MAX_TOTAL_BYTES → 400."""
    import zipfile as _zf

    from server.app.api.v1.endpoints.embed import _ZIP_MAX_TOTAL_BYTES, _extract_zip

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


@pytest.mark.unit
def test_extract_zip_rejects_oversize_single_file(tmp_path):
    """Declared per-file size > _ZIP_MAX_FILE_BYTES → 400."""
    import zipfile as _zf

    from server.app.api.v1.endpoints.embed import _ZIP_MAX_FILE_BYTES, _extract_zip

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


@pytest.mark.unit
@pytest.mark.parametrize("bad_ext", [".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar"])
def test_extract_zip_skips_nested_archives(tmp_path, bad_ext):
    """Nested-archive members are silently skipped, not extracted."""
    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
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


@pytest.mark.unit
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
    errors and must translate to HTTP 400 rather than leaking as 500.
    """
    import zipfile as _zf

    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
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
    than leaking as a 500.
    """
    import zipfile as _zf

    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
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

    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
def test_extract_zip_target_write_oserror_remains_500(tmp_path):
    """Disk-write OSError is NOT translated to 400 — that's a real server failure.

    The read-side wrapper for decompressor errors must not accidentally
    catch write-side OSError (e.g. disk full, ENOSPC, EROFS). Those are
    legitimate 500s and the caller should see them surface as such.
    """
    from pathlib import Path

    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
def test_extract_zip_translates_infolist_error_to_400(tmp_path):
    """A corrupt central directory (BadZipFile from infolist) surfaces as 400."""
    import zipfile as _zf

    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
def test_extract_zip_handles_member_named_like_backup_prefix(tmp_path):
    """A member called `.backup_<other>` does not collide with backup storage.

    The backup-naming scheme used during promotion must not collide with
    archive members whose name happens to start with `.backup_`. If an
    archive contains both `foo.txt` and `.backup_foo.txt` and dest
    already holds `foo.txt`, both members must land with their archive
    bytes intact.
    """
    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
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


@pytest.mark.unit
def test_extract_zip_rejects_directory_collision_in_dest(tmp_path):
    """A pre-existing directory at dest/<member-name> must not be replaced.

    Backup-and-rename of a directory would silently move a live work
    tree out from under whichever request created it. Surfacing this as
    a 409 matches the open("wb") behaviour (IsADirectoryError) and
    protects concurrent split_embed work_dirs.
    """
    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
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


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_lock_evicts_lru_when_full(monkeypatch):
    """The lock registry caps at settings.max_clients, evicting the LRU first.

    `_client_promotion_locks` is bounded with the same LRU pattern as
    `_client_store` so an unbounded sequence of Client header values
    cannot accumulate process state until restart.
    """
    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.core.settings import settings as core_settings

    embed_mod._client_promotion_locks.clear()
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

    keys = list(embed_mod._client_promotion_locks)
    assert keys == ["c", "a", "d"], f"expected LRU order [c, a, d]; got {keys}"
    assert len(embed_mod._client_promotion_locks) == 3


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_lock_skips_in_use_entry_during_eviction(monkeypatch):
    """In-use entries (holder or queued waiter) are not evicted."""
    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.core.settings import settings as core_settings

    embed_mod._client_promotion_locks.clear()
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

    assert "held" in embed_mod._client_promotion_locks
    assert "spare" not in embed_mod._client_promotion_locks
    assert "new" in embed_mod._client_promotion_locks


@pytest.mark.unit
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
    from server.app.core.settings import settings as core_settings

    embed_mod._client_promotion_locks.clear()
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

    entry = embed_mod._client_promotion_locks["client_a"]
    assert entry.users >= 2, (
        f"holder + waiter must both count toward users; got {entry.users}"
    )

    # Trigger the eviction path: cap is 1, "client_a" is in use.
    # Request a new client — eviction must not cull "client_a"; it
    # should instead allow temporary growth past the cap.
    async with embed_mod._client_lock("client_b"):
        registry_keys = set(embed_mod._client_promotion_locks)
        assert "client_a" in registry_keys, (
            f"in-use entry was evicted despite queued waiter; got {registry_keys}"
        )

    let_holder_finish.set()
    await asyncio.gather(holder_task, waiter_task)


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_lock_normalizes_key():
    """Two raw client strings that resolve to the same temp dir share one lock.

    `get_temp_directory(client, ...)` sanitises *client* via
    `safe_filename` (= `Path(client).name`), so `Client: team/a` and
    `Client: a` both write to `<base>/a/embedding`. If `_client_lock`
    keys by the raw header value, those two requests would take
    *different* locks while operating on the *same* on-disk files —
    defeating the serialisation guarantee. The lock key uses the same
    canonicalisation the filesystem does.
    """
    from server.app.api.v1.endpoints import embed as embed_mod

    embed_mod._client_promotion_locks.clear()

    async with embed_mod._client_lock("a"):
        entry_a = embed_mod._client_promotion_locks["a"]
    async with embed_mod._client_lock("team/a"):
        entry_team_a = embed_mod._client_promotion_locks["a"]
    async with embed_mod._client_lock("foo/bar/a"):
        entry_subdir_a = embed_mod._client_promotion_locks["a"]
    assert entry_a is entry_team_a
    assert entry_a is entry_subdir_a


@pytest.mark.unit
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


@pytest.mark.unit
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

        with (
            patch(
                "server.app.api.v1.endpoints.embed.get_temp_directory",
                side_effect=_fake_get_temp,
            ),
            patch("server.app.api.v1.endpoints.embed.get_oci_profile", return_value=MagicMock()),
            patch.object(embed_mod, "_client_lock", recording_client_lock),
        ):
            (tmp_path / "work_unique").mkdir()
            resp = await app_client.post(
                "/v1/embed/",
                json={
                    "embedding_model": {"provider": "openai", "id": "text-embedding-3-small"},
                    "chunk_size": 1000,
                    "chunk_overlap": 100,
                    "distance_strategy": "COSINE",
                },
                headers={**auth_headers, "Client": "lock-client-b"},
            )
    # We don't care about the response code — we just need to verify the
    # lock was acquired before the work-dir prep ran. Status will be
    # something other than 200 because we haven't mocked the embedding
    # path; what matters is that the lock helper was called.
    del resp
    assert "lock-client-b" in locks_acquired


@pytest.mark.unit
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
        if (
            ".request_" in src_s
            and ".request_" not in dst_s
            and ".backup_" not in src_s
        ):
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
    assert move_order[-1] == ".file_metadata.json", (
        f"metadata must promote last; got order={move_order}"
    )


@pytest.mark.unit
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


@pytest.mark.unit
def test_extract_zip_restores_overwritten_destination_on_promotion_failure(tmp_path):
    """_extract_zip restores a pre-existing dest file if its own promotion phase fails.

    Mirrors the store_local_file guarantee at the ZIP level: the inner
    staging→dest promotion must not leave dest with either the new
    archive's content or nothing — the pre-existing bytes must be
    restored on any mid-promotion OSError.
    """
    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
def test_extract_zip_returns_500_on_promotion_failure(tmp_path):
    """shutil.move failures during promotion surface as HTTPException(500).

    A generic-exception path in store_local_file would swallow OSError
    from mid-promotion moves and return 200 even though the archive was
    only partially applied. Raising HTTPException forces the caller to
    propagate the failure.
    """
    import zipfile as _zf

    from server.app.api.v1.endpoints import embed as embed_mod
    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
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


@pytest.mark.unit
def test_extract_zip_overwrites_preexisting_file_on_success(tmp_path):
    """Happy path still replaces pre-existing basenames.

    Staging-and-promote must not regress the prior overwrite-on-success
    behaviour: a successful extraction of `report.txt` replaces the
    pre-existing `report.txt` in *dest* rather than creating a duplicate
    or leaving the old content.
    """
    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
def test_extract_zip_preserves_preexisting_file_on_failure(tmp_path):
    """Pre-existing files in *dest* survive a failed extraction intact.

    The shared embedding temp directory accumulates files across
    multipart uploads and prior /local/store calls. If a corrupt ZIP
    member happens to share a basename with one of those pre-existing
    files, the rollback must not touch it — neither the bytes nor the
    mtime should change.
    """
    import zipfile as _zf

    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
def test_extract_zip_rolls_back_on_mid_member_failure(tmp_path):
    """Streaming extraction must stay atomic across CRC / decompression failures.

    A malformed member can fail its integrity check after the streaming
    read has already written partial bytes to the staging file, while a
    previous member already extracted successfully. Both the partial
    member AND the earlier-extracted file must be removed before the
    exception propagates.
    """
    import zipfile as _zf

    from server.app.api.v1.endpoints.embed import _extract_zip

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


@pytest.mark.unit
def test_extract_zip_raises_400_for_non_zip_input(tmp_path):
    """Non-ZIP uploads surface as HTTPException(400) rather than BadZipFile.

    A caller's generic `except Exception` would otherwise swallow
    BadZipFile and return success even though extraction never happened
    (and could leave artefacts behind under other failure modes).
    """
    from server.app.api.v1.endpoints.embed import _extract_zip

    src = tmp_path / "notazip.zip"
    src.write_bytes(b"this is not a zip file")
    dest = tmp_path / "out"
    dest.mkdir()

    with pytest.raises(HTTPException) as exc:
        _extract_zip(src, dest)
    assert exc.value.status_code == 400


@pytest.mark.unit
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
