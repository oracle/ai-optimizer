"""Identity-owned workspace and route-policy tests."""

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from server.app.api.mcp.router import router as mcp_router
from server.app.api.v1.endpoints.chat import get_orchestrator
from server.app.api.v1.router import router
from server.app.auth import dependencies
from server.app.auth import workspace as workspace_module
from server.app.auth.models import Principal
from server.app.auth.policy import ROUTE_POLICIES
from server.app.auth.service import AUTHENTICATORS, AuthenticationError
from server.app.core.schemas import ClientSettings
from server.app.core.settings import _client_store
from server.app.runtime.langgraph.chat import ChatOrchestrator

_ADMIN_ID = UUID("f4304c28-4bf6-5e7d-a284-33cc0a5a6c01")
_MEMBER_ID = UUID("0fc6d82d-56ea-44c6-933f-a50fe69db9e0")


def _route_names(routes):
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _route_names(route.original_router.routes)
        else:
            yield route.name


@pytest.mark.unit
def test_every_authenticated_route_has_a_policy():
    public = {
        "liveness_probe",
        "readiness_probe",
        "get_status",
        "swagger_ui",
        "auth_config",
        "login",
    }
    protected = (set(_route_names(router.routes)) - public) | (set(_route_names(mcp_router.routes)) - {"mcp_healthz"})
    assert protected <= ROUTE_POLICIES.keys()


@pytest.fixture
def two_users(monkeypatch):
    principals = {
        "test-token": Principal(
            user_id=_ADMIN_ID,
            subject="ADMIN",
            username="Admin",
            auth_source="database_end_user",
            roles=frozenset({"admin"}),
        ),
        "member-token": Principal(
            user_id=_MEMBER_ID,
            subject="MEMBER",
            username="Member",
            auth_source="database_end_user",
            roles=frozenset({"member"}),
        ),
    }

    class Authenticator:
        async def authenticate(self, credential):
            try:
                return principals[credential.value]
            except KeyError:
                raise AuthenticationError("Invalid credential") from None

    monkeypatch.setitem(AUTHENTICATORS, "local_users", Authenticator())
    monkeypatch.setattr(dependencies, "ensure_workspace", AsyncMock())
    monkeypatch.setattr(
        "server.app.api.v1.endpoints.settings.persist_client_settings",
        AsyncMock(return_value=True),
    )

    workspace_keys = (f"user:{_ADMIN_ID}", f"user:{_MEMBER_ID}")
    _client_store.clear()
    for key in workspace_keys:
        get_orchestrator().history.clear(key)

    yield

    _client_store.clear()
    for key in workspace_keys:
        get_orchestrator().history.clear(key)


@pytest.mark.unit
@pytest.mark.anyio
async def test_two_users_have_isolated_settings_and_history(app_client, two_users):
    del two_users
    admin_headers = {"Authorization": "Bearer test-token"}
    member_headers = {"Authorization": "Bearer member-token"}

    assert (
        await app_client.put("/v1/settings", json={"database": {"alias": "ADMIN_DB"}}, headers=admin_headers)
    ).status_code == 200
    assert (
        await app_client.put("/v1/settings", json={"database": {"alias": "MEMBER_DB"}}, headers=member_headers)
    ).status_code == 200

    admin_settings = (await app_client.get("/v1/settings", headers=admin_headers)).json()["client_settings"]
    member_settings = (await app_client.get("/v1/settings", headers=member_headers)).json()["client_settings"]
    assert admin_settings["database"]["alias"] == "ADMIN_DB"
    assert member_settings["database"]["alias"] == "MEMBER_DB"

    orchestrator = get_orchestrator()
    orchestrator.history.append(f"user:{_ADMIN_ID}", "user", "admin only")
    orchestrator.history.append(f"user:{_MEMBER_ID}", "user", "member only")
    assert (await app_client.get("/v1/chat/history", headers=admin_headers)).json()["messages"][0][
        "content"
    ] == "admin only"
    assert (await app_client.get("/v1/chat/history", headers=member_headers)).json()["messages"][0][
        "content"
    ] == "member only"


@pytest.mark.unit
@pytest.mark.anyio
async def test_member_cannot_mutate_shared_configuration(app_client, two_users):
    del two_users
    member = {"Authorization": "Bearer member-token"}
    admin = {"Authorization": "Bearer test-token"}
    assert (await app_client.post("/v1/databases", headers=member)).status_code == 403
    assert (await app_client.post("/v1/databases", headers=admin)).status_code == 422


@pytest.mark.unit
@pytest.mark.anyio
async def test_concurrent_chat_receives_each_request_credential(app_client, two_users, monkeypatch):
    del two_users
    observed = []

    async def execute_chat(question, client, bearer):
        observed.append((client, bearer))
        return {"result": question}

    monkeypatch.setattr(get_orchestrator(), "execute_chat", execute_chat)
    responses = await asyncio.gather(
        app_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "one"}]},
            headers={"Authorization": "Bearer test-token"},
        ),
        app_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "two"}]},
            headers={"Authorization": "Bearer member-token"},
        ),
    )
    assert [response.status_code for response in responses] == [200, 200]
    assert set(observed) == {(f"user:{_ADMIN_ID}", "test-token"), (f"user:{_MEMBER_ID}", "member-token")}


@pytest.mark.unit
@pytest.mark.anyio
async def test_request_credentials_are_not_stored_in_chat_session_cache(monkeypatch):
    client_settings = ClientSettings(client="workspace")
    client_settings.ll_model.provider = "openai"
    client_settings.ll_model.id = "model"
    orchestrator = ChatOrchestrator("http://mcp", resolve_client=lambda _key: client_settings)
    build = AsyncMock(side_effect=[object(), object()])
    monkeypatch.setattr(orchestrator, "_build_session", build)

    await orchestrator._get_or_create_session("workspace", "first-token")
    await orchestrator._get_or_create_session("workspace", "second-token")

    assert build.await_count == 2
    assert orchestrator._session_cache == {}


@pytest.mark.unit
@pytest.mark.anyio
async def test_mcp_workspace_uses_authenticated_principal(monkeypatch):
    token = type("Token", (), {"client_id": str(_MEMBER_ID)})()
    ensure = AsyncMock()
    monkeypatch.setattr(workspace_module, "get_access_token", lambda: token)
    monkeypatch.setattr(workspace_module, "ensure_workspace", ensure)

    key = await workspace_module.mcp_workspace_key("caller-thread")

    assert key == f"user:{_MEMBER_ID}"
    ensure.assert_awaited_once_with(key)
