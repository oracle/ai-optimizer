"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for settings endpoint.
"""
# spell-checker: disable

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from server.app.core.schemas import ClientSettings
from server.app.core.settings import (
    _PROTECTED_CLIENTS,
    _client_store,
    _ensure_capacity,
    settings,
)
from server.tests.conftest import make_test_database_config, make_test_model_config, make_test_oci_profile
from server.tests.constants import TEST_OPENAI_MODEL_ID

SETTINGS_MODULE = "server.app.api.v1.endpoints.settings"


@pytest.fixture(autouse=True)
def _populate_configs():
    """Ensure settings has at least one DB, OCI, and Model config for sensitive-field tests."""
    original_db = settings.database_configs
    original_oci = settings.oci_configs
    original_model = settings.model_configs
    original_cs = settings.client_settings
    settings.database_configs = [make_test_database_config()]
    settings.oci_configs = [make_test_oci_profile()]
    settings.model_configs = [make_test_model_config()]
    settings.client_settings = original_cs.model_copy(deep=True)
    yield
    _client_store.clear()
    settings.database_configs = original_db
    settings.oci_configs = original_oci
    settings.model_configs = original_model
    settings.client_settings = original_cs


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_client_settings_no_auth(app_client):
    """Settings endpoint rejects requests without API key."""
    resp = await app_client.get("/v1/settings")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_client_settings_excludes_sensitive(app_client, auth_headers):
    """Default response omits sensitive fields from all config sections."""
    resp = await app_client.get("/v1/settings", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    # Top-level api_key must be excluded
    assert "api_key" not in body

    # Database sensitive fields must be excluded
    for db_entry in body.get("database_configs", []):
        assert "password" not in db_entry
        assert "wallet_password" not in db_entry
        # Non-sensitive fields should still be present
        assert "alias" in db_entry

    # Model sensitive fields must be excluded
    for model_entry in body.get("model_configs", []):
        assert "api_key" not in model_entry
        # Non-sensitive fields should still be present
        assert "id" in model_entry

    # OCI sensitive fields must be excluded
    for oci_entry in body.get("oci_configs", []):
        assert "fingerprint" not in oci_entry
        assert "key_content" not in oci_entry
        assert "pass_phrase" not in oci_entry
        assert "security_token_file" not in oci_entry
        # Non-sensitive fields should still be present
        assert "auth_profile" in oci_entry
        assert "key_file" in oci_entry

    # client_settings should be present from GET /settings
    assert "client_settings" in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_client_settings_rediscovers_vector_stores(app_client, auth_headers):
    """GET /settings reconciles cached vector_stores against the live DB.

    Simulates an admin DROP TABLE: the cache has a stale entry; the refresh
    helper returns an empty discovery; the response must mirror reality.
    """
    from server.app.embed.schemas import VectorStoreConfig

    settings.database_configs[0].vector_stores = [VectorStoreConfig(vector_store="STALE")]

    async def _clear(cfg):
        cfg.vector_stores = []

    with patch(f"{SETTINGS_MODULE}.refresh_db_vector_stores", new=AsyncMock(side_effect=_clear)) as mock_refresh:
        resp = await app_client.get("/v1/settings", headers=auth_headers)

    assert resp.status_code == 200
    mock_refresh.assert_awaited()
    body = resp.json()
    assert body["database_configs"][0].get("vector_stores", []) == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_client_settings_refreshes_vector_stores_in_parallel(app_client, auth_headers):
    """Per-DB refreshes run concurrently so one slow DB doesn't stack with others."""
    settings.database_configs = [
        make_test_database_config(alias="A"),
        make_test_database_config(alias="B"),
        make_test_database_config(alias="C"),
    ]
    expected_concurrency = len(settings.database_configs)
    in_flight = 0
    peak = 0

    async def _track(_cfg):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1

    with patch(f"{SETTINGS_MODULE}.refresh_db_vector_stores", new=AsyncMock(side_effect=_track)):
        resp = await app_client.get("/v1/settings", headers=auth_headers)

    assert resp.status_code == 200
    assert peak == expected_concurrency, f"expected {expected_concurrency} concurrent refreshes, observed peak={peak}"


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_client_settings_uses_standard_projection(app_client, auth_headers):
    """``GET /v1/settings`` uses the standard projection when extra params are present."""
    resp = await app_client.get("/v1/settings", params={"include_sensitive": "true"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    assert "api_key" not in body

    # Sensitive fields are omitted from every nested config.
    for db_entry in body.get("database_configs", []):
        assert "password" not in db_entry
        assert "wallet_password" not in db_entry
    for model_entry in body.get("model_configs", []):
        assert "api_key" not in model_entry
    for oci_entry in body.get("oci_configs", []):
        for key in ("fingerprint", "key_content", "pass_phrase", "security_token_file"):
            assert key not in oci_entry

    assert "client_settings" in body


# ---------------------------------------------------------------------------
# PUT /settings
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_client_settings_database_alias(app_client, auth_headers):
    """PUT /settings updates database.alias in memory."""
    resp = await app_client.put(
        "/v1/settings",
        json={"database": {"alias": "NEW_DB"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"]["alias"] == "NEW_DB"
    assert settings.client_settings.database.alias == "NEW_DB"


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_client_settings_oci_profile(app_client, auth_headers):
    """PUT /settings updates oci.auth_profile in memory."""
    resp = await app_client.put(
        "/v1/settings",
        json={"oci": {"auth_profile": "PROD"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["oci"]["auth_profile"] == "PROD"
    assert settings.client_settings.oci.auth_profile == "PROD"


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_client_settings_partial(app_client, auth_headers):
    """PUT /settings with only database does not reset oci."""
    settings.client_settings.oci.auth_profile = "KEEP_ME"
    resp = await app_client.put(
        "/v1/settings",
        json={"database": {"alias": "OTHER"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"]["alias"] == "OTHER"
    assert body["oci"]["auth_profile"] == "KEEP_ME"


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_client_settings_dds_field_merge(app_client, auth_headers):
    """PUT /settings field-merges deep_data_security so a lone {enabled} keeps end_user/alias."""
    dds = settings.client_settings.deep_data_security
    dds.enabled = False
    dds.end_user = "SCOUT1"
    dds.alias = "CORE::SCOUT1"
    dds.base_alias = "CORE"

    resp = await app_client.put(
        "/v1/settings",
        json={"deep_data_security": {"enabled": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()["deep_data_security"]
    assert body["enabled"] is True
    assert body["end_user"] == "SCOUT1"  # preserved by the field-merge
    assert body["alias"] == "CORE::SCOUT1"
    assert body["base_alias"] == "CORE"
    assert settings.client_settings.deep_data_security.enabled is True
    assert settings.client_settings.deep_data_security.end_user == "SCOUT1"


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_client_settings_no_auth(app_client):
    """PUT /settings rejects requests without API key."""
    resp = await app_client.put("/v1/settings", json={"database": {"alias": "X"}})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_client_settings_reflects_put(app_client, auth_headers):
    """GET /settings returns updated client_settings after PUT /settings."""
    put_resp = await app_client.put(
        "/v1/settings",
        json={"oci": {"auth_profile": "LONDON"}},
        headers=auth_headers,
    )
    assert put_resp.status_code == 200

    get_resp = await app_client.get("/v1/settings", headers=auth_headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["client_settings"]["oci"]["auth_profile"] == "LONDON"


# ---------------------------------------------------------------------------
# Per-client isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_settings_isolation(app_client, auth_headers):
    """Different client IDs get independent settings; default is unaffected."""
    # Update two separate clients
    resp_a = await app_client.put(
        "/v1/settings?client=AAA",
        json={"database": {"alias": "DB_AAA"}},
        headers=auth_headers,
    )
    assert resp_a.status_code == 200

    resp_b = await app_client.put(
        "/v1/settings?client=BBB",
        json={"database": {"alias": "DB_BBB"}},
        headers=auth_headers,
    )
    assert resp_b.status_code == 200

    # Each client sees only its own value
    get_a = await app_client.get("/v1/settings?client=AAA", headers=auth_headers)
    assert get_a.json()["client_settings"]["database"]["alias"] == "DB_AAA"

    get_b = await app_client.get("/v1/settings?client=BBB", headers=auth_headers)
    assert get_b.json()["client_settings"]["database"]["alias"] == "DB_BBB"

    # Default (CONFIGURED) still has the original default alias
    get_default = await app_client.get("/v1/settings", headers=auth_headers)
    default_alias = get_default.json()["client_settings"]["database"]["alias"]
    assert default_alias == "CORE"


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_settings_sees_server_configs(app_client, auth_headers):
    """GET /settings includes shared server configs alongside client settings."""
    resp = await app_client.get("/v1/settings?client=NEW_CLIENT", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    # Shared server-level configs are present
    assert "database_configs" in body
    assert "model_configs" in body
    assert "oci_configs" in body

    # Per-client settings are also present
    assert "client_settings" in body
    assert body["client_settings"]["client"] == "NEW_CLIENT"


# ---------------------------------------------------------------------------
# POST /settings
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_post_settings_no_auth(app_client):
    """POST /settings rejects requests without API key."""
    resp = await app_client.post("/v1/settings")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_post_settings_creates_client(app_client, auth_headers):
    """POST /settings creates a new client session with skeleton defaults."""
    resp = await app_client.post("/v1/settings?client=FRESH", headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()

    assert "client_settings" in body
    assert body["client_settings"]["client"] == "FRESH"
    assert body["client_settings"]["database"]["alias"] == "CORE"


@pytest.mark.unit
@pytest.mark.anyio
async def test_post_settings_duplicate_returns_409(app_client, auth_headers):
    """POST /settings returns 409 if client already exists."""
    resp1 = await app_client.post("/v1/settings?client=DUP", headers=auth_headers)
    assert resp1.status_code == 201

    resp2 = await app_client.post("/v1/settings?client=DUP", headers=auth_headers)
    assert resp2.status_code == 409


@pytest.mark.unit
@pytest.mark.anyio
async def test_post_settings_excludes_sensitive(app_client, auth_headers):
    """POST /settings excludes sensitive fields from the response."""
    resp = await app_client.post("/v1/settings?client=SAFE", headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()

    assert "api_key" not in body

    for db_entry in body.get("database_configs", []):
        assert "password" not in db_entry
        assert "wallet_password" not in db_entry

    for model_entry in body.get("model_configs", []):
        assert "api_key" not in model_entry

    for oci_entry in body.get("oci_configs", []):
        assert "fingerprint" not in oci_entry


@pytest.mark.unit
@pytest.mark.anyio
async def test_post_settings_excludes_managed_configs(app_client, auth_headers):
    """A new client session must not receive runtime-only DDS-managed connections, even when
    load_settings() falls back to the in-memory settings object."""
    from server.app.database.schemas import DatabaseConfig

    managed = DatabaseConfig(alias="CORE::SCOUT1", username="SCOUT1", managed_by="dds:CORE")
    saved = settings.database_configs
    settings.database_configs = [*saved, managed]
    try:
        # Force the in-memory fallback (no persisted CONFIGURED row) — the leak path.
        with patch(f"{SETTINGS_MODULE}.load_settings", AsyncMock(return_value=None)):
            resp = await app_client.post("/v1/settings?client=DDSLEAK", headers=auth_headers)
    finally:
        settings.database_configs = saved
        _client_store.pop("DDSLEAK", None)
    assert resp.status_code == 201
    aliases = [c["alias"] for c in resp.json().get("database_configs", [])]
    assert "CORE::SCOUT1" not in aliases


@pytest.mark.unit
@pytest.mark.anyio
async def test_post_settings_includes_server_configs(app_client, auth_headers):
    """POST /settings response includes shared server configs."""
    resp = await app_client.post("/v1/settings?client=CFG", headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()

    assert "database_configs" in body
    assert "model_configs" in body
    assert "oci_configs" in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_post_then_get_round_trip(app_client, auth_headers):
    """POST /settings followed by GET /settings returns the same client."""
    post_resp = await app_client.post("/v1/settings?client=ROUND", headers=auth_headers)
    assert post_resp.status_code == 201

    get_resp = await app_client.get("/v1/settings?client=ROUND", headers=auth_headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["client_settings"]["client"] == "ROUND"


# ---------------------------------------------------------------------------
# DELETE /settings
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_settings_no_auth(app_client):
    """DELETE /settings rejects requests without API key."""
    resp = await app_client.delete("/v1/settings?client=X")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_settings_success(app_client, auth_headers):
    """DELETE /settings removes an existing client and calls delete_row."""
    # Create a client first
    _client_store["TEMP"] = ClientSettings(client="TEMP")

    with patch(f"{SETTINGS_MODULE}.delete_row", new_callable=AsyncMock) as mock_del:
        resp = await app_client.delete("/v1/settings?client=TEMP", headers=auth_headers)

    assert resp.status_code == 204
    assert "TEMP" not in _client_store
    mock_del.assert_awaited_once_with("TEMP")


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_settings_configured_forbidden(app_client, auth_headers):
    """DELETE /settings returns 403 for the CONFIGURED client."""
    resp = await app_client.delete("/v1/settings?client=CONFIGURED", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_settings_factory_forbidden(app_client, auth_headers):
    """DELETE /settings returns 403 for the FACTORY client."""
    resp = await app_client.delete("/v1/settings?client=FACTORY", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_settings_not_found(app_client, auth_headers):
    """DELETE /settings returns 404 for a missing client."""
    resp = await app_client.delete("/v1/settings?client=GHOST", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_settings_missing_param(app_client, auth_headers):
    """DELETE /settings returns 422 when client param is missing."""
    resp = await app_client.delete("/v1/settings", headers=auth_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_lru_eviction_oldest_non_protected():
    """Filling the store to capacity evicts the oldest non-protected entry."""
    _client_store.clear()

    # Seed protected clients so they exist but should never be evicted
    for name in _PROTECTED_CLIENTS:
        _client_store[name] = ClientSettings(client=name)

    # Fill remaining slots
    for i in range(settings.max_clients - len(_PROTECTED_CLIENTS)):
        _client_store[f"c{i}"] = ClientSettings(client=f"c{i}")

    assert len(_client_store) == settings.max_clients

    # Trigger eviction — oldest non-protected key is "c0"
    _ensure_capacity()

    assert len(_client_store) == settings.max_clients - 1
    assert "c0" not in _client_store
    for name in _PROTECTED_CLIENTS:
        assert name in _client_store


# ---------------------------------------------------------------------------
# POST /settings/server/copy
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_copy_to_server_no_auth(app_client):
    """POST /settings/server/copy rejects requests without API key."""
    resp = await app_client.post("/v1/settings/server/copy")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_copy_to_server_success(app_client, auth_headers):
    """POST /settings/server/copy copies source client settings to server."""
    _client_store["SOURCE"] = ClientSettings(client="SOURCE")
    _client_store["SOURCE"].database.alias = "MY_DB"

    with patch(f"{SETTINGS_MODULE}.persist_client_settings", new_callable=AsyncMock, return_value=True):
        resp = await app_client.post("/v1/settings/server/copy?client=SOURCE", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["client"] == "server"
    assert body["database"]["alias"] == "MY_DB"
    assert _client_store["server"].client == "server"


@pytest.mark.unit
@pytest.mark.anyio
async def test_copy_to_server_excludes_dds_override(app_client, auth_headers):
    """POST /settings/server/copy must not carry the runtime-only DDS override into the server client."""
    source = ClientSettings(client="SOURCE")
    source.database.alias = "MY_DB"
    source.deep_data_security.enabled = True
    source.deep_data_security.end_user = "SCOUT1"
    source.deep_data_security.alias = "DDS_MY_DB_SCOUT1"
    source.deep_data_security.base_alias = "MY_DB"
    _client_store["SOURCE"] = source

    with patch(f"{SETTINGS_MODULE}.persist_client_settings", new_callable=AsyncMock, return_value=True):
        resp = await app_client.post("/v1/settings/server/copy?client=SOURCE", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()["deep_data_security"]
    assert body["enabled"] is False
    assert body["end_user"] is None
    assert body["alias"] is None
    assert body["base_alias"] is None
    # The source's own override is untouched.
    assert _client_store["SOURCE"].deep_data_security.enabled is True
    server_dds = _client_store["server"].deep_data_security
    assert server_dds.enabled is False
    assert server_dds.alias is None


@pytest.mark.unit
@pytest.mark.anyio
async def test_copy_to_server_persist_failure_rollback(app_client, auth_headers):
    """POST /settings/server/copy rollback restores original server entry on persist failure."""
    original_server = ClientSettings(client="server")
    original_server.database.alias = "ORIGINAL"
    _client_store["server"] = original_server
    _client_store["SOURCE"] = ClientSettings(client="SOURCE")

    with patch(f"{SETTINGS_MODULE}.persist_client_settings", new_callable=AsyncMock, return_value=False):
        resp = await app_client.post("/v1/settings/server/copy?client=SOURCE", headers=auth_headers)

    assert resp.status_code == 503
    assert _client_store["server"].database.alias == "ORIGINAL"


# ---------------------------------------------------------------------------
# POST /settings/reset
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_no_auth(app_client):
    """POST /settings/reset rejects requests without API key."""
    resp = await app_client.post("/v1/settings/reset")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_success(app_client, auth_headers):
    """POST /settings/reset resets to factory defaults and evicts non-protected clients."""
    _client_store["ephemeral"] = ClientSettings(client="ephemeral")

    with (
        patch(f"{SETTINGS_MODULE}.reset_factory_models"),
        patch(f"{SETTINGS_MODULE}.apply_env_overrides"),
        patch(f"{SETTINGS_MODULE}.load_ollama_models", new_callable=AsyncMock),
        patch(f"{SETTINGS_MODULE}.load_factory_prompts"),
        patch(f"{SETTINGS_MODULE}.register_mcp_prompts"),
        patch(f"{SETTINGS_MODULE}.check_model_reachability", new_callable=AsyncMock),
        patch(f"{SETTINGS_MODULE}.persist_settings", new_callable=AsyncMock, return_value=True),
        patch(f"{SETTINGS_MODULE}.persist_client_settings", new_callable=AsyncMock, return_value=True),
    ):
        resp = await app_client.post("/v1/settings/reset", headers=auth_headers)

    assert resp.status_code == 200
    assert "ephemeral" not in _client_store
    body = resp.json()
    assert "client_settings" in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_excludes_managed_configs(app_client, auth_headers):
    """Reset preserves database_configs but must not surface runtime-only DDS-managed connections."""
    from server.app.database.schemas import DatabaseConfig

    managed = DatabaseConfig(alias="CORE::SCOUT1", username="SCOUT1", managed_by="dds:CORE")
    saved = settings.database_configs
    settings.database_configs = [*saved, managed]
    try:
        with (
            patch(f"{SETTINGS_MODULE}.reset_factory_models"),
            patch(f"{SETTINGS_MODULE}.apply_env_overrides"),
            patch(f"{SETTINGS_MODULE}.load_ollama_models", new_callable=AsyncMock),
            patch(f"{SETTINGS_MODULE}.load_factory_prompts"),
            patch(f"{SETTINGS_MODULE}.register_mcp_prompts"),
            patch(f"{SETTINGS_MODULE}.check_model_reachability", new_callable=AsyncMock),
            patch(f"{SETTINGS_MODULE}.persist_settings", new_callable=AsyncMock, return_value=True),
            patch(f"{SETTINGS_MODULE}.persist_client_settings", new_callable=AsyncMock, return_value=True),
        ):
            resp = await app_client.post("/v1/settings/reset", headers=auth_headers)
    finally:
        settings.database_configs = saved
    assert resp.status_code == 200
    aliases = [c["alias"] for c in resp.json().get("database_configs", [])]
    assert "CORE::SCOUT1" not in aliases


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_persist_failure_rollback(app_client, auth_headers):
    """POST /settings/reset rolls back on persist failure."""
    saved_models = list(settings.model_configs)

    with (
        patch(f"{SETTINGS_MODULE}.reset_factory_models"),
        patch(f"{SETTINGS_MODULE}.apply_env_overrides"),
        patch(f"{SETTINGS_MODULE}.load_ollama_models", new_callable=AsyncMock),
        patch(f"{SETTINGS_MODULE}.load_factory_prompts"),
        patch(f"{SETTINGS_MODULE}.register_mcp_prompts"),
        patch(f"{SETTINGS_MODULE}.check_model_reachability", new_callable=AsyncMock),
        patch(f"{SETTINGS_MODULE}.persist_settings", new_callable=AsyncMock, return_value=False),
    ):
        resp = await app_client.post("/v1/settings/reset", headers=auth_headers)

    assert resp.status_code == 503
    # model_configs should be rolled back
    assert settings.model_configs == saved_models


# ---------------------------------------------------------------------------
# _reconcile_ll_model_tokens
# ---------------------------------------------------------------------------


class TestReconcileLlModelTokens:
    """Tests for _reconcile_ll_model_tokens."""

    @staticmethod
    def _make_ll_model(**kwargs):
        """Create an LLModelSettings with given overrides."""
        from server.app.core.schemas import LLModelSettings

        return LLModelSettings(**kwargs)

    @staticmethod
    def _make_model_config(**kwargs):
        """Create a minimal mock model config."""
        from unittest.mock import MagicMock

        cfg = MagicMock()
        cfg.max_input_tokens = kwargs.get("max_input_tokens", 128000)
        cfg.max_tokens = kwargs.get("max_tokens", 4096)
        return cfg

    @pytest.mark.unit
    def test_same_model_no_change(self):
        """No changes when provider/id are unchanged."""
        from server.app.api.v1.endpoints.settings import _reconcile_ll_model_tokens

        current = self._make_ll_model(provider="openai", id=TEST_OPENAI_MODEL_ID)
        incoming = self._make_ll_model(provider="openai", id=TEST_OPENAI_MODEL_ID)
        original_max = incoming.max_tokens
        _reconcile_ll_model_tokens(current, incoming)
        assert incoming.max_tokens == original_max

    @pytest.mark.unit
    def test_unknown_new_model(self):
        """Unknown new model leaves incoming unchanged."""
        from server.app.api.v1.endpoints.settings import _reconcile_ll_model_tokens

        current = self._make_ll_model(provider="openai", id=TEST_OPENAI_MODEL_ID)
        incoming = self._make_ll_model(provider="openai", id="unknown-model")
        original_max = incoming.max_tokens
        with patch(f"{SETTINGS_MODULE}.find_model", return_value=None):
            _reconcile_ll_model_tokens(current, incoming)
        assert incoming.max_tokens == original_max

    @pytest.mark.unit
    def test_updates_max_input_tokens(self):
        """Changing model should update max_input_tokens from new model config."""
        from server.app.api.v1.endpoints.settings import _reconcile_ll_model_tokens

        new_cfg = self._make_model_config(max_input_tokens=200000, max_tokens=8192)
        old_cfg = self._make_model_config(max_input_tokens=128000, max_tokens=4096)
        current = self._make_ll_model(provider="openai", id=TEST_OPENAI_MODEL_ID, max_tokens=4096)
        incoming = self._make_ll_model(provider="anthropic", id="claude-3")
        with patch(f"{SETTINGS_MODULE}.find_model", side_effect=[new_cfg, old_cfg]):
            _reconcile_ll_model_tokens(current, incoming)
        assert incoming.max_input_tokens == 200000

    @pytest.mark.unit
    def test_adopts_new_default_max_tokens(self):
        """When user did not customize max_tokens, adopt new model's default."""
        from server.app.api.v1.endpoints.settings import _reconcile_ll_model_tokens

        old_cfg = self._make_model_config(max_input_tokens=128000, max_tokens=4096)
        new_cfg = self._make_model_config(max_input_tokens=200000, max_tokens=8192)
        # current.max_tokens matches old default → user did NOT customize
        current = self._make_ll_model(provider="openai", id=TEST_OPENAI_MODEL_ID, max_tokens=4096)
        incoming = self._make_ll_model(provider="anthropic", id="claude-3")
        with patch(f"{SETTINGS_MODULE}.find_model", side_effect=[new_cfg, old_cfg]):
            _reconcile_ll_model_tokens(current, incoming)
        assert incoming.max_tokens == 8192

    @pytest.mark.unit
    def test_first_model_selection_adopts_model_default_max_tokens(self):
        """Selecting the first model does not treat the schema default as customized."""
        from server.app.api.v1.endpoints.settings import _reconcile_ll_model_tokens

        new_cfg = self._make_model_config(max_input_tokens=40960, max_tokens=16384)
        current = self._make_ll_model(max_tokens=4096)
        incoming = self._make_ll_model(provider="ollama", id="granite4.1:8b")
        with patch(f"{SETTINGS_MODULE}.find_model", return_value=new_cfg):
            _reconcile_ll_model_tokens(current, incoming)
        assert incoming.max_input_tokens == 40960
        assert incoming.max_tokens == 16384

    @pytest.mark.unit
    def test_caps_customized_max_tokens(self):
        """When user customized max_tokens and it exceeds new max_input_tokens, cap it."""
        from server.app.api.v1.endpoints.settings import _reconcile_ll_model_tokens

        old_cfg = self._make_model_config(max_input_tokens=128000, max_tokens=4096)
        new_cfg = self._make_model_config(max_input_tokens=1000, max_tokens=500)
        # current.max_tokens differs from old default → user DID customize
        current = self._make_ll_model(provider="openai", id=TEST_OPENAI_MODEL_ID, max_tokens=5000)
        incoming = self._make_ll_model(provider="anthropic", id="claude-3")
        with patch(f"{SETTINGS_MODULE}.find_model", side_effect=[new_cfg, old_cfg]):
            _reconcile_ll_model_tokens(current, incoming)
        # Capped to new model's max_input_tokens
        assert incoming.max_tokens == 1000


# ---------------------------------------------------------------------------
# /v1/settings/export
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_export_requires_confirm_header(app_client, auth_headers):
    """POST /v1/settings/export requires the confirmation header."""
    resp = await app_client.post("/v1/settings/export", headers=auth_headers)
    assert resp.status_code == 400
    assert "X-Confirm-Export" in resp.json()["detail"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_export_rejects_falsy_confirm_header(app_client, auth_headers):
    """X-Confirm-Export must be the expected literal value."""
    headers = {**auth_headers, "X-Confirm-Export": "yes"}
    resp = await app_client.post("/v1/settings/export", headers=headers)
    assert resp.status_code == 400


@pytest.mark.unit
@pytest.mark.anyio
async def test_export_uses_reveal_projection_with_confirm_header(app_client, auth_headers):
    """With the confirm header, response uses the export projection."""
    headers = {**auth_headers, "X-Confirm-Export": "true"}
    resp = await app_client.post("/v1/settings/export", headers=headers)
    assert resp.status_code == 200
    body = resp.text
    # Defensive: regardless of fixture-set values, the masked sentinel must
    # not appear anywhere in the export body.
    assert "**********" not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_export_excludes_model_status(app_client, auth_headers):
    """``status`` is runtime-determined and must not be carried in an export."""
    model = make_test_model_config(enabled=True)
    model.status = "available"
    settings.model_configs = [model]
    headers = {**auth_headers, "X-Confirm-Export": "true"}
    resp = await app_client.post("/v1/settings/export", headers=headers)
    assert resp.status_code == 200
    exported = resp.json()["model_configs"]
    assert exported  # sanity: a model is present
    for mc in exported:
        assert "status" not in mc


@pytest.mark.unit
@pytest.mark.anyio
async def test_export_excludes_database_usable(app_client, auth_headers):
    """``usable`` is runtime-determined (DB reachability) and must not be carried in an export."""
    db = make_test_database_config(alias="CORE")
    db.usable = True
    settings.database_configs = [db]
    headers = {**auth_headers, "X-Confirm-Export": "true"}
    resp = await app_client.post("/v1/settings/export", headers=headers)
    assert resp.status_code == 200
    exported = resp.json()["database_configs"]
    assert exported  # sanity: a database is present
    for dc in exported:
        assert "usable" not in dc


@pytest.mark.unit
@pytest.mark.anyio
async def test_export_excludes_oci_usable(app_client, auth_headers):
    """``usable`` is runtime-determined (OCI profile reachability) and must not be carried in an export."""
    profile = make_test_oci_profile()
    profile.usable = True
    settings.oci_configs = [profile]
    headers = {**auth_headers, "X-Confirm-Export": "true"}
    resp = await app_client.post("/v1/settings/export", headers=headers)
    assert resp.status_code == 200
    exported = resp.json()["oci_configs"]
    assert exported  # sanity: a profile is present
    for oc in exported:
        assert "usable" not in oc


@pytest.mark.unit
@pytest.mark.anyio
async def test_export_excludes_managed_configs(app_client, auth_headers):
    """Export never includes runtime-only DDS-managed connections (this payload reveals creds)."""
    from server.app.database.schemas import DatabaseConfig

    saved = settings.database_configs
    settings.database_configs = [
        make_test_database_config(alias="CORE"),
        DatabaseConfig(alias="CORE::SCOUT1", username="SCOUT1", managed_by="dds:CORE"),
    ]
    try:
        headers = {**auth_headers, "X-Confirm-Export": "true"}
        resp = await app_client.post("/v1/settings/export", headers=headers)
    finally:
        settings.database_configs = saved
    assert resp.status_code == 200
    aliases = [c["alias"] for c in resp.json().get("database_configs", [])]
    assert "CORE" in aliases
    assert "CORE::SCOUT1" not in aliases
