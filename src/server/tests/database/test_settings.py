"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for persist_settings() and load_settings() against a real Oracle container.
"""
# spell-checker: disable

import json
from unittest.mock import AsyncMock, patch

import pytest

from server.app.core.settings import SettingsBase, settings
from server.app.database.config import close_pool
from server.app.database.registry import init_core_database
from server.app.database.schemas import DatabaseConfig
from server.app.database.settings import (
    _UPSERT_SQL,
    delete_row,
    load_client_settings,
    load_oci_genai_overlay,
    load_settings,
    persist_settings,
    row_exists,
)
from server.app.database.sql import execute_sql
from server.tests.conftest import make_core_db_config

pytestmark = [pytest.mark.db, pytest.mark.integration]

_READ_SQL = "SELECT client, settings, is_current FROM aio_settings WHERE client = :client"
_DELETE_SQL = "DELETE FROM aio_settings WHERE client = :client"


@pytest.fixture(autouse=True)
def _reset_oci_source_baseline():
    """Isolate the OCI source-baseline (mutated by ``load_oci_profiles``) per test.

    Without this, a registry test that ran first leaks its baseline into the
    persist tests and changes which fields count as "deltas".
    """
    from server.app.oci.registry import get_oci_source_baseline, reset_oci_source_baseline

    saved = dict(get_oci_source_baseline())
    reset_oci_source_baseline()
    yield
    reset_oci_source_baseline()
    get_oci_source_baseline().update(saved)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def core_pool(oracle_db_container):
    """Create a CORE pool and ensure aio_settings is clean before tests."""
    del oracle_db_container

    cfg = make_core_db_config()

    pool = await init_core_database(cfg)
    assert pool is not None

    saved_configs = list(settings.database_configs)
    settings.database_configs = [cfg]

    try:
        async with pool.acquire() as conn:
            await execute_sql(conn, _DELETE_SQL, {"client": "CONFIGURED"})
            await execute_sql(conn, _DELETE_SQL, {"client": "FACTORY"})
            await conn.commit()
        yield cfg
    finally:
        settings.database_configs = saved_configs
        await close_pool(pool)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _read_aio_settings(cfg: DatabaseConfig, client: str = "CONFIGURED") -> list:
    """SELECT the persisted row for the given client."""
    assert cfg.pool is not None
    async with cfg.pool.acquire() as conn:
        rows = await execute_sql(conn, _READ_SQL, {"client": client})
    return rows or []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_persist_settings_inserts_row(core_pool):
    """persist_settings() should INSERT a row on first call."""
    await persist_settings()

    rows = await _read_aio_settings(core_pool)
    assert len(rows) == 1
    client, payload, is_current = rows[0]
    assert client == "CONFIGURED"
    assert is_current == 1

    data = json.loads(payload) if isinstance(payload, str) else payload
    assert "database_configs" in data
    assert "env" in data


async def test_persist_settings_upsert_updates(core_pool):
    """Two calls should result in one row with the latest value."""
    original_level = settings.log_level

    await persist_settings()

    # Mutate a setting
    settings.log_level = "DEBUG"
    try:
        await persist_settings()

        rows = await _read_aio_settings(core_pool)
        assert len(rows) == 1

        data = json.loads(rows[0][1]) if isinstance(rows[0][1], str) else rows[0][1]
        assert data["log_level"] == "DEBUG"
    finally:
        settings.log_level = original_level


async def test_persist_settings_no_pool_is_noop(core_pool):
    """When the pool is removed, persist_settings() is a graceful no-op."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        # Should not raise
        await persist_settings()
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


async def test_persist_settings_factory_row(core_pool):
    """persist_settings('FACTORY', is_current=False) creates a non-current row."""
    await persist_settings("FACTORY", is_current=False)

    rows = await _read_aio_settings(core_pool, client="FACTORY")
    assert len(rows) == 1
    client, payload, is_current = rows[0]
    assert client == "FACTORY"
    assert is_current == 0

    data = json.loads(payload) if isinstance(payload, str) else payload
    assert "env" in data


async def test_persist_settings_round_trip_json(core_pool):
    """Persisted JSON should deserialize back into SettingsBase with matching fields."""
    await persist_settings()

    rows = await _read_aio_settings(core_pool)
    assert len(rows) == 1

    raw = json.loads(rows[0][1]) if isinstance(rows[0][1], str) else rows[0][1]
    restored = SettingsBase.model_validate(raw)

    assert restored.env == settings.env
    assert restored.server_port == settings.server_port
    assert restored.log_level == settings.log_level
    # API_KEY is never returned
    assert restored.api_key is None


async def test_persist_settings_stores_real_secret_values(core_pool):
    """Persisted JSON carries the configured value, not the masked sentinel."""
    from pydantic import SecretStr

    from server.app.core.secrets import reveal
    from server.app.models.schemas import ModelConfig

    sentinel = "SENTINEL_MODEL_KEY_ROUNDTRIP"
    saved_models = settings.model_configs[:]
    settings.model_configs = [
        ModelConfig(type="ll", provider="openai", id="test-model", api_key=SecretStr(sentinel))
    ]
    try:
        await persist_settings()
        rows = await _read_aio_settings(core_pool)
        assert len(rows) == 1

        raw = rows[0][1]
        # ``oracledb`` may return numeric JSON values as ``Decimal`` (e.g. the
        # epoch ``created`` field on ModelConfig); ``default=str`` lets the
        # assertion stringify them without rejecting the dump.
        raw_str = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        # Stored value survived the round-trip; masked sentinel is absent.
        assert sentinel in raw_str
        assert "**********" not in raw_str

        # Re-loading restores a SecretStr-typed field with the stored value.
        data = json.loads(raw_str) if isinstance(raw, str) else raw
        restored = SettingsBase.model_validate(data)
        restored_key = restored.model_configs[0].api_key
        assert isinstance(restored_key, SecretStr)
        assert reveal(restored_key) == sentinel
    finally:
        settings.model_configs = saved_models


# ---------------------------------------------------------------------------
# load_settings tests
# ---------------------------------------------------------------------------


async def test_load_settings_returns_settings_base(core_pool):
    """load_settings() returns a SettingsBase after persist_settings()."""
    del core_pool
    await persist_settings()

    result = await load_settings()

    assert isinstance(result, SettingsBase)
    assert result.env == settings.env
    assert result.log_level == settings.log_level
    # API_KEY is never returned
    assert result.api_key is None


async def test_load_settings_empty_table(core_pool):
    """load_settings() returns None when no rows exist."""
    del core_pool
    result = await load_settings()
    assert result is None


async def test_load_settings_no_pool_returns_none(core_pool):
    """load_settings() returns None when CORE pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        result = await load_settings()
        assert result is None
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


async def test_load_client_settings_round_trip(core_pool):
    """client_settings is excluded from persistence, so load returns None."""
    del core_pool
    await persist_settings()

    result = await load_client_settings()

    assert result is None


async def test_load_client_settings_error_path(core_pool):
    """JSON decode errors are handled and return None."""
    cfg = core_pool
    assert cfg.pool is not None

    with patch(
        "server.app.database.settings.execute_sql",
        new_callable=AsyncMock,
        return_value=[("not-json",)],
    ) as mock_exec:
        result = await load_client_settings()

    mock_exec.assert_awaited()
    assert result is None


async def test_row_exists_true(core_pool):
    """row_exists() returns True when the row has been persisted."""
    del core_pool
    await persist_settings()
    assert await row_exists("CONFIGURED") is True


async def test_row_exists_false(core_pool):
    """row_exists() returns False when no row exists."""
    del core_pool
    assert await row_exists("CONFIGURED") is False


async def test_row_exists_no_pool(core_pool):
    """row_exists() returns False when CORE pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        assert await row_exists("CONFIGURED") is False
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


# ---------------------------------------------------------------------------
# delete_row tests
# ---------------------------------------------------------------------------


async def test_delete_row_removes_row(core_pool):
    """delete_row() removes the specified row."""
    del core_pool
    await persist_settings("TEMP_CLIENT", is_current=False)
    assert await row_exists("TEMP_CLIENT") is True

    await delete_row("TEMP_CLIENT")
    assert await row_exists("TEMP_CLIENT") is False


async def test_delete_row_refuses_factory(core_pool):
    """delete_row() refuses to delete the FACTORY row."""
    del core_pool
    await persist_settings("FACTORY", is_current=False)
    assert await row_exists("FACTORY") is True

    await delete_row("FACTORY")
    assert await row_exists("FACTORY") is True


async def test_load_client_settings_empty_table(core_pool):
    """load_client_settings() returns None when no rows exist."""
    del core_pool
    result = await load_client_settings()
    assert result is None


async def test_load_client_settings_no_pool(core_pool):
    """load_client_settings() returns None when CORE pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        result = await load_client_settings()
        assert result is None
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


async def test_delete_row_no_pool(core_pool):
    """delete_row() is a graceful no-op when CORE pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        await delete_row("CONFIGURED")  # Should not raise
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


# ---------------------------------------------------------------------------
# OCI GenAI overlay tests
# ---------------------------------------------------------------------------


async def test_persist_settings_writes_oci_genai_overlay(core_pool):
    """persist_settings() stores only GenAI fields for OCI profiles — no auth material.

    Profiles whose fields match the (empty) file/env baseline contribute no
    delta and are omitted; the user-set DEFAULT profile contributes both fields.
    """
    from pydantic import SecretStr

    from server.app.oci.schemas import OciProfileConfig

    saved_oci = settings.oci_configs[:]
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            tenancy="ocid1.tenancy.oc1..tt",
            fingerprint="aa:bb",
            key_content=SecretStr("SHOULD_NOT_PERSIST"),
            genai_compartment_id="ocid1.compartment.oc1..cc",
            genai_region="us-chicago-1",
        ),
        OciProfileConfig(auth_profile="EMPTY"),
    ]
    try:
        await persist_settings()

        rows = await _read_aio_settings(core_pool)
        raw = rows[0][1]
        data = json.loads(raw) if isinstance(raw, str) else raw

        stored = data.get("oci_genai_overlay")
        assert stored == [
            {
                "auth_profile": "DEFAULT",
                "genai_compartment_id": "ocid1.compartment.oc1..cc",
                "genai_region": "us-chicago-1",
            }
        ]

        raw_str = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        assert "SHOULD_NOT_PERSIST" not in raw_str
        assert "fingerprint" not in raw_str.lower() or "aa:bb" not in raw_str
    finally:
        settings.oci_configs = saved_oci


async def test_persist_omits_source_derived_oci_fields(core_pool):
    """File/env-derived OCI GenAI values that the user never edited are not persisted.

    Without this, a value parsed from ``~/.oci/config`` (or AIO_GENAI_* env) becomes
    sticky in the DB and subsequent edits to the config file are ignored.
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    saved_oci = settings.oci_configs[:]
    saved_baseline = dict(oci_registry._source_baseline)
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..fromfile",
            genai_region="us-ashburn-1",
        ),
    ]
    # Post-load_oci_profiles state: baseline matches the in-memory values, so
    # nothing was ever edited by the user.
    oci_registry._source_baseline = {
        "default": {
            "genai_compartment_id": "ocid1.compartment.oc1..fromfile",
            "genai_region": "us-ashburn-1",
        },
    }
    try:
        await persist_settings()
        rows = await _read_aio_settings(core_pool)
        raw = rows[0][1]
        data = json.loads(raw) if isinstance(raw, str) else raw
        assert data.get("oci_genai_overlay") == []
    finally:
        settings.oci_configs = saved_oci
        oci_registry._source_baseline = saved_baseline


async def test_persist_then_load_oci_overlay_round_trips_explicit_clear(core_pool):
    """Round-trip: persisting a profile with cleared GenAI fields yields ``None`` entries on reload.

    This is what makes a UI-initiated clear durable across restarts even when
    ``~/.oci/config`` still contains values for the same profile.
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    del core_pool
    saved_oci = settings.oci_configs[:]
    saved_baseline = dict(oci_registry._source_baseline)
    # Baseline reflects what was parsed from the config file; in-memory is the
    # user's cleared state.
    oci_registry._source_baseline = {
        "default": {
            "genai_compartment_id": "ocid1.compartment.oc1..fromfile",
            "genai_region": "us-ashburn-1",
        }
    }
    settings.oci_configs = [OciProfileConfig(auth_profile="DEFAULT")]
    try:
        await persist_settings()
        overlay = await load_oci_genai_overlay()
        assert overlay == {
            "default": {"genai_compartment_id": None, "genai_region": None}
        }
    finally:
        settings.oci_configs = saved_oci
        oci_registry._source_baseline = saved_baseline


async def test_load_oci_genai_overlay_returns_persisted_values(core_pool):
    """load_oci_genai_overlay() returns a casefold-keyed dict from the persisted row."""
    from server.app.oci.schemas import OciProfileConfig

    del core_pool
    saved_oci = settings.oci_configs[:]
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="Production",
            genai_compartment_id="ocid1.compartment.oc1..prod",
            genai_region="us-chicago-1",
        ),
    ]
    try:
        await persist_settings()
        overlay = await load_oci_genai_overlay()
        assert overlay == {
            "production": {
                "genai_compartment_id": "ocid1.compartment.oc1..prod",
                "genai_region": "us-chicago-1",
            }
        }
    finally:
        settings.oci_configs = saved_oci


async def test_persist_touched_field_reverting_to_baseline_removes_override(core_pool):
    """A field the user explicitly set back to baseline must remove the override.

    Distinct from the env-masking case (untouched field, in-memory equals
    baseline → carry forward): when ``oci_user_touched`` says the user *did*
    touch the field, "current == baseline" means "revert" and the prior overlay
    must be dropped.
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    saved_oci = settings.oci_configs[:]
    oci_registry._source_baseline.update(
        {
            "default": {
                "genai_compartment_id": "ocid1.compartment.oc1..A",
                "genai_region": "us-ashburn-1",
            }
        }
    )
    # Run 1: user sets compartment=B (overrides file value A).
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..B",
            genai_region="us-ashburn-1",
        ),
    ]
    try:
        await persist_settings()

        # Run 2: user PUTs compartment back to A (the baseline).
        settings.oci_configs[0].genai_compartment_id = "ocid1.compartment.oc1..A"
        await persist_settings(oci_user_touched={"DEFAULT": {"genai_compartment_id"}})

        rows = await _read_aio_settings(core_pool)
        raw = rows[0][1]
        data = json.loads(raw) if isinstance(raw, str) else raw
        assert data.get("oci_genai_overlay") == []
    finally:
        settings.oci_configs = saved_oci


async def test_persist_touched_clear_with_baseline_none_removes_override(core_pool):
    """User-touched explicit None when baseline is also None removes the override.

    The user previously set a value (overlay has it); user now clears it. The
    file baseline is None, so post-clear in-memory == baseline. ``touched``
    tells persist this is a revert, not silent matching.
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    saved_oci = settings.oci_configs[:]
    oci_registry._source_baseline.update(
        {"default": {"genai_compartment_id": None, "genai_region": None}}
    )
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..B",
            genai_region=None,
        ),
    ]
    try:
        await persist_settings()
        settings.oci_configs[0].genai_compartment_id = None
        await persist_settings(oci_user_touched={"DEFAULT": {"genai_compartment_id"}})

        rows = await _read_aio_settings(core_pool)
        raw = rows[0][1]
        data = json.loads(raw) if isinstance(raw, str) else raw
        assert data.get("oci_genai_overlay") == []
    finally:
        settings.oci_configs = saved_oci


async def test_persist_does_not_prune_when_env_matches_saved_overlay(core_pool):
    """Env values are transient — pruning when env happens to equal the saved
    overlay would erase the user's saved GenAI value once env is unset.
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    saved_oci = settings.oci_configs[:]
    saved_env_comp = settings.genai_compartment_id
    settings.genai_compartment_id = None
    # Run 1: no env, file=A, user persists override B.
    oci_registry._source_baseline.update(
        {
            "default": {
                "genai_compartment_id": "ocid1.compartment.oc1..A",
                "genai_region": None,
            }
        }
    )
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..B",
        ),
    ]
    try:
        await persist_settings()

        # Run 2: env now masks compartment with the same value as the saved
        # overlay. Baseline reflects env (B), in-memory is B, carry is B.
        settings.genai_compartment_id = "ocid1.compartment.oc1..B"
        oci_registry._source_baseline.clear()
        oci_registry._source_baseline.update(
            {
                "default": {
                    "genai_compartment_id": "ocid1.compartment.oc1..B",
                    "genai_region": None,
                }
            }
        )
        settings.oci_configs = [
            OciProfileConfig(
                auth_profile="DEFAULT",
                genai_compartment_id="ocid1.compartment.oc1..B",
            ),
        ]
        await persist_settings()

        rows = await _read_aio_settings(core_pool)
        raw = rows[0][1]
        data = json.loads(raw) if isinstance(raw, str) else raw
        assert data.get("oci_genai_overlay") == [
            {
                "auth_profile": "DEFAULT",
                "genai_compartment_id": "ocid1.compartment.oc1..B",
            }
        ]
    finally:
        settings.oci_configs = saved_oci
        settings.genai_compartment_id = saved_env_comp


async def test_persist_prunes_overlay_when_baseline_catches_up(core_pool):
    """A carry-forward value that now equals the *file* baseline must be dropped.

    Scenario: user previously set ``compartment=B`` (overlay row has B); the
    user then adds ``compartment=B`` to ``~/.oci/config``. Next restart's
    baseline is B and in-memory is B with no env override. The override is
    now redundant — if persist re-writes it, a later file edit (B → C) would
    be masked.
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    saved_oci = settings.oci_configs[:]
    saved_env_comp = settings.genai_compartment_id
    saved_env_region = settings.genai_region
    settings.genai_compartment_id = None
    settings.genai_region = None
    # Run 1: user override lands in the DB while file said A.
    oci_registry._source_baseline.update(
        {
            "default": {
                "genai_compartment_id": "ocid1.compartment.oc1..A",
                "genai_region": None,
            }
        }
    )
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..B",
            genai_region=None,
        ),
    ]
    try:
        await persist_settings()

        # Run 2: file now contains B; baseline matches in-memory.
        oci_registry._source_baseline.clear()
        oci_registry._source_baseline.update(
            {
                "default": {
                    "genai_compartment_id": "ocid1.compartment.oc1..B",
                    "genai_region": None,
                }
            }
        )
        settings.oci_configs = [
            OciProfileConfig(
                auth_profile="DEFAULT",
                genai_compartment_id="ocid1.compartment.oc1..B",
                genai_region=None,
            ),
        ]
        await persist_settings()

        rows = await _read_aio_settings(core_pool)
        raw = rows[0][1]
        data = json.loads(raw) if isinstance(raw, str) else raw
        # Override pruned — DB no longer masks future file edits.
        assert data.get("oci_genai_overlay") == []
    finally:
        settings.oci_configs = saved_oci
        settings.genai_compartment_id = saved_env_comp
        settings.genai_region = saved_env_region


async def test_persist_preserves_prior_overlay_when_env_masks_user_value(core_pool):
    """Env-override at startup must not erase a previously persisted user edit.

    Scenario: a prior UI edit wrote ``compartment=B`` to the DB.  On the next
    restart, ``AIO_GENAI_COMPARTMENT_ID=X`` is exported, so
    ``apply_env_overrides`` puts X on all profiles and the baseline snapshot is
    also X.  In-memory now equals baseline, so the delta-only persist would
    otherwise drop the field — overwriting the row and losing B.
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    saved_oci = settings.oci_configs[:]
    # Run 1: user edit lands in the DB.
    oci_registry._source_baseline.update(
        {
            "default": {
                "genai_compartment_id": "ocid1.compartment.oc1..A",
                "genai_region": "us-ashburn-1",
            }
        }
    )
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..B",
            genai_region="us-ashburn-1",
        ),
    ]
    try:
        await persist_settings()

        # Run 2: env override active; baseline reflects env, in-memory matches.
        oci_registry._source_baseline.clear()
        oci_registry._source_baseline.update(
            {
                "default": {
                    "genai_compartment_id": "ocid1.compartment.oc1..X",
                    "genai_region": "us-ashburn-1",
                }
            }
        )
        settings.oci_configs = [
            OciProfileConfig(
                auth_profile="DEFAULT",
                genai_compartment_id="ocid1.compartment.oc1..X",
                genai_region="us-ashburn-1",
            ),
        ]
        await persist_settings()

        rows = await _read_aio_settings(core_pool)
        raw = rows[0][1]
        data = json.loads(raw) if isinstance(raw, str) else raw
        assert data.get("oci_genai_overlay") == [
            {
                "auth_profile": "DEFAULT",
                "genai_compartment_id": "ocid1.compartment.oc1..B",
            }
        ]
    finally:
        settings.oci_configs = saved_oci


async def test_load_settings_returns_none_for_non_object_payload(core_pool):
    """A malformed CONFIGURED row containing valid JSON that isn't an object
    must not crash startup — it should fall back to "no persisted settings".
    """
    import oracledb

    async with core_pool.pool.acquire() as conn:
        await execute_sql(
            conn,
            _UPSERT_SQL,
            {"client": "CONFIGURED", "settings": [1, 2, 3], "is_current": 1},
            input_sizes={"settings": oracledb.DB_TYPE_JSON},
        )
        await conn.commit()

    result = await load_settings()
    assert result is None


async def test_load_settings_does_not_expose_sparse_oci_overlay(core_pool):
    """``load_settings()`` must not return delta-only OCI entries as full profiles.

    Generic callers (e.g. ``POST /settings``) dump the result; partial overlay
    entries would surface as fake ``OciProfileConfig`` objects with everything
    but ``auth_profile`` / GenAI fields defaulted.
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    del core_pool
    saved_oci = settings.oci_configs[:]
    oci_registry._source_baseline.update(
        {
            "default": {
                "genai_compartment_id": "ocid1.compartment.oc1..A",
                "genai_region": "us-ashburn-1",
            }
        }
    )
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            tenancy="ocid1.tenancy.oc1..real",
            genai_compartment_id="ocid1.compartment.oc1..B",
            genai_region="us-ashburn-1",
        ),
    ]
    try:
        await persist_settings()

        result = await load_settings()
        assert result is not None
        assert result.oci_configs == []
    finally:
        settings.oci_configs = saved_oci


async def test_load_oci_genai_overlay_preserves_omitted_fields(core_pool):
    """Loader must not materialize fields that were omitted from the persisted entry.

    Required so that ``load_oci_profiles`` can tell ``"the DB has no opinion on
    this field"`` (key absent → keep file value) from ``"the DB says null"``
    (key present with null → override file value).
    """
    from server.app.oci import registry as oci_registry
    from server.app.oci.schemas import OciProfileConfig

    del core_pool
    saved_oci = settings.oci_configs[:]
    # Baseline mirrors compartment but leaves region as None → only region is a delta.
    oci_registry._source_baseline.update(
        {
            "default": {
                "genai_compartment_id": "ocid1.compartment.oc1..baseline",
                "genai_region": None,
            }
        }
    )
    settings.oci_configs = [
        OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..baseline",
            genai_region="us-chicago-1",
        ),
    ]
    try:
        await persist_settings()
        overlay = await load_oci_genai_overlay()
        assert overlay == {"default": {"genai_region": "us-chicago-1"}}
    finally:
        settings.oci_configs = saved_oci


async def test_load_oci_genai_overlay_no_pool(core_pool):
    """load_oci_genai_overlay() returns an empty dict when the pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        result = await load_oci_genai_overlay()
        assert result == {}
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable
