"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Local CORE configuration for client-managed all-in-one startup.
"""

import json
import os
import stat
import tempfile
from enum import Enum
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, Field, SecretStr, field_validator


class LocalCoreConfigurationError(ValueError):
    """Raised when local CORE configuration cannot be used safely."""


class IncompleteLocalCoreEnvironment(LocalCoreConfigurationError):
    """Raised when deployment environment variables partially define CORE."""


class LocalCoreSource(Enum):
    MISSING = "missing"
    ENVIRONMENT = "environment"
    SAVED = "saved"


class LocalCoreConfig(BaseModel):
    """CORE credentials supplied to a locally spawned server."""

    username: str = Field(min_length=1)
    password: SecretStr
    dsn: str = Field(min_length=1)
    wallet_password: SecretStr | None = None
    wallet_location: str | None = None

    @field_validator("username", "wallet_location", mode="before")
    @classmethod
    def _normalize_single_line_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(character in value for character in ("\n", "\r", "\x00")):
            raise ValueError("must not contain control characters")
        return value.strip()

    @field_validator("dsn", mode="before")
    @classmethod
    def _normalize_dsn(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("must not contain NUL")
        return value.strip()

    @field_validator("password", "wallet_password")
    @classmethod
    def _require_nonempty_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value():
            raise ValueError("must not be empty")
        return value

    def child_environment(self) -> dict[str, str]:
        """Return AIO settings for a local server child process."""
        environment = {
            "AIO_DB_USERNAME": self.username,
            "AIO_DB_PASSWORD": self.password.get_secret_value(),
            "AIO_DB_DSN": self.dsn,
        }
        if self.wallet_password is not None:
            environment["AIO_DB_WALLET_PASSWORD"] = self.wallet_password.get_secret_value()
        if self.wallet_location:
            environment["AIO_DB_WALLET_LOCATION"] = self.wallet_location
        return environment

    def persisted_payload(self) -> dict[str, str]:
        """Return the JSON payload written to the protected local file."""
        payload = {
            "username": self.username,
            "password": self.password.get_secret_value(),
            "dsn": self.dsn,
        }
        if self.wallet_password is not None:
            payload["wallet_password"] = self.wallet_password.get_secret_value()
        if self.wallet_location:
            payload["wallet_location"] = self.wallet_location
        return payload


class ResolvedLocalCore(BaseModel):
    """Resolved local configuration and its ownership source."""

    config: LocalCoreConfig | None
    source: LocalCoreSource


def local_core_config_path(environ: Mapping[str, str] = os.environ) -> Path:
    """Return the protected local CORE configuration path."""
    configured_dir = environ.get("AIO_LOCAL_CONFIG_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser() / "core.json"
    xdg_config = environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(xdg_config).expanduser() if xdg_config else Path.home() / ".config"
    return root / "ai-optimizer" / "core.json"


def _environment_config(environ: Mapping[str, str]) -> LocalCoreConfig | None:
    values = {
        "username": environ.get("DB_USERNAME") or environ.get("AIO_DB_USERNAME"),
        "password": environ.get("DB_PASSWORD") or environ.get("AIO_DB_PASSWORD"),
        "dsn": environ.get("DB_DSN") or environ.get("AIO_DB_DSN"),
        "wallet_password": environ.get("DB_WALLET_PASSWORD") or environ.get("AIO_DB_WALLET_PASSWORD"),
        "wallet_location": environ.get("DB_WALLET_LOCATION") or environ.get("AIO_DB_WALLET_LOCATION"),
    }
    required = ("username", "password", "dsn")
    present = [key for key in required if values[key]]
    if not present:
        return None
    missing = [key for key in required if not values[key]]
    if missing:
        names = ", ".join(missing)
        raise IncompleteLocalCoreEnvironment(f"CORE environment configuration is incomplete; missing {names}")
    return LocalCoreConfig.model_validate(values)


def load_saved_local_core(path: Path) -> LocalCoreConfig:
    """Load a protected local CORE configuration file."""
    try:
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise LocalCoreConfigurationError(f"Local CORE configuration permissions must be 0600: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return LocalCoreConfig.model_validate(payload)
    except LocalCoreConfigurationError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise LocalCoreConfigurationError(f"Local CORE configuration is invalid: {path}") from exc


def resolve_local_core(
    environ: Mapping[str, str] = os.environ,
    path: Path | None = None,
) -> ResolvedLocalCore:
    """Resolve environment configuration before the saved local file."""
    environment_config = _environment_config(environ)
    if environment_config is not None:
        return ResolvedLocalCore(config=environment_config, source=LocalCoreSource.ENVIRONMENT)

    config_path = path or local_core_config_path(environ)
    if config_path.is_file():
        return ResolvedLocalCore(config=load_saved_local_core(config_path), source=LocalCoreSource.SAVED)
    return ResolvedLocalCore(config=None, source=LocalCoreSource.MISSING)


def persist_local_core(config: LocalCoreConfig, path: Path | None = None) -> Path:
    """Atomically save CORE credentials with owner-only permissions."""
    config_path = path or local_core_config_path()
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".core-",
            suffix=".tmp",
            dir=config_path.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            json.dump(config.persisted_payload(), stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, config_path)
        if os.name != "nt":
            config_path.chmod(0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return config_path
