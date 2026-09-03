"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Private local storage for All-In-One development IdP bootstrap credentials.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

_CREDENTIAL_FILE_NAME = "dev-oidc-bootstrap.json"
_WEB_CLIENT_SECRET_FILE_NAME = "dev-oidc-web-client-secret"
_STREAMLIT_CONFIG_DIR = Path("client") / "app" / ".streamlit"


@dataclass(frozen=True, slots=True)
class BootstrapCredential:
    """One locally generated administrator credential."""

    username: str
    password: str
    web_client_secret: str


def bootstrap_credential_path(script_dir: Path) -> Path:
    """Return the owner-only credential path for a local source installation."""
    return script_dir / _STREAMLIT_CONFIG_DIR / _CREDENTIAL_FILE_NAME


def _web_client_secret_path(script_dir: Path) -> Path:
    return script_dir / _STREAMLIT_CONFIG_DIR / _WEB_CLIENT_SECRET_FILE_NAME


def read_bootstrap_credential(script_dir: Path) -> BootstrapCredential | None:
    """Read a locally generated bootstrap credential without consulting the database."""
    path = bootstrap_credential_path(script_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        username = raw["username"]
        password = raw["password"]
        web_client_secret = raw.get("web_client_secret")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Invalid development bootstrap credential file: {path}") from exc
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        raise ValueError(f"Invalid development bootstrap credential file: {path}")
    if web_client_secret is not None and (not isinstance(web_client_secret, str) or not web_client_secret):
        raise ValueError(f"Invalid development bootstrap credential file: {path}")
    path.chmod(0o600)
    return BootstrapCredential(username=username, password=password, web_client_secret=web_client_secret or "")


def load_or_create_bootstrap_credential(script_dir: Path) -> BootstrapCredential:
    """Return the durable generated credential, creating it with private permissions."""
    existing = read_bootstrap_credential(script_dir)
    if existing is not None and existing.web_client_secret:
        return existing

    path = bootstrap_credential_path(script_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    credential = BootstrapCredential(
        username="admin@example.test",
        password=existing.password if existing is not None else secrets.token_urlsafe(32),
        web_client_secret=secrets.token_urlsafe(32),
    )
    payload = json.dumps(
        {
            "username": credential.username,
            "password": credential.password,
            "web_client_secret": credential.web_client_secret,
        }
    )
    if existing is not None:
        path.write_text(payload, encoding="utf-8")
        path.chmod(0o600)
        return credential
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raced = read_bootstrap_credential(script_dir)
        if raced is None:  # pragma: no cover - filesystem race guard
            raise RuntimeError(f"Development bootstrap credential disappeared: {path}")
        return raced
    with os.fdopen(descriptor, "w", encoding="utf-8") as credential_file:
        credential_file.write(payload)
    return credential


def load_or_create_web_client_secret(script_dir: Path, fallback: str = "") -> str:
    """Return one durable web-client secret without persisting an operator password."""
    path = _web_client_secret_path(script_dir)
    if path.is_file():
        secret = path.read_text(encoding="utf-8").strip()
        if secret:
            path.chmod(0o600)
            return secret
        raise ValueError(f"Invalid development web-client secret file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    secret = fallback or secrets.token_urlsafe(32)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return load_or_create_web_client_secret(script_dir)
    with os.fdopen(descriptor, "w", encoding="utf-8") as secret_file:
        secret_file.write(secret)
    return secret
