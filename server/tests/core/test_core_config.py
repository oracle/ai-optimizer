"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.core.config Settings.
"""
# spell-checker: disable
# pylint: disable=redefined-outer-name

import importlib
import sys

import pytest
from pydantic import ValidationError

from server.app.core.config import PROJECT_ROOT

CONFIG_MODULE = "server.app.core.config"


def _parse_env_file(app_env: str = "dev") -> dict[str, str]:
    """Read the real .env.<app_env> and return key-value pairs."""
    env_file = PROJECT_ROOT / f".env.{app_env}"
    values = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"')
    return values


@pytest.fixture
def reload_settings(monkeypatch):
    """Reload the config module with a clean environment and optional overrides."""

    def _reload(env_vars: dict | None = None):
        sys.modules.pop(CONFIG_MODULE, None)

        for key in ("AIO_ENV", "AIO_URL_PREFIX", "AIO_PORT", "AIO_LOG_LEVEL",
                     "AIO_API_KEY",
                     "AIO_DB_USERNAME", "AIO_DB_PASSWORD", "AIO_DB_DSN",
                     "AIO_DB_WALLET_PASSWORD", "AIO_DB_WALLET_LOCATION"):
            monkeypatch.delenv(key, raising=False)

        if env_vars:
            for key, value in env_vars.items():
                monkeypatch.setenv(key, value)

        module = importlib.import_module(CONFIG_MODULE)
        return module.Settings()

    return _reload


class TestDefaults:
    """Settings should have sensible defaults when nothing is configured."""

    def test_default_values(self, reload_settings):
        """Verify default settings when no environment is configured."""
        s = reload_settings()
        # Server defaults (not in .env.dev)
        assert s.env == "dev"
        assert s.url_prefix == ""
        assert s.port == 8000
        assert s.log_level == "INFO"
        # DB values come from .env.dev if it exists, otherwise None
        env = _parse_env_file()
        assert s.db_username == env.get("AIO_DB_USERNAME")
        assert s.db_password == env.get("AIO_DB_PASSWORD")
        assert s.db_dsn == env.get("AIO_DB_DSN")
        assert s.db_wallet_password == env.get("AIO_DB_WALLET_PASSWORD")

    def test_unknown_init_kwarg_raises(self, reload_settings):
        """Settings rejects unexpected keyword arguments via extra='forbid'."""
        reload_settings()  # ensure clean module reload
        module = sys.modules[CONFIG_MODULE]
        with pytest.raises(ValidationError):
            module.Settings(bogus="oops")


class TestEnvVars:
    """Settings should be populated from environment variables."""

    def test_server_settings_from_env(self, reload_settings):
        """Verify server settings are read from environment variables."""
        s = reload_settings(env_vars={
            "AIO_URL_PREFIX": "/api",
            "AIO_PORT": "9000",
            "AIO_LOG_LEVEL": "DEBUG",
        })
        assert s.url_prefix == "/api"
        assert s.port == 9000
        assert s.log_level == "DEBUG"

    def test_db_settings_from_env(self, reload_settings):
        """Verify database settings are read from environment variables."""
        s = reload_settings(env_vars={
            "AIO_DB_USERNAME": "admin",
            "AIO_DB_PASSWORD": "secret",
            "AIO_DB_DSN": "//localhost:1521/ORCLPDB1",
            "AIO_DB_WALLET_PASSWORD": "wallet_pass",
        })
        assert s.db_username == "admin"
        assert s.db_password == "secret"
        assert s.db_dsn == "//localhost:1521/ORCLPDB1"
        assert s.db_wallet_password == "wallet_pass"


class TestEnvFile:
    """Settings should load from .env.<AIO_ENV> file."""

    def test_loads_from_env_file(self, reload_settings):
        """Verify settings are populated from the .env.dev file."""
        env = _parse_env_file()
        if not env:
            pytest.skip("No .env.dev file to test")
        s = reload_settings()
        for key, expected in env.items():
            field = key.removeprefix("AIO_").lower()
            assert getattr(s, field) == expected

    def test_env_var_overrides_env_file(self, reload_settings):
        """Verify environment variables take precedence over .env file values."""
        s = reload_settings(
            env_vars={"AIO_LOG_LEVEL": "DEBUG"},
        )
        assert s.log_level == "DEBUG"

    def test_missing_env_file_uses_defaults(self, reload_settings):
        """No .env file present should not raise, just use defaults."""
        s = reload_settings(env_vars={"AIO_ENV": "nonexistent"})
        assert s.port == 8000
        assert s.db_username is None
