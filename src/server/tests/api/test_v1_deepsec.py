"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the Deep Data Security API endpoints.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import oracledb
import pytest

from server.app.deepsec.database import DeepSecError
from server.tests.api.conftest import _create_mock_pool

MODULE = "server.app.api.v1.endpoints.deepsec"

_STATUS = {
    "available": True,
    "version": "23.26.2.0.0",
    "capabilities": {
        "create_data_role": True,
        "drop_data_role": True,
        "create_end_user": True,
        "drop_end_user": True,
        "manage_data_grants": True,
        "list_data_roles": True,
        "list_end_users": True,
        "list_data_grants": True,
    },
    "missing_privileges": [],
}


@pytest.fixture
def mock_db():
    """Patch the client pool resolution so endpoints get a usable pool."""
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    with patch(f"{MODULE}.get_client_pool", return_value=pool):
        yield conn


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_status_requires_auth(app_client):
    """GET /status rejects requests without an API key."""
    resp = await app_client.get("/v1/deepsec/status")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_data_role_requires_auth(app_client):
    """POST /data-roles rejects requests without an API key."""
    resp = await app_client.post("/v1/deepsec/data-roles", json={"name": "r"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_status_ok(app_client, auth_headers, mock_db):
    with patch(f"{MODULE}.deepsec_db.get_status", AsyncMock(return_value=_STATUS)):
        resp = await app_client.get("/v1/deepsec/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["capabilities"]["manage_data_grants"] is True


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_data_roles(app_client, auth_headers, mock_db):
    roles = [{"name": "ANALYST", "mapped_to": None, "enabled_by_default": True}]
    with patch(f"{MODULE}.deepsec_db.list_data_roles", AsyncMock(return_value=roles)):
        resp = await app_client.get("/v1/deepsec/data-roles", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "ANALYST"


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_data_role(app_client, auth_headers, mock_db):
    with patch(f"{MODULE}.deepsec_db.create_data_role", AsyncMock()) as mock_create:
        resp = await app_client.post(
            "/v1/deepsec/data-roles", json={"name": "ANALYST"}, headers=auth_headers
        )
    assert resp.status_code == 200
    assert "ANALYST" in resp.json()["message"]
    mock_create.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_end_user_requires_password(app_client, auth_headers, mock_db):
    resp = await app_client.post(
        "/v1/deepsec/end-users", json={"name": "EU", "password": ""}, headers=auth_headers
    )
    assert resp.status_code == 400


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_data_grant(app_client, auth_headers, mock_db):
    payload = {
        "name": "MASK_SALARY",
        "privileges": ["SELECT"],
        "object_name": "EMP",
        "grantee": "ANALYST",
        "columns": ["SALARY"],
        "all_columns_except": True,
    }
    with patch(f"{MODULE}.deepsec_db.create_data_grant", AsyncMock()) as mock_create:
        resp = await app_client.post("/v1/deepsec/data-grants", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    mock_create.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_validation_error_maps_to_400(app_client, auth_headers, mock_db):
    with patch(
        f"{MODULE}.deepsec_db.create_data_grant",
        AsyncMock(side_effect=DeepSecError("Invalid identifier: 'x;'")),
    ):
        resp = await app_client.post(
            "/v1/deepsec/data-grants",
            json={"name": "g", "privileges": ["SELECT"], "object_name": "t", "grantee": "r"},
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert "Invalid identifier" in resp.json()["detail"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_database_error_maps_to_400(app_client, auth_headers, mock_db):
    with patch(
        f"{MODULE}.deepsec_db.drop_data_grant",
        AsyncMock(side_effect=oracledb.DatabaseError("ORA-01031: insufficient privileges")),
    ):
        resp = await app_client.delete("/v1/deepsec/data-grants/g", headers=auth_headers)
    assert resp.status_code == 400
    assert "ORA-01031" in resp.json()["detail"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_status_503_when_db_unavailable(app_client, auth_headers):
    """When no usable pool resolves, status returns 503."""
    with (
        patch(f"{MODULE}.get_client_pool", return_value=None),
        patch(f"{MODULE}.resolve_client", return_value=MagicMock(database=MagicMock(alias="DEFAULT"))),
    ):
        resp = await app_client.get("/v1/deepsec/status", headers=auth_headers)
    assert resp.status_code == 503
