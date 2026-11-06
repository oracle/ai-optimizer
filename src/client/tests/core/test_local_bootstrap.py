"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for local CORE bootstrap configuration.
"""

import json
import stat
from pathlib import Path

import pytest
from pydantic import SecretStr

from client.app.core.local_bootstrap import (
    LocalCoreConfig,
    LocalCoreConfigurationError,
    LocalCoreSource,
    load_saved_local_core,
    local_core_config_path,
    persist_local_core,
    resolve_local_core,
)

pytestmark = pytest.mark.unit
PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _config() -> LocalCoreConfig:
    return LocalCoreConfig(
        username="AI_OPTIMIZER",
        password=SecretStr("secret"),
        dsn="localhost:1521/FREEPDB1",
    )


def test_environment_configuration_precedes_session_memory():
    environment = {
        "DB_USERNAME": "environment-user",
        "DB_PASSWORD": "environment-password",
        "DB_DSN": "environment-dsn",
    }

    resolved = resolve_local_core(environment, _config())

    assert resolved.source is LocalCoreSource.ENVIRONMENT
    assert resolved.config is not None
    assert resolved.config.username == "environment-user"
    assert resolved.config.password.get_secret_value() == "environment-password"


def test_db_environment_names_precede_aio_names():
    environment = {
        "DB_USERNAME": "db-user",
        "DB_PASSWORD": "db-password",
        "DB_DSN": "db-dsn",
        "AIO_DB_USERNAME": "aio-user",
        "AIO_DB_PASSWORD": "aio-password",
        "AIO_DB_DSN": "aio-dsn",
    }

    resolved = resolve_local_core(environment)

    assert resolved.config is not None
    assert resolved.config.child_environment() == {
        "AIO_DB_USERNAME": "db-user",
        "AIO_DB_PASSWORD": "db-password",
        "AIO_DB_DSN": "db-dsn",
    }


def test_incomplete_environment_is_rejected():
    with pytest.raises(LocalCoreConfigurationError, match="password, dsn"):
        resolve_local_core({"AIO_DB_USERNAME": "AI_OPTIMIZER"})


def test_missing_configuration_is_reported():
    resolved = resolve_local_core({})

    assert resolved.source is LocalCoreSource.MISSING
    assert resolved.config is None


def test_session_memory_configuration_is_resolved():
    config = _config()

    resolved = resolve_local_core({}, config)

    assert resolved.source is LocalCoreSource.MEMORY
    assert resolved.config is config


def test_container_configuration_round_trip_is_owner_only(tmp_path):
    path = tmp_path / "config" / "core.json"

    persist_local_core(_config(), path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert list(path.parent.glob(".core-*.tmp")) == []
    loaded = load_saved_local_core(path)
    assert loaded.username == "AI_OPTIMIZER"
    assert loaded.password.get_secret_value() == "secret"
    assert loaded.dsn == "localhost:1521/FREEPDB1"


def test_explicit_container_storage_is_resolved(tmp_path):
    path = tmp_path / "core.json"
    persist_local_core(_config(), path)

    resolved = resolve_local_core({"AIO_LOCAL_CONFIG_DIR": str(tmp_path)})

    assert resolved.source is LocalCoreSource.SAVED
    assert resolved.config == _config()


def test_password_whitespace_is_preserved():
    config = LocalCoreConfig(username=" AI_OPTIMIZER ", password=SecretStr(" secret "), dsn=" database ")

    assert config.username == "AI_OPTIMIZER"
    assert config.password.get_secret_value() == " secret "
    assert config.dsn == "database"


def test_container_configuration_rejects_broad_permissions(tmp_path):
    path = tmp_path / "core.json"
    path.write_text(json.dumps(_config().persisted_payload()), encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(LocalCoreConfigurationError, match="0600"):
        load_saved_local_core(path)


def test_bare_metal_has_no_local_config_path():
    assert local_core_config_path({}) is None
    assert local_core_config_path({"XDG_CONFIG_HOME": "/tmp/config"}) is None


def test_container_config_path_requires_explicit_directory(tmp_path):
    assert local_core_config_path({"AIO_LOCAL_CONFIG_DIR": str(tmp_path)}) == tmp_path / "core.json"


def test_all_in_one_image_provides_container_config_storage():
    dockerfile = (PROJECT_ROOT / "src" / "Dockerfile").read_text(encoding="utf-8")

    assert "AIO_LOCAL_CONFIG_DIR=/app/data" in dockerfile
    assert 'VOLUME ["/app/data"]' in dockerfile


def test_server_only_image_does_not_enable_local_bootstrap():
    dockerfile = (PROJECT_ROOT / "src" / "server" / "Dockerfile").read_text(encoding="utf-8")

    assert "AIO_LOCAL_CONFIG_DIR" not in dockerfile
