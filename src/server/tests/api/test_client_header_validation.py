"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Contract tests for the `Client:` header (and `client` query param on
`/v1/settings/*`).

These tests pin the Pydantic `ClientId` contract at every endpoint that
accepts the identifier, so a malformed value is rejected with 422 before
any handler logic runs. The contract rejects path separators, whitespace,
null / control characters, and bare dot-components, while permitting
identifiers persisted by the prior unconstrained API (e.g. `team:blue`,
`alice+dev@example.com`) so they stay reachable across the upgrade.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.tests.api.conftest import _create_mock_pool

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
    with (
        patch(
            "server.app.api.v1.endpoints.embed._get_client_db_config",
            return_value=(mock_cfg, pool),
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
        yield


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_client", INVALID_CLIENT_VALUES)
async def test_embed_rejects_invalid_client_header(app_client, auth_headers, bad_client):
    """Invalid Client header → 422 before any embed handler runs."""
    resp = await app_client.get(
        "/v1/embed/MY_VS/files",
        headers={**auth_headers, "Client": bad_client},
    )
    assert resp.status_code == 422, (
        f"Expected 422 for Client={bad_client!r}, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("good_client", VALID_CLIENT_VALUES)
async def test_embed_accepts_valid_client_header(app_client, auth_headers, good_client, mock_embed_deps):
    """Valid Client header passes validation (endpoint may still error on other grounds, but not 422)."""
    del mock_embed_deps
    resp = await app_client.get(
        "/v1/embed/MY_VS/files",
        headers={**auth_headers, "Client": good_client},
    )
    assert resp.status_code != 422, (
        f"Valid client {good_client!r} was rejected with 422: {resp.text}"
    )


# ---------------------------------------------------------------------------
# /v1/testbed — Client header
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_testbed_deps():
    """Stub CORE pool so `POST /v1/testbed/testset_generate` can reach header validation."""
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    with patch(
        "server.app.api.v1.endpoints.testbed.get_core_pool",
        return_value=pool,
    ):
        yield


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_client", INVALID_CLIENT_VALUES)
async def test_testbed_rejects_invalid_client_header(app_client, auth_headers, bad_client, mock_testbed_deps):
    """Invalid Client header → 422 before any testbed handler runs."""
    del mock_testbed_deps
    import io as _io

    resp = await app_client.post(
        "/v1/testbed/testset_generate",
        data={"name": "T", "ll_model": "openai/gpt-5-mini", "embed_model": "openai/e", "questions": "2"},
        files=[("files", ("a.pdf", _io.BytesIO(b"%PDF-"), "application/pdf"))],
        headers={**auth_headers, "Client": bad_client},
    )
    assert resp.status_code == 422, (
        f"Expected 422 for Client={bad_client!r}, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# /v1/chat — Client header
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_client", INVALID_CLIENT_VALUES)
async def test_chat_history_rejects_invalid_client_header(app_client, auth_headers, bad_client):
    """Invalid Client header on GET /v1/chat/history → 422."""
    resp = await app_client.get(
        "/v1/chat/history",
        headers={**auth_headers, "Client": bad_client},
    )
    assert resp.status_code == 422, (
        f"Expected 422 for Client={bad_client!r}, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("good_client", VALID_CLIENT_VALUES)
async def test_chat_history_accepts_valid_client_header(app_client, auth_headers, good_client):
    """Valid Client header on GET /v1/chat/history passes validation."""
    resp = await app_client.get(
        "/v1/chat/history",
        headers={**auth_headers, "Client": good_client},
    )
    assert resp.status_code != 422, (
        f"Valid client {good_client!r} was rejected with 422: {resp.text}"
    )


# ---------------------------------------------------------------------------
# /v1/oci — Client header
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_client", INVALID_CLIENT_VALUES)
async def test_oci_download_rejects_invalid_client_header(app_client, auth_headers, bad_client):
    """Invalid Client header on POST /v1/oci/objects/download/... → 422."""
    resp = await app_client.post(
        "/v1/oci/objects/download/my-bucket/DEFAULT",
        json=["file.txt"],
        headers={**auth_headers, "Client": bad_client},
    )
    assert resp.status_code == 422, (
        f"Expected 422 for Client={bad_client!r}, got {resp.status_code}: {resp.text}"
    )


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
async def test_settings_rejects_invalid_client_query(app_client, auth_headers, bad_client):
    """Invalid `client` query param on GET /v1/settings → 422."""
    resp = await app_client.get(
        "/v1/settings",
        params={"client": bad_client},
        headers=auth_headers,
    )
    assert resp.status_code == 422, (
        f"Expected 422 for client={bad_client!r}, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("good_client", VALID_CLIENT_VALUES)
async def test_settings_accepts_valid_client_query(app_client, auth_headers, good_client):
    """Valid `client` query param on GET /v1/settings passes validation."""
    resp = await app_client.get(
        "/v1/settings",
        params={"client": good_client},
        headers=auth_headers,
    )
    assert resp.status_code != 422, (
        f"Valid client {good_client!r} was rejected with 422: {resp.text}"
    )
