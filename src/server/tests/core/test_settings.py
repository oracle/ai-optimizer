"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.core.settings — resolve_client, _apply_default_ll_model, _ensure_capacity.
"""
# spell-checker: disable

from typing import Literal

import pytest
from pydantic import SecretStr, ValidationError

from server.app.core.schemas import ClientSettings
from server.app.core.settings import (
    _PROTECTED_CLIENTS,
    CoreDatabaseConfigurationError,
    Settings,
    SettingsBase,
    _apply_default_ll_model,
    _client_store,
    _ensure_capacity,
    require_core_database_config,
    resolve_client,
    settings,
)
from server.app.database.schemas import DatabaseConfig
from server.app.models.schemas import ModelConfig
from server.tests.constants import TEST_OPENAI_MODEL_ID

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _restore_settings_state():
    """Save and restore settings and client store around each test."""
    original_models = settings.model_configs[:]
    original_cs = settings.client_settings.model_copy(deep=True)
    store_snapshot = dict(_client_store)

    yield

    settings.model_configs = original_models
    settings.client_settings = original_cs
    _client_store.clear()
    _client_store.update(store_snapshot)


def _make_model(
    provider, model_id, model_type: Literal["ll", "embed", "rerank"] = "ll", enabled=True, usable=True, **kwargs
):
    """Build a test ModelConfig."""
    return ModelConfig(
        provider=provider,
        id=model_id,
        type=model_type,
        enabled=enabled,
        status="available" if usable else "unreachable",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# SettingsBase validators
# ---------------------------------------------------------------------------


class TestSettingsBaseValidators:
    """Test SettingsBase field validators."""

    def test_server_address_default(self):
        """Default server_address is the wildcard bind address."""
        sb = SettingsBase()
        assert sb.server_address == "0.0.0.0"

    def test_normalize_url_prefix_adds_leading_slash(self):
        """Bare prefix gets a leading slash."""
        sb = SettingsBase(server_url_prefix="api")
        assert sb.server_url_prefix == "/api"

    def test_normalize_url_prefix_strips_trailing_slash(self):
        """Trailing slash is stripped."""
        sb = SettingsBase(server_url_prefix="/api/")
        assert sb.server_url_prefix == "/api"

    def test_normalize_url_prefix_empty_stays_empty(self):
        """Empty string stays empty."""
        sb = SettingsBase(server_url_prefix="")
        assert sb.server_url_prefix == ""

    def test_normalize_url_prefix_with_leading_slash(self):
        """Already-correct prefix is unchanged."""
        sb = SettingsBase(server_url_prefix="/v1")
        assert sb.server_url_prefix == "/v1"


class TestSettingsValidators:
    """Test application-only settings validation."""

    def test_mcp_cache_ttl_defaults_to_five_seconds(self):
        assert Settings.model_validate({}).mcp_cache_ttl_seconds == 5

    def test_mcp_cache_ttl_accepts_zero_from_environment(self, monkeypatch):
        monkeypatch.setenv("AIO_MCP_CACHE_TTL_SECONDS", "0")

        assert Settings().mcp_cache_ttl_seconds == 0

    def test_mcp_cache_ttl_rejects_negative_values(self):
        with pytest.raises(ValidationError):
            Settings.model_validate({"mcp_cache_ttl_seconds": -1})

    def test_requires_complete_core_bootstrap_settings(self, monkeypatch):
        monkeypatch.setenv("AIO_DB_DSN", "")

        app_settings = Settings(db_username="core_user", db_password=SecretStr("secret-value"))

        with pytest.raises(CoreDatabaseConfigurationError) as exc_info:
            require_core_database_config(app_settings)

        assert "AIO_DB_DSN" in str(exc_info.value)
        assert "secret-value" not in str(exc_info.value)

    def test_rejects_core_supplied_only_as_database_config(self, monkeypatch):
        monkeypatch.setenv("AIO_DB_USERNAME", "")
        monkeypatch.setenv("AIO_DB_PASSWORD", "")
        monkeypatch.setenv("AIO_DB_DSN", "")
        app_settings = Settings(
            database_configs=[
                DatabaseConfig(
                    alias="core",
                    username="file_user",
                    password=SecretStr("file_secret"),
                    dsn="file_dsn",
                )
            ]
        )

        with pytest.raises(CoreDatabaseConfigurationError) as exc_info:
            require_core_database_config(app_settings)

        message = str(exc_info.value)
        assert "AIO_DB_USERNAME" in message
        assert "AIO_DB_PASSWORD" in message
        assert "AIO_DB_DSN" in message
        assert "file_secret" not in message

    def test_builds_canonical_core_from_aio_settings(self):
        app_settings = Settings(
            db_username="aio_user",
            db_password=SecretStr("aio_secret"),
            db_dsn="aio_dsn",
            db_wallet_password=SecretStr("wallet_secret"),
            db_wallet_location="/wallet",
        )

        core = require_core_database_config(app_settings)

        assert core.alias == "CORE"
        assert core.username == "aio_user"
        assert core.password is not None
        assert core.password.get_secret_value() == "aio_secret"
        assert core.dsn == "aio_dsn"
        assert core.wallet_password is not None
        assert core.wallet_password.get_secret_value() == "wallet_secret"
        assert core.wallet_location == "/wallet"
        assert app_settings.database_configs == [core]

    def test_unprefixed_db_settings_are_ignored(self, monkeypatch):
        monkeypatch.setenv("DB_USERNAME", "db_user")
        monkeypatch.setenv("DB_PASSWORD", "db_secret")
        monkeypatch.setenv("DB_DSN", "db_dsn")
        monkeypatch.setenv("DB_WALLET_PASSWORD", "db_wallet_secret")
        app_settings = Settings(
            db_username="aio_user",
            db_password=SecretStr("aio_secret"),
            db_dsn="aio_dsn",
            db_wallet_password=SecretStr("aio_wallet_secret"),
        )

        core = require_core_database_config(app_settings)

        assert core.username == "aio_user"
        assert core.password is not None
        assert core.password.get_secret_value() == "aio_secret"
        assert core.dsn == "aio_dsn"
        assert core.wallet_password is not None
        assert core.wallet_password.get_secret_value() == "aio_wallet_secret"

    def test_db_pool_size_takes_precedence_over_aio_setting(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_SIZE", "9")

        app_settings = Settings(db_pool_size=3)

        assert app_settings.db_pool_size == 9


# ---------------------------------------------------------------------------
# _apply_default_ll_model
# ---------------------------------------------------------------------------


class TestApplyDefaultLlModel:
    """Test automatic language model assignment."""

    def test_skips_when_provider_already_set(self):
        """No change when ll_model.provider is already set."""
        cs = ClientSettings()
        cs.ll_model.provider = "openai"
        cs.ll_model.id = None
        settings.model_configs = [_make_model("anthropic", "claude")]

        _apply_default_ll_model(cs)

        assert cs.ll_model.provider == "openai"

    def test_skips_when_id_already_set(self):
        """No change when ll_model.id is already set."""
        cs = ClientSettings()
        cs.ll_model.provider = None
        cs.ll_model.id = TEST_OPENAI_MODEL_ID
        settings.model_configs = [_make_model("anthropic", "claude")]

        _apply_default_ll_model(cs)

        assert cs.ll_model.id == TEST_OPENAI_MODEL_ID

    def test_picks_first_enabled_usable_ll_model(self):
        """Selects the first model matching type=ll, enabled, usable."""
        settings.model_configs = [
            _make_model("openai", "embed-v3", model_type="embed"),
            _make_model("openai", TEST_OPENAI_MODEL_ID, enabled=False),
            _make_model("anthropic", "claude", enabled=True, usable=True),
            _make_model("openai", TEST_OPENAI_MODEL_ID, enabled=True, usable=True),
        ]
        cs = ClientSettings()

        _apply_default_ll_model(cs)

        assert cs.ll_model.provider == "anthropic"
        assert cs.ll_model.id == "claude"

    def test_copies_max_input_tokens_when_present(self):
        """max_input_tokens is copied from the selected model."""
        settings.model_configs = [_make_model("openai", TEST_OPENAI_MODEL_ID, max_input_tokens=128000)]
        cs = ClientSettings()

        _apply_default_ll_model(cs)

        assert cs.ll_model.max_input_tokens == 128000

    def test_copies_max_tokens_when_present(self):
        """max_tokens is copied from the selected model."""
        settings.model_configs = [_make_model("openai", TEST_OPENAI_MODEL_ID, max_tokens=8192)]
        cs = ClientSettings()

        _apply_default_ll_model(cs)

        assert cs.ll_model.max_tokens == 8192

    def test_no_matching_model_leaves_ll_model_unset(self):
        """When no enabled+usable ll model exists, ll_model stays None/None."""
        settings.model_configs = [
            _make_model("openai", "embed-v3", model_type="embed"),
            _make_model("openai", TEST_OPENAI_MODEL_ID, enabled=False),
        ]
        cs = ClientSettings()

        _apply_default_ll_model(cs)

        assert cs.ll_model.provider is None
        assert cs.ll_model.id is None


# ---------------------------------------------------------------------------
# _ensure_capacity
# ---------------------------------------------------------------------------


class TestEnsureCapacity:
    """Test LRU eviction for client store."""

    def test_under_capacity_no_eviction(self):
        """No eviction when under settings.max_clients."""
        _client_store.clear()
        _client_store["c1"] = ClientSettings(client="c1")
        _client_store["c2"] = ClientSettings(client="c2")

        _ensure_capacity()

        assert "c1" in _client_store
        assert "c2" in _client_store

    def test_at_capacity_evicts_oldest_non_protected(self):
        """Oldest non-protected entry is evicted when at capacity."""
        _client_store.clear()
        # Fill to capacity with non-protected clients
        for i in range(settings.max_clients):
            _client_store[f"client_{i}"] = ClientSettings(client=f"client_{i}")

        _ensure_capacity()

        assert "client_0" not in _client_store
        assert len(_client_store) == settings.max_clients - 1

    def test_only_protected_clients_remain_no_eviction(self):
        """When only protected clients remain, no eviction occurs."""
        _client_store.clear()
        for name in _PROTECTED_CLIENTS:
            _client_store[name] = ClientSettings(client=name)

        initial_size = len(_client_store)
        _ensure_capacity()

        assert len(_client_store) == initial_size

    def test_evicts_correct_entry_when_mixed(self):
        """Protected entries are skipped; first non-protected is evicted."""
        _client_store.clear()
        # Add protected first, then non-protected to fill
        for name in _PROTECTED_CLIENTS:
            _client_store[name] = ClientSettings(client=name)
        remaining = settings.max_clients - len(_PROTECTED_CLIENTS)
        for i in range(remaining):
            _client_store[f"c_{i}"] = ClientSettings(client=f"c_{i}")

        _ensure_capacity()

        # c_0 was the oldest non-protected
        assert "c_0" not in _client_store
        # Protected clients remain
        for name in _PROTECTED_CLIENTS:
            assert name in _client_store


# ---------------------------------------------------------------------------
# resolve_client
# ---------------------------------------------------------------------------


class TestResolveClient:
    """Test per-client resolution and caching."""

    def test_configured_returns_singleton(self):
        """CONFIGURED always returns the global settings.client_settings."""
        result = resolve_client("CONFIGURED")
        assert result is settings.client_settings

    def test_new_client_creates_deep_copy(self):
        """New client gets a deep copy independent of the original."""
        _client_store.clear()
        original_alias = settings.client_settings.database.alias

        cs = resolve_client("NEW_CLIENT")
        cs.database.alias = "MODIFIED"

        assert settings.client_settings.database.alias == original_alias

    def test_new_client_gets_client_name_set(self):
        """New client has its client field set to the requested name."""
        _client_store.clear()

        cs = resolve_client("MY_CLIENT")

        assert cs.client == "MY_CLIENT"

    def test_existing_client_moves_to_end(self):
        """Accessing an existing client moves it to end of OrderedDict (LRU)."""
        _client_store.clear()
        _client_store["A"] = ClientSettings(client="A")
        _client_store["B"] = ClientSettings(client="B")
        _client_store["C"] = ClientSettings(client="C")

        resolve_client("A")

        assert list(_client_store.keys())[-1] == "A"

    def test_existing_client_returns_same_instance(self):
        """Re-accessing a client returns the same cached instance."""
        _client_store.clear()

        first = resolve_client("REUSE")
        second = resolve_client("REUSE")

        assert first is second

    def test_applies_default_ll_model_on_creation(self):
        """New client gets the default ll_model applied."""
        _client_store.clear()
        settings.model_configs = [_make_model("openai", TEST_OPENAI_MODEL_ID)]

        cs = resolve_client("WITH_MODEL")

        assert cs.ll_model.provider == "openai"
        assert cs.ll_model.id == TEST_OPENAI_MODEL_ID

    def test_stored_in_client_store(self):
        """New client is stored in _client_store."""
        _client_store.clear()

        resolve_client("STORED")

        assert "STORED" in _client_store
