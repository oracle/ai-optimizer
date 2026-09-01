"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract tests for the `Client:` header (and `client` query param on
`/v1/settings/*`).

These tests exercise the client boundary in both supported authentication
postures. In API-key mode, a malformed raw client value is rejected with 422
by FastAPI. In development principal mode, the middleware replaces caller
supplied client values with the principal-owned session client before FastAPI
sees them.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from server.tests.api.conftest import _create_mock_pool
from server.tests.constants import TEST_OPENAI_MODEL_KEY

INVALID_CLIENT_VALUES = [
    "",  # Pydantic min_length
    "/abs/one",  # absolute path
    "/abs/two",  # absolute path
    "/abs",
    "../../../up",  # parent traversal
    "mixed/../etc",
    "client\nwithnewline",
    "client withspace",
    "\ttab\tseparated",
    ".",  # bare current-directory name
    "..",  # bare parent component
    "a" * 256,  # exceeds 255-char ceiling
    "client\\with\\backslash",  # Windows-style separator
]

# Unicode is blocked by httpx at the header-transport layer (headers must be
# latin-1/ascii), so we only assert server-side rejection where the value can
# actually reach the handler — i.e. the settings.py query parameter.
INVALID_CLIENT_VALUES_QUERY_ONLY = [
    *INVALID_CLIENT_VALUES,
    "unicode_café",  # non-ASCII rejected by pattern
]

VALID_CLIENT_VALUES = [
    "server",  # the hard-coded default
    "CONFIGURED",  # protected name used by settings.py
    "FACTORY",  # other protected name
    "550e8400-e29b-41d4-a716-446655440000",  # Streamlit UUID
    "c1",  # short test id
    "my-client_01",  # underscores and hyphens
    "team.alpha",  # persisted pre-upgrade id with a dot
    "alice@example.com",  # persisted pre-upgrade id with @ and dots
    "alice+dev@example.com",  # `+` is permitted when callers encode it
    "team:blue",  # colon — historically accepted, not dangerous
    "a" * 255,  # 255-char upper bound (matches DB column)
]


# ---------------------------------------------------------------------------
# /v1/embed — Client header
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_embed_deps():
    """Mock the minimum surface needed to let `GET /v1/embed/{vs}/files` reach the header validator."""
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    mock_cfg = MagicMock()
    mock_cfg.pool = pool
    mock_cfg.usable = True
    seen_clients: list[str] = []

    def _get_client_db_config(client):
        seen_clients.append(client)
        return mock_cfg, pool

    with (
        patch(
            "server.app.api.v1.endpoints.embed._get_client_db_config",
            side_effect=_get_client_db_config,
        ),
        patch(
            "server.app.api.v1.endpoints.embed.get_vector_store_files",
            new_callable=AsyncMock,
            return_value={
                "vector_store": "MY_VS",
                "total_files": 0,
                "total_chunks": 0,
                "orphaned_chunks": 0,
                "files": [],
            },
        ),
    ):
        yield seen_clients


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_client", INVALID_CLIENT_VALUES)
async def test_embed_client_header_contract(
    app_client, auth_headers, bad_client, test_auth_mode, owned_client_key, mock_embed_deps
):
    """Raw invalid clients reject in API-key mode and are replaced in development mode."""
    resp = await app_client.get(
        "/v1/embed/MY_VS/files",
        headers={**auth_headers, "Client": bad_client},
    )
    if test_auth_mode is None:
        assert resp.status_code == 422
        assert mock_embed_deps == []
    else:
        assert resp.status_code == 200
        assert mock_embed_deps == [owned_client_key]


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("good_client", VALID_CLIENT_VALUES)
async def test_embed_accepts_valid_client_header(
    app_client, auth_headers, good_client, test_auth_mode, owned_client_key, mock_embed_deps
):
    """Valid client requests authenticate and use the expected client key."""
    resp = await app_client.get(
        "/v1/embed/MY_VS/files",
        headers={**auth_headers, "Client": good_client},
    )
    assert resp.status_code == 200
    expected_client = good_client if test_auth_mode is None else owned_client_key
    assert mock_embed_deps == [expected_client]


# ---------------------------------------------------------------------------
# /v1/testbed — Client header
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_testbed_deps():
    """Stub testbed dependencies so the normalized client can be observed."""
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    seen_clients: list[str] = []

    def _capture_client(client):
        seen_clients.append(client)
        raise HTTPException(status_code=418, detail="client captured")

    with (
        patch("server.app.api.v1.endpoints.testbed.get_core_pool", return_value=pool),
        patch("server.app.api.v1.endpoints.testbed.get_oci_profile", side_effect=_capture_client),
    ):
        yield seen_clients


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_client", INVALID_CLIENT_VALUES)
async def test_testbed_client_header_contract(
    app_client, auth_headers, bad_client, test_auth_mode, owned_client_key, mock_testbed_deps
):
    """Raw invalid clients reject in API-key mode and are replaced in development mode."""
    import io as _io

    resp = await app_client.post(
        "/v1/testbed/testset_generate",
        data={"name": "T", "ll_model": TEST_OPENAI_MODEL_KEY, "embed_model": "openai/e", "questions": "2"},
        files=[("files", ("a.pdf", _io.BytesIO(b"%PDF-"), "application/pdf"))],
        headers={**auth_headers, "Client": bad_client},
    )
    if test_auth_mode is None:
        assert resp.status_code == 422
        assert mock_testbed_deps == []
    else:
        assert resp.status_code == 418
        assert mock_testbed_deps == [owned_client_key]


# ---------------------------------------------------------------------------
# /v1/chat — Client header
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_client", INVALID_CLIENT_VALUES)
async def test_chat_history_client_header_contract(
    app_client, auth_headers, bad_client, test_auth_mode, owned_client_key
):
    """Raw invalid clients reject in API-key mode and are replaced in development mode."""
    resp = await app_client.get(
        "/v1/chat/history",
        headers={**auth_headers, "Client": bad_client},
    )
    if test_auth_mode is None:
        assert resp.status_code == 422
    else:
        assert resp.status_code == 200
        assert resp.json()["client"] == owned_client_key


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("good_client", VALID_CLIENT_VALUES)
async def test_chat_history_accepts_valid_client_header(
    app_client, auth_headers, good_client, test_auth_mode, owned_client_key
):
    """Valid client requests authenticate and use the expected client key."""
    resp = await app_client.get(
        "/v1/chat/history",
        headers={**auth_headers, "Client": good_client},
    )
    assert resp.status_code == 200
    expected_client = good_client if test_auth_mode is None else owned_client_key
    assert resp.json()["client"] == expected_client


# ---------------------------------------------------------------------------
# /v1/oci — Client header
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_oci_deps():
    """Stub OCI work and capture the client-scoped temporary directory."""
    seen_clients: list[str] = []

    def _capture_temp_directory(client, _function):
        seen_clients.append(client)
        return MagicMock()

    with (
        patch("server.app.api.v1.endpoints.oci._find_oci_profile", return_value=MagicMock()),
        patch(
            "server.app.api.v1.endpoints.oci.get_temp_directory",
            side_effect=_capture_temp_directory,
        ),
        patch(
            "server.app.api.v1.endpoints.oci.download_bucket_objects_to_dir",
            new_callable=AsyncMock,
            return_value=([], []),
        ),
    ):
        yield seen_clients


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_client", INVALID_CLIENT_VALUES)
async def test_oci_download_client_header_contract(
    app_client, auth_headers, bad_client, test_auth_mode, owned_client_key, mock_oci_deps
):
    """Raw invalid clients reject in API-key mode and are replaced in development mode."""
    resp = await app_client.post(
        "/v1/oci/objects/download/my-bucket/DEFAULT",
        json=["file.txt"],
        headers={**auth_headers, "Client": bad_client},
    )
    if test_auth_mode is None:
        assert resp.status_code == 422
        assert mock_oci_deps == []
    else:
        assert resp.status_code == 200
        assert mock_oci_deps == [owned_client_key]


# ---------------------------------------------------------------------------
# /v1/settings — client query parameter (same ClientId contract)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad_client",
    # `""` is skipped — missing query params fall back to the default
    [v for v in INVALID_CLIENT_VALUES_QUERY_ONLY if v != ""],
)
async def test_settings_client_query_contract(app_client, auth_headers, bad_client, test_auth_mode, owned_client_key):
    """Raw invalid clients reject in API-key mode and are replaced in development mode."""
    resp = await app_client.get(
        "/v1/settings",
        params={"client": bad_client},
        headers=auth_headers,
    )
    if test_auth_mode is None:
        assert resp.status_code == 422
    else:
        assert resp.status_code == 200
        assert resp.json()["client_settings"]["client"] == owned_client_key


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("good_client", VALID_CLIENT_VALUES)
async def test_settings_accepts_valid_client_query(
    app_client, auth_headers, good_client, test_auth_mode, owned_client_key
):
    """Valid client requests authenticate and use the expected client key."""
    resp = await app_client.get(
        "/v1/settings",
        params={"client": good_client},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    expected_client = good_client if test_auth_mode is None else owned_client_key
    assert resp.json()["client_settings"]["client"] == expected_client
