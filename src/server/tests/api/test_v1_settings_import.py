"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for POST /v1/settings/import endpoint.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, patch

import pytest

from server.app.api.v1.endpoints.settings import _client_store
from server.app.core.settings import settings
from server.app.database.schemas import DatabaseConfig
from server.app.mcp.prompts.schemas import PromptConfig
from server.app.models.schemas import ModelConfig
from server.app.oci.schemas import OciProfileConfig

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

ENDPOINT = "/v1/settings/import"
SETTINGS_MODULE = "server.app.api.v1.endpoints.settings"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_settings():
    """Save and restore settings state around each test."""
    saved = {
        "log_level": settings.log_level,
        "database_configs": list(settings.database_configs),
        "model_configs": list(settings.model_configs),
        "oci_configs": list(settings.oci_configs),
        "prompt_configs": list(settings.prompt_configs),
        "client_settings": settings.client_settings.model_copy(deep=True),
    }
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
    _client_store.clear()


@pytest.fixture
def mock_persist():
    """Prevent persist_settings from doing real DB I/O."""
    with patch(f"{SETTINGS_MODULE}.persist_settings", new_callable=AsyncMock) as m:
        yield m


@pytest.fixture
def mock_register_mcp_prompts():
    """Prevent register_mcp_prompts from doing real FastMCP registration."""
    with patch(f"{SETTINGS_MODULE}.register_mcp_prompts") as m:
        yield m


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def test_import_no_auth(app_client):
    """POST /import without API key returns 403."""
    resp = await app_client.post(ENDPOINT, json={})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Empty / no-op
# ---------------------------------------------------------------------------


async def test_import_empty_body(app_client, auth_headers, mock_persist):
    """An empty body is a valid no-op — returns 200 with all sections null."""
    resp = await app_client.post(ENDPOINT, json={}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"] is None
    assert data["model_configs"] is None
    assert data["oci_configs"] is None
    assert data["prompt_configs"] is None
    assert data["client_settings"] is None
    assert data["scalars"] is None


# ---------------------------------------------------------------------------
# Model configs
# ---------------------------------------------------------------------------


async def test_import_model_creates_new(app_client, auth_headers, mock_persist):
    """A new model ID is appended to settings."""
    settings.model_configs = []
    payload = {"model_configs": [{"id": "new-model", "type": "ll", "provider": "openai"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["model_configs"]["created"] == 1
    assert data["model_configs"]["updated"] == 0
    assert any(m.id == "new-model" for m in settings.model_configs)


async def test_import_model_updates_existing(app_client, auth_headers, mock_persist):
    """An existing model ID is updated in-place."""
    settings.model_configs = [ModelConfig(id="existing", type="ll", provider="openai")]
    payload = {"model_configs": [{"id": "existing", "type": "ll", "provider": "openai", "api_base": "http://updated"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["model_configs"]["updated"] == 1
    assert data["model_configs"]["created"] == 0
    assert settings.model_configs[0].api_base == "http://updated"


# ---------------------------------------------------------------------------
# Database configs
# ---------------------------------------------------------------------------


async def test_import_database_creates_new(app_client, auth_headers, mock_persist):
    """A new database alias is appended with usable=False."""
    settings.database_configs = [DatabaseConfig(alias="CORE")]
    payload = {"database_configs": [{"alias": "ANALYTICS", "dsn": "analytics_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["created"] == 1
    new_db = next(db for db in settings.database_configs if db.alias == "ANALYTICS")
    assert new_db.usable is False
    assert new_db.pool is None


async def test_import_database_updates_existing(app_client, auth_headers, mock_persist):
    """An existing database alias with changed credentials is reset to usable=False."""
    settings.database_configs = [
        DatabaseConfig(alias="CORE"),
        DatabaseConfig(alias="ANALYTICS", dsn="old_dsn", usable=True),
    ]
    payload = {"database_configs": [{"alias": "ANALYTICS", "dsn": "new_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["updated"] == 1
    analytics = next(db for db in settings.database_configs if db.alias == "ANALYTICS")
    assert analytics.dsn == "new_dsn"
    assert analytics.usable is False


async def test_import_database_preserves_usable_when_creds_unchanged(app_client, auth_headers, mock_persist):
    """An existing database alias imported with unchanged credentials keeps usable=True."""
    settings.database_configs = [
        DatabaseConfig(alias="CORE"),
        DatabaseConfig(alias="ANALYTICS", dsn="same_dsn", usable=True),
    ]
    payload = {"database_configs": [{"alias": "ANALYTICS", "dsn": "same_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["updated"] == 1
    analytics = next(db for db in settings.database_configs if db.alias == "ANALYTICS")
    assert analytics.dsn == "same_dsn"
    assert analytics.usable is True


async def test_import_database_preserves_usable_false_when_creds_unchanged(app_client, auth_headers, mock_persist):
    """A stale export with usable=True must not override a runtime usable=False."""
    settings.database_configs = [
        DatabaseConfig(alias="CORE"),
        DatabaseConfig(alias="ANALYTICS", dsn="same_dsn", usable=False),
    ]
    payload = {"database_configs": [{"alias": "ANALYTICS", "dsn": "same_dsn", "usable": True}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    assert settings.database_configs[0].usable is False


async def test_import_database_resets_usable_when_timeout_changes(app_client, auth_headers, mock_persist):
    """Changing tcp_connect_timeout invalidates the pool."""
    settings.database_configs = [
        DatabaseConfig(alias="CORE"),
        DatabaseConfig(alias="ANALYTICS", dsn="same_dsn", tcp_connect_timeout=30, usable=True),
    ]
    payload = {"database_configs": [{"alias": "ANALYTICS", "dsn": "same_dsn", "tcp_connect_timeout": 10}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    assert settings.database_configs[0].usable is False


async def test_import_legacy_v203_database_configs(app_client, auth_headers, mock_persist):
    """A v2.0.3-shaped single-database payload is promoted to CORE when no CORE exists."""
    settings.database_configs = []
    payload = {
        "database_configs": [
            {"name": "LEGACY", "user": "admin", "dsn": "//host/svc"},
        ]
    }

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["created"] == 1
    assert data["database_configs"]["skipped"] == 0
    new_db = next(db for db in settings.database_configs if db.alias == "CORE")
    assert new_db.username == "admin"
    assert new_db.dsn == "//host/svc"


async def test_import_invalid_json_returns_422(app_client, auth_headers):
    """Malformed JSON body returns 422 (FastAPI's default), not 500."""
    resp = await app_client.post(
        ENDPOINT,
        content=b"{ not valid json }",
        headers={**auth_headers, "content-type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("body", [[], "not an object", 42])
async def test_import_non_object_body_returns_422(app_client, auth_headers, body):
    """Syntactically valid but non-object JSON bodies yield 422 (not 500) from Pydantic."""
    resp = await app_client.post(ENDPOINT, json=body, headers=auth_headers)
    assert resp.status_code == 422


async def test_import_null_body_returns_422(app_client, auth_headers):
    """An explicit JSON `null` body yields 422, not 500."""
    resp = await app_client.post(
        ENDPOINT,
        content=b"null",
        headers={**auth_headers, "content-type": "application/json"},
    )
    assert resp.status_code == 422


async def test_import_database_skips_core(app_client, auth_headers, mock_persist):
    """CORE alias is silently skipped when CORE already exists."""
    settings.database_configs = [DatabaseConfig(alias="CORE")]
    payload = {"database_configs": [{"alias": "CORE", "dsn": "should_not_apply"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["skipped"] == 1
    assert data["database_configs"]["created"] == 0
    assert data["database_configs"]["updated"] == 0


async def test_import_promotes_first_db_to_core_when_no_core(app_client, auth_headers, mock_persist):
    """When no CORE exists, the first imported database is promoted to CORE."""
    settings.database_configs = []
    payload = {"database_configs": [{"alias": "ANALYTICS", "dsn": "analytics_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["created"] == 1
    assert data["database_configs"]["skipped"] == 0
    new_db = next(db for db in settings.database_configs if db.alias == "CORE")
    assert new_db.dsn == "analytics_dsn"


async def test_import_no_promotion_when_core_exists(app_client, auth_headers, mock_persist):
    """When CORE exists, a non-CORE database is imported with its original alias."""
    settings.database_configs = [DatabaseConfig(alias="CORE", dsn="core_dsn")]
    payload = {"database_configs": [{"alias": "ANALYTICS", "dsn": "analytics_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["created"] == 1
    assert data["database_configs"]["skipped"] == 0
    aliases = {db.alias for db in settings.database_configs}
    assert aliases == {"CORE", "ANALYTICS"}


async def test_import_empty_database_configs_no_crash(app_client, auth_headers, mock_persist):
    """An empty database_configs list does not crash when no CORE exists."""
    settings.database_configs = []
    payload = {"database_configs": []}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["created"] == 0
    assert data["database_configs"]["skipped"] == 0
    assert settings.database_configs == []


async def test_import_updates_existing_then_promotes_to_core(app_client, auth_headers, mock_persist):
    """An existing non-CORE DB is updated in-place, then promoted to CORE."""
    settings.database_configs = [DatabaseConfig(alias="LEGACY", dsn="old_dsn")]
    payload = {"database_configs": [{"alias": "LEGACY", "dsn": "new_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["updated"] == 1
    assert data["database_configs"]["created"] == 0
    assert len(settings.database_configs) == 1
    assert settings.database_configs[0].alias == "CORE"
    assert settings.database_configs[0].dsn == "new_dsn"


async def test_import_normalizes_lowercase_core_alias(app_client, auth_headers, mock_persist):
    """A lowercase 'core' alias is normalized to exact 'CORE' string."""
    settings.database_configs = []
    payload = {"database_configs": [{"alias": "core", "dsn": "core_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    assert settings.database_configs[0].alias == "CORE"
    assert settings.database_configs[0].dsn == "core_dsn"


async def test_import_no_promotion_when_incoming_has_core(app_client, auth_headers, mock_persist):
    """When no CORE exists but incoming already has a CORE alias, it is imported as-is."""
    settings.database_configs = []
    payload = {"database_configs": [{"alias": "CORE", "dsn": "core_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["created"] == 1
    assert data["database_configs"]["skipped"] == 0
    assert settings.database_configs[0].alias == "CORE"
    assert settings.database_configs[0].dsn == "core_dsn"


# ---------------------------------------------------------------------------
# OCI configs
# ---------------------------------------------------------------------------


async def test_import_oci_creates_new(app_client, auth_headers, mock_persist):
    """A new OCI profile is appended with usable=False."""
    settings.oci_configs = []
    payload = {"oci_configs": [{"auth_profile": "PROD", "region": "us-phoenix-1"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["oci_configs"]["created"] == 1
    new_oci = next(p for p in settings.oci_configs if p.auth_profile == "PROD")
    assert new_oci.usable is False


async def test_import_oci_updates_existing(app_client, auth_headers, mock_persist):
    """An existing OCI profile is updated in-place with usable=False."""
    settings.oci_configs = [OciProfileConfig(auth_profile="PROD", region="us-ashburn-1", usable=True)]
    payload = {"oci_configs": [{"auth_profile": "PROD", "region": "us-phoenix-1"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["oci_configs"]["updated"] == 1
    assert settings.oci_configs[0].region == "us-phoenix-1"
    assert settings.oci_configs[0].usable is False


# ---------------------------------------------------------------------------
# Prompt configs
# ---------------------------------------------------------------------------


async def test_import_prompt_updates_text(app_client, auth_headers, mock_persist, mock_register_mcp_prompts):
    """Prompt text is updated via reconcile and register_mcp_prompts is called."""
    settings.prompt_configs = [
        PromptConfig(name="test_prompt", title="Test", text="old text"),
    ]
    payload = {"prompt_configs": [{"name": "test_prompt", "title": "Test", "text": "new text"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["prompt_configs"]["updated"] == 1
    assert settings.prompt_configs[0].text == "new text"
    mock_register_mcp_prompts.assert_called_once()


async def test_import_prompt_skips_unknown(app_client, auth_headers, mock_persist, mock_register_mcp_prompts):
    """Prompts with unknown names are silently skipped."""
    settings.prompt_configs = [
        PromptConfig(name="known", title="Known", text="text"),
    ]
    payload = {"prompt_configs": [{"name": "unknown", "title": "Unknown", "text": "text"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["prompt_configs"]["updated"] == 0
    assert data["prompt_configs"]["skipped"] == 1


async def test_import_prompt_skips_unchanged(app_client, auth_headers, mock_persist, mock_register_mcp_prompts):
    """Prompts with the same text are counted as skipped."""
    settings.prompt_configs = [
        PromptConfig(name="stable", title="Stable", text="same text"),
    ]
    payload = {"prompt_configs": [{"name": "stable", "title": "Stable", "text": "same text"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["prompt_configs"]["updated"] == 0
    assert data["prompt_configs"]["skipped"] == 1


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------


async def test_import_scalar_log_level(app_client, auth_headers, mock_persist):
    """log_level is updated in settings."""
    settings.log_level = "INFO"
    payload = {"log_level": "DEBUG"}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["scalars"] == {"log_level": "DEBUG"}
    assert settings.log_level == "DEBUG"


async def test_import_ignores_protected_fields(app_client, auth_headers, mock_persist):
    """Fields not in SettingsImport schema (env, api_key, etc.) are silently dropped."""
    payload = {"env": "production", "api_key": "hacked", "server_port": 9999}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    # Protected fields should not have changed
    assert settings.env != "production"
    assert settings.api_key != "hacked"
    assert settings.server_port != 9999


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def test_import_persists_once(app_client, auth_headers, mock_persist):
    """persist_settings is called exactly once regardless of sections imported."""
    payload = {
        "log_level": "DEBUG",
        "model_configs": [{"id": "m1", "type": "ll", "provider": "openai"}],
        "database_configs": [{"alias": "DB1"}],
    }

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    mock_persist.assert_called_once()


async def test_import_rollback_does_not_promote_core(app_client, auth_headers):
    """When persistence fails, CORE promotion is skipped and aliases stay consistent."""
    settings.database_configs = [DatabaseConfig(alias="LEGACY", dsn="old")]
    settings.client_settings.database.alias = "LEGACY"
    payload = {"database_configs": [{"alias": "LEGACY", "dsn": "new"}]}

    with patch(f"{SETTINGS_MODULE}.persist_settings", new_callable=AsyncMock, return_value=False):
        resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 503
    # Rollback should restore original state — no CORE promotion occurred
    assert settings.database_configs[0].alias == "LEGACY"
    assert settings.client_settings.database.alias == "LEGACY"


# ---------------------------------------------------------------------------
# Case insensitive matching
# ---------------------------------------------------------------------------


async def test_import_case_insensitive(app_client, auth_headers, mock_persist):
    """Lowercase alias matches uppercase existing entry."""
    settings.database_configs = [DatabaseConfig(alias="CORE"), DatabaseConfig(alias="ANALYTICS", dsn="old_dsn")]
    payload = {"database_configs": [{"alias": "analytics", "dsn": "new_dsn"}]}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["database_configs"]["updated"] == 1
    assert data["database_configs"]["created"] == 0
    analytics = next(db for db in settings.database_configs if db.alias == "ANALYTICS")
    assert analytics.dsn == "new_dsn"


# ---------------------------------------------------------------------------
# Client settings
# ---------------------------------------------------------------------------


async def test_import_client_settings_applied(app_client, auth_headers, mock_persist):
    """client_settings are applied to the default CONFIGURED client."""
    payload = {"client_settings": {"database": {"alias": "ANALYTICS"}, "oci": {"auth_profile": "PROD"}}}

    resp = await app_client.post(ENDPOINT, json=payload, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["client_settings"] is True
    assert _client_store["CONFIGURED"].database.alias == "ANALYTICS"
    assert _client_store["CONFIGURED"].oci.auth_profile == "PROD"


async def test_import_client_settings_custom_client(app_client, auth_headers, mock_persist):
    """client_settings with explicit client param targets that client only."""
    payload = {"client_settings": {"database": {"alias": "ANALYTICS"}, "oci": {"auth_profile": "PROD"}}}

    resp = await app_client.post(f"{ENDPOINT}?client=MY_SESSION", json=payload, headers=auth_headers)

    assert resp.status_code == 200
    assert _client_store["MY_SESSION"].database.alias == "ANALYTICS"
    assert "CONFIGURED" not in _client_store
