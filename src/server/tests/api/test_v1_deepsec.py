"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the Deep Data Security API endpoints.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import oracledb
import pytest
from pydantic import SecretStr

from server.app.database.schemas import DatabaseConfig
from server.app.deepsec.database import DeepSecError
from server.tests.api.conftest import _create_mock_pool

MODULE = "server.app.api.v1.endpoints.deepsec"


def _base_cfg() -> DatabaseConfig:
    return DatabaseConfig(alias="CORE", username="OWNER", password=SecretStr("pw"), dsn="dsn")

_STATUS = {
    "available": True,
    "version": "23.26.2.0.0",
    "capabilities": {
        "create_data_role": True,
        "drop_data_role": True,
        "create_end_user": True,
        "drop_end_user": True,
        "manage_data_grants": True,
        "grant_data_roles": True,
        "list_data_roles": True,
        "list_end_users": True,
        "list_data_grants": True,
        "list_data_role_grants": True,
    },
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
async def test_create_end_user_uses_db_password(app_client, auth_headers, mock_db):
    """End user is provisioned with the connected database user's password."""
    db_config = MagicMock()
    db_config.password = "DBPASS"
    with (
        patch(f"{MODULE}.get_client_db_config", return_value=db_config),
        patch(f"{MODULE}.deepsec_db.create_end_user", AsyncMock()) as mock_create,
    ):
        resp = await app_client.post("/v1/deepsec/end-users", json={"name": "EU"}, headers=auth_headers)
    assert resp.status_code == 200
    assert "EU" in resp.json()["message"]
    # The password forwarded to the DDL is the database user's, not anything from the request body.
    assert mock_create.await_args is not None
    assert mock_create.await_args.args[2] == "DBPASS"


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_end_user_forwards_schema(app_client, auth_headers, mock_db):
    """The schema_name from the request is forwarded to the CREATE END USER DDL."""
    db_config = MagicMock()
    db_config.password = "DBPASS"
    with (
        patch(f"{MODULE}.get_client_db_config", return_value=db_config),
        patch(f"{MODULE}.deepsec_db.create_end_user", AsyncMock()) as mock_create,
    ):
        resp = await app_client.post(
            "/v1/deepsec/end-users", json={"name": "EU", "schema_name": "ACADEMY"}, headers=auth_headers
        )
    assert resp.status_code == 200
    assert mock_create.await_args is not None
    assert mock_create.await_args.args[3] == "ACADEMY"


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_end_user_requires_db_password(app_client, auth_headers, mock_db):
    """Reject creation when the database user's password is unavailable."""
    db_config = MagicMock()
    db_config.password = None
    with patch(f"{MODULE}.get_client_db_config", return_value=db_config):
        resp = await app_client.post("/v1/deepsec/end-users", json={"name": "EU"}, headers=auth_headers)
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
# Data role grants (role -> end user membership)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_data_role_grants(app_client, auth_headers, mock_db):
    grants = [{"data_role": "EMPLOYEE_ROLE", "grantee": "EMMA", "start_time": None, "end_time": None}]
    with patch(f"{MODULE}.deepsec_db.list_data_role_grants", AsyncMock(return_value=grants)):
        resp = await app_client.get("/v1/deepsec/data-role-grants", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["grantee"] == "EMMA"


@pytest.mark.unit
@pytest.mark.anyio
async def test_grant_data_role(app_client, auth_headers, mock_db):
    payload = {"grantee": "EMMA", "roles": ["EMPLOYEE_ROLE", "MANAGER_ROLE"]}
    with patch(f"{MODULE}.deepsec_db.grant_data_role", AsyncMock()) as mock_grant:
        resp = await app_client.post("/v1/deepsec/data-role-grants", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    mock_grant.assert_awaited_once()
    # roles list and grantee forwarded positionally to the DDL builder.
    assert mock_grant.await_args is not None
    assert mock_grant.await_args.args[1] == ["EMPLOYEE_ROLE", "MANAGER_ROLE"]
    assert mock_grant.await_args.args[2] == "EMMA"


@pytest.mark.unit
@pytest.mark.anyio
async def test_grant_data_role_requires_a_role(app_client, auth_headers, mock_db):
    resp = await app_client.post(
        "/v1/deepsec/data-role-grants", json={"grantee": "EMMA", "roles": []}, headers=auth_headers
    )
    assert resp.status_code == 400


@pytest.mark.unit
@pytest.mark.anyio
async def test_revoke_data_role(app_client, auth_headers, mock_db):
    with patch(f"{MODULE}.deepsec_db.revoke_data_role", AsyncMock()) as mock_revoke:
        resp = await app_client.delete("/v1/deepsec/data-role-grants/EMMA/EMPLOYEE_ROLE", headers=auth_headers)
    assert resp.status_code == 200
    mock_revoke.assert_awaited_once()
    # endpoint maps the path (grantee, role) to revoke_data_role(conn, role, grantee).
    assert mock_revoke.await_args is not None
    assert mock_revoke.await_args.args[1] == "EMPLOYEE_ROLE"
    assert mock_revoke.await_args.args[2] == "EMMA"


@pytest.mark.unit
@pytest.mark.anyio
async def test_grant_data_role_requires_auth(app_client):
    """POST /data-role-grants rejects requests without an API key."""
    resp = await app_client.post("/v1/deepsec/data-role-grants", json={"grantee": "x", "roles": ["r"]})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Connect-as (chat tools connect as a DDS end user)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_connect_as_registers_managed(app_client, auth_headers, mock_db):
    """A successful connect-as registers a runtime-only managed connection (strict, no persist)."""
    with (
        patch(f"{MODULE}.get_client_db_config", return_value=_base_cfg()),
        patch(f"{MODULE}._find_config_ci", return_value=None),
        patch(f"{MODULE}.register_database", AsyncMock(return_value=None)) as mock_reg,
        patch(f"{MODULE}.refresh_sqlcl_proxy", AsyncMock()) as mock_refresh,
    ):
        resp = await app_client.post(
            "/v1/deepsec/connect-as", json={"end_user": "SCOUT1"}, headers=auth_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"alias": "CORE::SCOUT1", "base_alias": "CORE", "end_user": "SCOUT1"}
    # Registered strictly and runtime-only.
    assert mock_reg.await_args is not None
    assert mock_reg.await_args.kwargs == {"require_usable": True, "persist": False, "managed_by": "dds:CORE"}
    mock_refresh.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_connect_as_strict_failure_registers_nothing(app_client, auth_headers, mock_db):
    """A failed end-user login returns 400 and triggers no SQLcl refresh."""
    with (
        patch(f"{MODULE}.get_client_db_config", return_value=_base_cfg()),
        patch(f"{MODULE}._find_config_ci", return_value=None),
        patch(f"{MODULE}.register_database", AsyncMock(return_value="ORA-01017: invalid credential")),
        patch(f"{MODULE}.refresh_sqlcl_proxy", AsyncMock()) as mock_refresh,
    ):
        resp = await app_client.post(
            "/v1/deepsec/connect-as", json={"end_user": "SCOUT1"}, headers=auth_headers
        )
    assert resp.status_code == 400
    assert "ORA-01017" in resp.json()["detail"]
    mock_refresh.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_connect_as_stale_failure_refreshes_sqlcl(app_client, auth_headers, mock_db):
    """If a stale managed alias is removed and re-registration then fails, SQLcl is still
    refreshed so its store stops advertising the removed alias (no orphan)."""
    stale = DatabaseConfig(alias="CORE::SCOUT1", username="SCOUT1", managed_by="dds:CORE")
    stale.usable = False  # stale → torn down before re-register
    with (
        patch(f"{MODULE}.get_client_db_config", return_value=_base_cfg()),
        patch(f"{MODULE}._find_config_ci", return_value=stale),
        patch(f"{MODULE}.clear_dds_for", AsyncMock(return_value={"core::scout1"})) as mock_clear,
        patch(f"{MODULE}.register_database", AsyncMock(return_value="ORA-01017: invalid credential")),
        patch(f"{MODULE}.refresh_sqlcl_proxy", AsyncMock()) as mock_refresh,
    ):
        resp = await app_client.post(
            "/v1/deepsec/connect-as", json={"end_user": "SCOUT1"}, headers=auth_headers
        )
    assert resp.status_code == 400
    # Stale entry torn down (config + referencing settings) and the store rebuilt despite the failure.
    mock_clear.assert_awaited_once_with(alias="CORE::SCOUT1")
    mock_refresh.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_connect_as_reuses_existing_usable(app_client, auth_headers, mock_db):
    """An already-usable managed connection is reused without re-registering."""
    existing = DatabaseConfig(alias="CORE::SCOUT1", username="SCOUT1", managed_by="dds:CORE")
    existing.pool = object()  # type: ignore[assignment]
    existing.usable = True
    with (
        patch(f"{MODULE}.get_client_db_config", return_value=_base_cfg()),
        patch(f"{MODULE}._find_config_ci", return_value=existing),
        patch(f"{MODULE}.register_database", AsyncMock()) as mock_reg,
        patch(f"{MODULE}.refresh_sqlcl_proxy", AsyncMock()) as mock_refresh,
    ):
        resp = await app_client.post(
            "/v1/deepsec/connect-as", json={"end_user": "SCOUT1"}, headers=auth_headers
        )
    assert resp.status_code == 200
    assert resp.json()["alias"] == "CORE::SCOUT1"
    mock_reg.assert_not_awaited()
    mock_refresh.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_connect_as_rejects_non_managed_alias_collision(app_client, auth_headers, mock_db):
    """An ordinary (non-managed) config occupying the deterministic alias is a conflict, not a reuse.

    Reusing it would report success for a connection resolve_effective_tool_alias() later rejects
    (managed_by missing), silently breaking the sidebar toggle; re-registering would append a
    duplicate alias. The endpoint must refuse and leave the colliding config untouched.
    """
    collision = DatabaseConfig(alias="CORE::SCOUT1", username="SOMEONE")  # managed_by=None (ordinary)
    collision.pool = object()  # type: ignore[assignment]
    collision.usable = True
    with (
        patch(f"{MODULE}.get_client_db_config", return_value=_base_cfg()),
        patch(f"{MODULE}._find_config_ci", return_value=collision),
        patch(f"{MODULE}.register_database", AsyncMock()) as mock_reg,
        patch(f"{MODULE}.clear_dds_for", AsyncMock(return_value=set())) as mock_clear,
        patch(f"{MODULE}.refresh_sqlcl_proxy", AsyncMock()) as mock_refresh,
    ):
        resp = await app_client.post(
            "/v1/deepsec/connect-as", json={"end_user": "SCOUT1"}, headers=auth_headers
        )
    assert resp.status_code == 409
    # The ordinary connection was neither reused-as-managed, torn down, nor duplicated.
    mock_reg.assert_not_awaited()
    mock_clear.assert_not_awaited()
    mock_refresh.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_connect_as_requires_usable_owner(app_client, auth_headers, mock_db):
    """503 when the owner database is unavailable."""
    with patch(f"{MODULE}.get_client_db_config", return_value=None):
        resp = await app_client.post(
            "/v1/deepsec/connect-as", json={"end_user": "SCOUT1"}, headers=auth_headers
        )
    assert resp.status_code == 503


@pytest.mark.unit
@pytest.mark.anyio
async def test_clear_connect_as(app_client, auth_headers, mock_db):
    """DELETE /connect-as tears down the managed connection and refreshes SQLcl when something was removed."""
    dds = MagicMock(alias="CORE::SCOUT1", base_alias="CORE", end_user="SCOUT1")
    client_cs = MagicMock(deep_data_security=dds)
    with (
        patch(f"{MODULE}.resolve_client", return_value=client_cs),
        patch(f"{MODULE}.clear_dds_for", AsyncMock(return_value={"core::scout1"})) as mock_clear,
        patch(f"{MODULE}.refresh_sqlcl_proxy", AsyncMock()) as mock_refresh,
    ):
        resp = await app_client.delete("/v1/deepsec/connect-as", headers=auth_headers)
    assert resp.status_code == 200
    # Scoped to the exact managed alias — base_alias/end_user are NOT passed (avoids
    # OR-matching that would remove a same-end-user connection on another base).
    assert mock_clear.await_args is not None
    assert mock_clear.await_args.kwargs == {"alias": "CORE::SCOUT1"}
    mock_refresh.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_drop_end_user_clears_connect_as_for_current_base_only(app_client, auth_headers, mock_db):
    """Dropping an end user tears down its connection on the CURRENT base only (exact alias).

    End users are per-database accounts, so a same-named user on another base is distinct and
    must not be swept up — hence the endpoint clears by exact managed alias, not by end_user.
    """
    client_cs = MagicMock(database=MagicMock(alias="CORE"))
    with (
        patch(f"{MODULE}.resolve_client", return_value=client_cs),
        patch(f"{MODULE}.deepsec_db.drop_end_user", AsyncMock()),
        patch(f"{MODULE}.clear_dds_for", AsyncMock(return_value={"core::scout1"})) as mock_clear,
        patch(f"{MODULE}.refresh_sqlcl_proxy", AsyncMock()) as mock_refresh,
    ):
        resp = await app_client.delete("/v1/deepsec/end-users/SCOUT1", headers=auth_headers)
    assert resp.status_code == 200
    mock_clear.assert_awaited_once_with(alias="CORE::SCOUT1")
    mock_refresh.assert_awaited_once()


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
