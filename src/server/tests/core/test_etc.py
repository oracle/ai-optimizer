"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.core.etc — configuration file loading and overlay logic.
"""
# spell-checker: disable

import json

import pytest

from server.app.core.etc import apply_overlay, load_config_file, migrate_legacy_settings, upsert_list_field
from server.app.core.settings import SettingsBase, settings
from server.app.database.schemas import DatabaseConfig
from server.app.models.schemas import ModelConfig
from server.app.oci.schemas import OciProfileConfig

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_settings():
    """Save and restore settings state around each test."""
    saved = {
        "log_level": settings.log_level,
        "server_port": settings.server_port,
        "api_key": settings.api_key,
        "database_configs": list(settings.database_configs),
        "model_configs": list(settings.model_configs),
        "oci_configs": list(settings.oci_configs),
        "_api_key_generated": getattr(settings, "_api_key_generated", False),
    }
    yield
    for k, v in saved.items():
        if k.startswith("_"):
            object.__setattr__(settings, k, v)
        else:
            setattr(settings, k, v)


# ---------------------------------------------------------------------------
# load_config_file
# ---------------------------------------------------------------------------


def test_load_config_file_valid(tmp_path):
    """A valid JSON file returns a SettingsBase instance."""
    cfg = tmp_path / "configuration.json"
    cfg.write_text(json.dumps({"log_level": "DEBUG"}), encoding="utf-8")

    result = load_config_file(cfg)

    assert isinstance(result, SettingsBase)
    assert result.log_level == "DEBUG"


def test_load_config_file_missing(tmp_path):
    """A missing file returns None."""
    result = load_config_file(tmp_path / "no_such_file.json")
    assert result is None


def test_load_config_file_invalid_json(tmp_path):
    """Malformed JSON returns None."""
    cfg = tmp_path / "configuration.json"
    cfg.write_text("{ not valid json }", encoding="utf-8")

    result = load_config_file(cfg)
    assert result is None


def test_load_config_file_schema_mismatch(tmp_path):
    """Invalid field types return None."""
    cfg = tmp_path / "configuration.json"
    cfg.write_text(json.dumps({"server_port": "not_a_number"}), encoding="utf-8")

    result = load_config_file(cfg)
    assert result is None


def test_load_config_file_accepts_legacy_v203_shape(tmp_path):
    """A v2.0.3-shaped configuration.json is migrated and loads successfully."""
    cfg = tmp_path / "configuration.json"
    cfg.write_text(
        json.dumps(
            {
                "database_configs": [
                    {"name": "DEFAULT", "user": "admin", "dsn": "//host/svc"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = load_config_file(cfg)

    assert isinstance(result, SettingsBase)
    assert len(result.database_configs) == 1
    assert result.database_configs[0].alias == "DEFAULT"
    assert result.database_configs[0].username == "admin"
    assert result.database_configs[0].dsn == "//host/svc"


def test_load_config_file_tracks_model_fields_set(tmp_path):
    """Only fields present in the JSON appear in model_fields_set."""
    cfg = tmp_path / "configuration.json"
    cfg.write_text(json.dumps({"log_level": "DEBUG"}), encoding="utf-8")

    result = load_config_file(cfg)

    assert result is not None
    assert "log_level" in result.model_fields_set
    assert "server_port" not in result.model_fields_set


# ---------------------------------------------------------------------------
# migrate_legacy_settings
# ---------------------------------------------------------------------------


def test_migrate_legacy_settings_renames_database_fields():
    """v2.0.3 name/user fields are renamed to 2.1 alias/username."""
    legacy = {
        "database_configs": [
            {"name": "DEFAULT", "user": "admin", "dsn": "//host/svc"},
            {"name": "ANALYTICS", "user": "ro_user"},
        ]
    }

    migrated = migrate_legacy_settings(legacy)

    assert migrated["database_configs"][0] == {
        "alias": "DEFAULT",
        "username": "admin",
        "dsn": "//host/svc",
    }
    assert migrated["database_configs"][1] == {"alias": "ANALYTICS", "username": "ro_user"}


def test_migrate_legacy_settings_noop_for_current_shape():
    """A 2.1-shaped payload passes through unchanged."""
    current = {
        "database_configs": [{"alias": "CORE", "username": "coreuser", "dsn": "//c/s"}],
        "model_configs": [{"id": "m1", "provider": "openai", "type": "ll"}],
        "oci_configs": [{"auth_profile": "DEFAULT"}],
    }

    migrated = migrate_legacy_settings(current)

    assert migrated == current


def test_migrate_legacy_settings_deep_copies_input():
    """The caller's dict is not mutated."""
    legacy = {"database_configs": [{"name": "DEFAULT", "user": "admin"}]}

    migrate_legacy_settings(legacy)

    assert legacy == {"database_configs": [{"name": "DEFAULT", "user": "admin"}]}


def test_migrate_legacy_settings_preserves_new_fields_when_both_present():
    """If both alias and name are present, alias wins and name is left alone."""
    mixed = {"database_configs": [{"alias": "NEW", "name": "OLD", "username": "u", "user": "legacy"}]}

    migrated = migrate_legacy_settings(mixed)

    assert migrated["database_configs"][0]["alias"] == "NEW"
    assert migrated["database_configs"][0]["username"] == "u"
    # Untouched legacy keys remain — harmless for Pydantic with extras ignored
    assert migrated["database_configs"][0]["name"] == "OLD"
    assert migrated["database_configs"][0]["user"] == "legacy"


def test_migrate_legacy_settings_handles_missing_or_empty_database_configs():
    """No database_configs key, or an empty list, is a no-op."""
    assert migrate_legacy_settings({}) == {}
    assert migrate_legacy_settings({"database_configs": []}) == {"database_configs": []}
    assert migrate_legacy_settings({"database_configs": None}) == {"database_configs": None}


@pytest.mark.parametrize("payload", [[], None, "string", 42, [{"alias": "X"}]])
def test_migrate_legacy_settings_returns_non_dict_unchanged(payload):
    """Non-dict payloads pass through so Pydantic can surface the real validation error."""
    assert migrate_legacy_settings(payload) is payload


def test_load_config_file_non_object_json_returns_none(tmp_path):
    """A JSON file whose top-level value is a list (not an object) returns None, not a crash."""
    cfg = tmp_path / "configuration.json"
    cfg.write_text(json.dumps([{"alias": "X"}]), encoding="utf-8")

    result = load_config_file(cfg)

    assert result is None


# ---------------------------------------------------------------------------
# apply_overlay — scalar fields
# ---------------------------------------------------------------------------


def test_apply_overlay_scalar_not_protected():
    """Unprotected scalar fields are applied from the source."""
    source = SettingsBase.model_validate({"log_level": "DEBUG"})

    apply_overlay(source, protected=set())

    assert settings.log_level == "DEBUG"


def test_apply_overlay_scalar_protected():
    """Protected scalar fields are NOT overridden."""
    settings.log_level = "WARNING"
    source = SettingsBase.model_validate({"log_level": "DEBUG"})

    apply_overlay(source, protected={"log_level"})

    assert settings.log_level == "WARNING"


def test_apply_overlay_returns_updated_protected():
    """Returned set is the union of input protected and source model_fields_set."""
    source = SettingsBase.model_validate({"log_level": "DEBUG", "server_port": 9000})

    result = apply_overlay(source, protected={"env"})

    assert result == {"env", "log_level", "server_port"}


# ---------------------------------------------------------------------------
# apply_overlay — api_key
# ---------------------------------------------------------------------------


def test_apply_overlay_api_key_updates_generated_flag():
    """Overlaying api_key clears the auto-generated flag."""
    object.__setattr__(settings, "_api_key_generated", True)

    source = SettingsBase.model_validate({"api_key": "from_config_file"})
    apply_overlay(source, protected=set())

    assert settings.api_key == "from_config_file"
    assert settings.api_key_generated is False


def test_apply_overlay_api_key_protected():
    """api_key is NOT overridden when protected."""
    settings.api_key = "from_env"
    source = SettingsBase.model_validate({"api_key": "from_config_file"})

    apply_overlay(source, protected={"api_key"})

    assert settings.api_key == "from_env"


# ---------------------------------------------------------------------------
# apply_overlay — list field merging
# ---------------------------------------------------------------------------


def test_merge_database_configs_new_alias():
    """New database aliases are appended."""
    settings.database_configs = [DatabaseConfig(alias="CORE")]
    source = SettingsBase.model_validate(
        {
            "database_configs": [
                {"alias": "CORE", "dsn": "file_dsn"},
                {"alias": "ANALYTICS", "dsn": "analytics_dsn"},
            ]
        }
    )

    apply_overlay(source, protected=set())

    aliases = [db.alias for db in settings.database_configs]
    assert aliases == ["CORE", "ANALYTICS"]


def test_merge_database_configs_existing_wins():
    """Existing database items are not replaced."""
    settings.database_configs = [DatabaseConfig(alias="CORE", dsn="env_dsn")]
    source = SettingsBase.model_validate({"database_configs": [{"alias": "CORE", "dsn": "file_dsn"}]})

    apply_overlay(source, protected=set())

    assert len(settings.database_configs) == 1
    assert settings.database_configs[0].dsn == "env_dsn"


def test_merge_model_configs_by_composite_key():
    """Model configs are merged by (provider, id) composite key."""
    settings.model_configs = [ModelConfig(id="existing", type="ll", provider="openai")]
    source = SettingsBase.model_validate(
        {
            "model_configs": [
                {"id": "existing", "type": "ll", "provider": "openai", "temperature": 0.9},
                {"id": "new_model", "type": "embed", "provider": "ollama"},
            ]
        }
    )

    apply_overlay(source, protected=set())

    ids = [m.id for m in settings.model_configs]
    assert ids == ["existing", "new_model"]
    # Existing wins — temperature is NOT overwritten by incoming 0.9
    assert settings.model_configs[0].provider == "openai"
    assert settings.model_configs[0].temperature == 0.5  # default


def test_merge_oci_profiles_by_auth_profile():
    """OCI profiles are merged by auth_profile."""
    settings.oci_configs = [OciProfileConfig(auth_profile="DEFAULT")]
    source = SettingsBase.model_validate(
        {
            "oci_configs": [
                {"auth_profile": "DEFAULT", "region": "file_region"},
                {"auth_profile": "PROD", "region": "us-phoenix-1"},
            ]
        }
    )

    apply_overlay(source, protected=set())

    profiles = [p.auth_profile for p in settings.oci_configs]
    assert profiles == ["DEFAULT", "PROD"]
    assert settings.oci_configs[0].region is None


# ---------------------------------------------------------------------------
# apply_overlay — exclude_fields
# ---------------------------------------------------------------------------


def test_apply_overlay_exclude_fields():
    """Excluded fields are skipped entirely."""
    settings.log_level = "INFO"
    settings.model_configs = []
    settings.oci_configs = []
    excl = {"model_configs", "oci_configs"}
    source = SettingsBase.model_validate(
        {
            "log_level": "DEBUG",
            "model_configs": [{"id": "m1", "type": "ll", "provider": "openai"}],
            "oci_configs": [{"auth_profile": "TEST"}],
        }
    )

    result = apply_overlay(source, protected=set(), exclude_fields=excl)

    assert settings.log_level == "DEBUG"  # not excluded, applied
    assert not settings.model_configs  # excluded, untouched
    assert not settings.oci_configs  # excluded, untouched
    assert "model_configs" in result  # still added to protected set
    assert "oci_configs" in result


# ---------------------------------------------------------------------------
# Full precedence chain
# ---------------------------------------------------------------------------


def test_full_overlay_chain_precedence():
    """Simulate env -> config file -> DB: higher sources always win.

    model_configs are excluded from overlay (handled separately in lifespan).
    """
    # Initial state: env set log_level and has CORE db
    settings.log_level = "INFO"
    settings.database_configs = [DatabaseConfig(alias="CORE", dsn="env_dsn")]
    env_protected = {"log_level"}
    excl = {"model_configs", "oci_configs"}

    # Config file provides log_level (should be skipped) and server_port + new DB
    config_source = SettingsBase.model_validate(
        {
            "log_level": "DEBUG",
            "server_port": 9000,
            "database_configs": [
                {"alias": "CORE", "dsn": "file_dsn"},
                {"alias": "ANALYTICS", "dsn": "analytics_dsn"},
            ],
        }
    )
    protected = apply_overlay(config_source, env_protected, exclude_fields=excl)

    assert settings.log_level == "INFO"  # env wins
    assert settings.server_port == 9000  # config file applied
    assert len(settings.database_configs) == 2
    assert settings.database_configs[0].dsn == "env_dsn"  # env CORE wins

    # DB provides log_level, server_port (both should be skipped) and new DB
    db_source = SettingsBase.model_validate(
        {
            "log_level": "ERROR",
            "server_port": 7000,
            "database_configs": [
                {"alias": "ANALYTICS", "dsn": "db_analytics"},
                {"alias": "REPORTING", "dsn": "reporting_dsn"},
            ],
        }
    )
    apply_overlay(db_source, protected, exclude_fields=excl)

    assert settings.log_level == "INFO"  # env still wins
    assert settings.server_port == 9000  # config file wins over DB
    aliases = [db.alias for db in settings.database_configs]
    assert aliases == ["CORE", "ANALYTICS", "REPORTING"]
    assert settings.database_configs[1].dsn == "analytics_dsn"  # config file ANALYTICS wins


# ---------------------------------------------------------------------------
# upsert_list_field
# ---------------------------------------------------------------------------


def test_upsert_creates_new_item():
    """An item with a new identity key is appended."""
    settings.database_configs = [DatabaseConfig(alias="CORE")]
    incoming = [DatabaseConfig(alias="NEW_DB", dsn="new_dsn")]

    created, updated = upsert_list_field("database_configs", incoming)

    assert len(created) == 1
    assert len(updated) == 0
    assert created[0].alias == "NEW_DB"
    aliases = [db.alias for db in settings.database_configs]
    assert aliases == ["CORE", "NEW_DB"]


def test_upsert_updates_existing_item():
    """A matching composite key updates fields in-place."""
    settings.model_configs = [ModelConfig(id="m1", type="ll", provider="openai")]
    incoming = [ModelConfig.model_validate({"id": "m1", "type": "ll", "provider": "openai", "enabled": True})]

    created, updated = upsert_list_field("model_configs", incoming)

    assert len(created) == 0
    assert len(updated) == 1
    assert settings.model_configs[0].enabled is True


def test_upsert_case_insensitive_match():
    """Lowercase key matches uppercase existing entry."""
    settings.database_configs = [DatabaseConfig(alias="ANALYTICS")]
    incoming = [DatabaseConfig.model_validate({"alias": "analytics", "dsn": "new_dsn"})]

    created, updated = upsert_list_field("database_configs", incoming)

    assert len(created) == 0
    assert len(updated) == 1
    assert settings.database_configs[0].dsn == "new_dsn"


def test_upsert_preserves_identity_key():
    """The identity key itself is not overwritten by incoming item."""
    settings.database_configs = [DatabaseConfig(alias="ANALYTICS")]
    incoming = [DatabaseConfig.model_validate({"alias": "analytics", "dsn": "new_dsn"})]

    upsert_list_field("database_configs", incoming)

    # Original casing preserved
    assert settings.database_configs[0].alias == "ANALYTICS"


def test_upsert_only_updates_fields_set():
    """Only explicitly provided fields are changed (via model_fields_set)."""
    settings.model_configs = [
        ModelConfig(id="m1", type="ll", provider="openai", temperature=0.5),
    ]
    # Only provide id, provider, and enabled — temperature should remain untouched
    incoming = [ModelConfig.model_validate({"id": "m1", "type": "ll", "provider": "openai", "enabled": True})]

    upsert_list_field("model_configs", incoming)

    assert settings.model_configs[0].enabled is True
    assert settings.model_configs[0].temperature == 0.5


# ---------------------------------------------------------------------------
# Composite key — model_configs uses (provider, id)
# ---------------------------------------------------------------------------


def test_upsert_model_same_id_different_provider_creates():
    """Same model id with different provider creates a new entry."""
    settings.model_configs = [ModelConfig(id="m1", type="ll", provider="openai")]
    incoming = [ModelConfig(id="m1", type="ll", provider="anthropic")]

    created, updated = upsert_list_field("model_configs", incoming)

    assert len(created) == 1
    assert len(updated) == 0
    assert len(settings.model_configs) == 2
    providers = {m.provider for m in settings.model_configs}
    assert providers == {"openai", "anthropic"}


def test_merge_model_same_id_different_provider_appends():
    """During overlay merge, same id with different provider is treated as new."""
    settings.model_configs = [ModelConfig(id="m1", type="ll", provider="openai")]
    source = SettingsBase.model_validate({"model_configs": [{"id": "m1", "type": "ll", "provider": "anthropic"}]})

    apply_overlay(source, protected=set())

    assert len(settings.model_configs) == 2
    providers = {m.provider for m in settings.model_configs}
    assert providers == {"openai", "anthropic"}


def test_upsert_model_composite_key_case_insensitive():
    """Composite key matching is case-insensitive."""
    settings.model_configs = [ModelConfig(id="GPT-4o", type="ll", provider="OpenAI")]
    incoming = [ModelConfig.model_validate({"id": "gpt-4o", "type": "ll", "provider": "openai", "enabled": True})]

    created, updated = upsert_list_field("model_configs", incoming)

    assert len(created) == 0
    assert len(updated) == 1
    assert settings.model_configs[0].enabled is True
    # Original casing preserved
    assert settings.model_configs[0].id == "GPT-4o"
    assert settings.model_configs[0].provider == "OpenAI"
