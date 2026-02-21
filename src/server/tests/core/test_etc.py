"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.core.etc — configuration file loading and overlay logic.
"""
# pylint: disable=redefined-outer-name

import json
from pathlib import Path

import pytest

from server.app.core.settings import SettingsBase, settings
from server.app.core.etc import apply_overlay, load_config_file
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
        "client_disable_testbed": settings.client_disable_testbed,
        "database_configs": list(settings.database_configs),
        "model_configs": list(settings.model_configs),
        "oci_profile_configs": list(settings.oci_profile_configs),
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


def test_load_config_file_tracks_model_fields_set(tmp_path):
    """Only fields present in the JSON appear in model_fields_set."""
    cfg = tmp_path / "configuration.json"
    cfg.write_text(json.dumps({"log_level": "DEBUG"}), encoding="utf-8")

    result = load_config_file(cfg)

    assert result is not None
    assert "log_level" in result.model_fields_set
    assert "server_port" not in result.model_fields_set


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
    source = SettingsBase.model_validate({
        "database_configs": [
            {"alias": "CORE", "dsn": "file_dsn"},
            {"alias": "ANALYTICS", "dsn": "analytics_dsn"},
        ]
    })

    apply_overlay(source, protected=set())

    aliases = [db.alias for db in settings.database_configs]
    assert aliases == ["CORE", "ANALYTICS"]


def test_merge_database_configs_existing_wins():
    """Existing database items are not replaced."""
    settings.database_configs = [DatabaseConfig(alias="CORE", dsn="env_dsn")]
    source = SettingsBase.model_validate({
        "database_configs": [{"alias": "CORE", "dsn": "file_dsn"}]
    })

    apply_overlay(source, protected=set())

    assert len(settings.database_configs) == 1
    assert settings.database_configs[0].dsn == "env_dsn"


def test_merge_model_configs_by_id():
    """Model configs are merged by id when not excluded."""
    settings.model_configs = [ModelConfig(id="existing", type="ll", provider="openai")]
    source = SettingsBase.model_validate({
        "model_configs": [
            {"id": "existing", "type": "ll", "provider": "new_provider"},
            {"id": "new_model", "type": "embed", "provider": "ollama"},
        ]
    })

    apply_overlay(source, protected=set())

    ids = [m.id for m in settings.model_configs]
    assert ids == ["existing", "new_model"]
    assert settings.model_configs[0].provider == "openai"


def test_merge_oci_profiles_by_auth_profile():
    """OCI profiles are merged by auth_profile."""
    settings.oci_profile_configs = [OciProfileConfig(auth_profile="DEFAULT")]
    source = SettingsBase.model_validate({
        "oci_profile_configs": [
            {"auth_profile": "DEFAULT", "region": "file_region"},
            {"auth_profile": "PROD", "region": "us-phoenix-1"},
        ]
    })

    apply_overlay(source, protected=set())

    profiles = [p.auth_profile for p in settings.oci_profile_configs]
    assert profiles == ["DEFAULT", "PROD"]
    assert settings.oci_profile_configs[0].region is None


# ---------------------------------------------------------------------------
# apply_overlay — exclude_fields
# ---------------------------------------------------------------------------


def test_apply_overlay_exclude_fields():
    """Excluded fields are skipped entirely."""
    settings.log_level = "INFO"
    settings.model_configs = []
    settings.oci_profile_configs = []
    excl = {"model_configs", "oci_profile_configs"}
    source = SettingsBase.model_validate({
        "log_level": "DEBUG",
        "model_configs": [{"id": "m1", "type": "ll", "provider": "openai"}],
        "oci_profile_configs": [{"auth_profile": "TEST"}],
    })

    result = apply_overlay(source, protected=set(), exclude_fields=excl)

    assert settings.log_level == "DEBUG"           # not excluded, applied
    assert settings.model_configs == []            # excluded, untouched
    assert settings.oci_profile_configs == []      # excluded, untouched
    assert "model_configs" in result               # still added to protected set
    assert "oci_profile_configs" in result


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
    excl = {"model_configs", "oci_profile_configs"}

    # Config file provides log_level (should be skipped) and server_port + new DB
    config_source = SettingsBase.model_validate({
        "log_level": "DEBUG",
        "server_port": 9000,
        "database_configs": [
            {"alias": "CORE", "dsn": "file_dsn"},
            {"alias": "ANALYTICS", "dsn": "analytics_dsn"},
        ],
    })
    protected = apply_overlay(config_source, env_protected, exclude_fields=excl)

    assert settings.log_level == "INFO"       # env wins
    assert settings.server_port == 9000       # config file applied
    assert len(settings.database_configs) == 2
    assert settings.database_configs[0].dsn == "env_dsn"  # env CORE wins

    # DB provides log_level, server_port (both should be skipped) and new DB
    db_source = SettingsBase.model_validate({
        "log_level": "ERROR",
        "server_port": 7000,
        "client_disable_testbed": True,
        "database_configs": [
            {"alias": "ANALYTICS", "dsn": "db_analytics"},
            {"alias": "REPORTING", "dsn": "reporting_dsn"},
        ],
    })
    apply_overlay(db_source, protected, exclude_fields=excl)

    assert settings.log_level == "INFO"       # env still wins
    assert settings.server_port == 9000       # config file wins over DB
    assert settings.client_disable_testbed is True  # DB applied (new field)
    aliases = [db.alias for db in settings.database_configs]
    assert aliases == ["CORE", "ANALYTICS", "REPORTING"]
    assert settings.database_configs[1].dsn == "analytics_dsn"  # config file ANALYTICS wins
