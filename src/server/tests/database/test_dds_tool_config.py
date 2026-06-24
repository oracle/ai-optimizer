"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for the Deep Data Security 'connect as' tool-connection resolver and cleanup.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from server.app.core.settings import _client_store, resolve_client, settings
from server.app.database.config import (
    DdsConnectionError,
    clear_dds_for,
    get_tool_db_config,
    resolve_effective_tool_alias,
)
from server.app.database.schemas import DatabaseConfig

pytestmark = pytest.mark.unit


def _owner_cfg(alias: str = "CORE") -> DatabaseConfig:
    cfg = DatabaseConfig(alias=alias, username="OWNER")
    cfg.pool = object()  # type: ignore[assignment]
    cfg.usable = True
    return cfg


def _managed_cfg(base: str, end_user: str, *, usable: bool = True, with_pool: bool = True) -> DatabaseConfig:
    cfg = DatabaseConfig(alias=f"{base}::{end_user}".upper(), username=end_user, managed_by=f"dds:{base}")
    if with_pool:
        pool = MagicMock()
        pool.close = AsyncMock()
        cfg.pool = pool  # type: ignore[assignment]
    cfg.usable = usable
    return cfg


def _set_dds(*, enabled, end_user=None, alias=None, base_alias=None) -> None:
    dds = settings.client_settings.deep_data_security
    dds.enabled = enabled
    dds.end_user = end_user
    dds.alias = alias
    dds.base_alias = base_alias


# ---------------------------------------------------------------------------
# resolve_effective_tool_alias / get_tool_db_config
# ---------------------------------------------------------------------------


async def test_effective_alias_owner_when_disabled():
    owner = _owner_cfg("CORE")
    settings.database_configs = [owner]
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=False)

    assert resolve_effective_tool_alias() == "CORE"
    assert get_tool_db_config() is owner


async def test_effective_alias_owner_when_base_mismatch():
    """DDS configured for a different owner base is inactive — falls back to the owner."""
    owner = _owner_cfg("CORE")
    managed = _managed_cfg("OTHER", "SCOUT1")
    settings.database_configs = [owner, managed]
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=True, end_user="SCOUT1", alias=managed.alias, base_alias="OTHER")

    assert resolve_effective_tool_alias() == "CORE"
    assert get_tool_db_config() is owner


async def test_effective_alias_managed_when_active():
    owner = _owner_cfg("CORE")
    managed = _managed_cfg("CORE", "SCOUT1")
    settings.database_configs = [owner, managed]
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=True, end_user="SCOUT1", alias=managed.alias, base_alias="CORE")

    assert resolve_effective_tool_alias() == managed.alias
    assert get_tool_db_config() is managed


async def test_effective_alias_raises_when_active_missing():
    owner = _owner_cfg("CORE")
    settings.database_configs = [owner]  # managed alias absent
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=True, end_user="SCOUT1", alias="CORE::SCOUT1", base_alias="CORE")

    with pytest.raises(DdsConnectionError):
        resolve_effective_tool_alias()
    with pytest.raises(DdsConnectionError):
        get_tool_db_config()


async def test_effective_alias_raises_when_active_unusable():
    """Never fall back to the owner when the managed connection exists but is unusable."""
    owner = _owner_cfg("CORE")
    managed = _managed_cfg("CORE", "SCOUT1", usable=False)
    settings.database_configs = [owner, managed]
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=True, end_user="SCOUT1", alias=managed.alias, base_alias="CORE")

    with pytest.raises(DdsConnectionError):
        resolve_effective_tool_alias()


async def test_effective_alias_rejects_non_managed_alias():
    """A crafted/stale DDS alias pointing at an ordinary (non-managed) usable config must not
    route tools there — only the managed connection owned by the current base is acceptable."""
    owner = _owner_cfg("CORE")
    ordinary = _owner_cfg("PROD")  # ordinary usable config (managed_by=None)
    settings.database_configs = [owner, ordinary]
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=True, end_user="SCOUT1", alias="PROD", base_alias="CORE")

    with pytest.raises(DdsConnectionError):
        resolve_effective_tool_alias()
    with pytest.raises(DdsConnectionError):
        get_tool_db_config()


async def test_effective_alias_rejects_managed_alias_of_other_base():
    """A DDS alias pointing at a managed connection owned by a *different* base must be rejected
    (managed_by is dds:OTHER, not dds:CORE) — prevents cross-base/cross-identity routing."""
    owner = _owner_cfg("CORE")
    foreign = _managed_cfg("OTHER", "ADMIN")  # usable, but managed_by="dds:OTHER"
    settings.database_configs = [owner, foreign]
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=True, end_user="ADMIN", alias=foreign.alias, base_alias="CORE")

    with pytest.raises(DdsConnectionError):
        resolve_effective_tool_alias()


# ---------------------------------------------------------------------------
# clear_dds_for
# ---------------------------------------------------------------------------


async def test_clear_dds_for_removes_managed_and_clears_settings():
    owner = _owner_cfg("CORE")
    managed = _managed_cfg("CORE", "SCOUT1", with_pool=False)
    # Inject the pool with a locally-held close mock so we can assert it was awaited
    # (clear_dds_for nulls cfg.pool after closing, so we can't read it back afterwards).
    close = AsyncMock()
    managed.pool = MagicMock(close=close)  # type: ignore[assignment]
    settings.database_configs = [owner, managed]
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=True, end_user="SCOUT1", alias=managed.alias, base_alias="CORE")

    removed = await clear_dds_for(base_alias="CORE")

    assert removed == {managed.alias.lower()}
    assert managed not in settings.database_configs
    assert owner in settings.database_configs  # owner untouched
    dds = settings.client_settings.deep_data_security
    assert (dds.enabled, dds.end_user, dds.alias, dds.base_alias) == (False, None, None, None)
    close.assert_awaited_once()


async def test_clear_dds_for_by_base_removes_all_for_that_base():
    """base_alias removes every managed connection owned by that base, but no other base."""
    core_a = _managed_cfg("CORE", "SCOUT1")
    core_b = _managed_cfg("CORE", "AUDITOR")
    other = _managed_cfg("OTHER", "SCOUT1")
    settings.database_configs = [_owner_cfg("CORE"), core_a, core_b, other]

    removed = await clear_dds_for(base_alias="CORE")

    assert removed == {core_a.alias.lower(), core_b.alias.lower()}
    assert other in settings.database_configs  # different base, untouched


async def test_clear_dds_for_no_client_store_side_effects():
    """clear_dds_for clears matching per-client copies without creating new store entries."""
    managed = _managed_cfg("CORE", "SCOUT1")
    settings.database_configs = [_owner_cfg("CORE"), managed]
    settings.client_settings.database.alias = "CORE"
    _set_dds(enabled=False)  # CONFIGURED has no DDS setting

    # One real per-client entry that references the managed alias.
    _client_store.clear()
    cs = resolve_client("client-a")
    cs.deep_data_security.enabled = True
    cs.deep_data_security.end_user = "SCOUT1"
    cs.deep_data_security.alias = managed.alias
    cs.deep_data_security.base_alias = "CORE"
    before = set(_client_store.keys())

    removed = await clear_dds_for(base_alias="CORE")

    assert removed == {managed.alias.lower()}
    assert set(_client_store.keys()) == before  # no entries created/evicted
    cleared = _client_store["client-a"].deep_data_security
    assert (cleared.enabled, cleared.alias) == (False, None)


async def test_clear_dds_for_by_alias_is_scoped():
    """Clearing one managed alias must not remove a same-end-user connection on another base."""
    core = _managed_cfg("CORE", "SCOUT1")
    other = _managed_cfg("OTHER", "SCOUT1")  # same end user, different base
    settings.database_configs = [_owner_cfg("CORE"), core, other]

    removed = await clear_dds_for(alias=core.alias)

    assert removed == {core.alias.lower()}
    assert core not in settings.database_configs
    assert other in settings.database_configs  # untouched despite the shared end user


async def test_clear_dds_for_noop_returns_empty():
    settings.database_configs = [_owner_cfg("CORE")]
    removed = await clear_dds_for(base_alias="CORE")
    assert removed == set()


# ---------------------------------------------------------------------------
# persist_settings backstop: managed configs are never serialized
# ---------------------------------------------------------------------------


async def test_persist_settings_excludes_managed_configs():
    """Backstop invariant: a managed config in settings.database_configs is never persisted."""
    from server.app.database import settings as dbsettings

    owner = DatabaseConfig(alias="CORE", username="OWNER", password=SecretStr("pw"), dsn="dsn")
    managed = _managed_cfg("CORE", "SCOUT1", with_pool=False)
    settings.database_configs = [owner, managed]

    conn = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    captured: dict = {}

    async def _fake_execute(_conn, _sql, binds=None, **_kwargs):
        if binds and "settings" in binds:
            captured["payload"] = binds["settings"]
            return None
        return []  # carry-forward read in _load_raw_settings

    with (
        patch.object(dbsettings, "get_core_pool", return_value=pool),
        patch.object(dbsettings, "execute_sql", side_effect=_fake_execute),
        patch("server.app.oci.registry.get_oci_source_baseline", return_value={}),
    ):
        ok = await dbsettings.persist_settings()

    assert ok is True
    aliases = [c["alias"] for c in captured["payload"]["database_configs"]]
    assert "CORE" in aliases
    assert managed.alias not in aliases
