#!/usr/bin/env python3
"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Container / CLI entrypoint — configures the environment and launches the server (uvicorn) or client (streamlit).
"""
# spell-checker: ignore streamlit sslcertfile sslkeyfile

import json
import os
import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from net_addressing import ensure_ssl_cert


def setup_pythonpath(script_dir: Path) -> None:
    """Prepend the src/ directory to PYTHONPATH so module imports resolve."""
    current = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(script_dir) + (":" + current if current else "")


def load_env_file(script_dir: Path) -> None:
    """Load .env.{AIO_ENV} variables without overwriting existing environment variables.

    Pod / container env vars always take precedence over values in the .env file.
    """
    env_name = os.environ.get("AIO_ENV", "dev")
    env_file = script_dir / f".env.{env_name}"
    if env_file.is_file():
        load_dotenv(env_file, override=False)


def prepare_oci_config() -> None:
    """Copy a read-only OCI config mount to a writable location and rewrite key_file paths."""
    oci_dir = Path("/app/.oci")
    oci_runtime_dir = Path("/app/runtime/.oci")
    config_file = oci_dir / "config"

    if not config_file.is_file():
        return

    print(f"Found OCI Config file in: {oci_dir}; preparing writable copy in {oci_runtime_dir}")
    shutil.copytree(oci_dir, oci_runtime_dir, dirs_exist_ok=True)

    runtime_config = oci_runtime_dir / "config"
    content = runtime_config.read_text(encoding="utf-8")
    content = re.sub(
        r"^(key_file\s*=\s*)(.+)$",
        lambda m: m.group(1) + str(oci_runtime_dir / Path(m.group(2).strip()).name),
        content,
        flags=re.MULTILINE,
    )
    runtime_config.write_text(content, encoding="utf-8")

    os.environ["OCI_CLI_CONFIG_FILE"] = str(runtime_config)


def detect_component(script_dir: Path, arg: str) -> str:
    """Determine whether to start 'server' or 'client' from a CLI arg or directory structure."""
    if arg:
        return arg
    # Docker images remove the unused component directory
    if (script_dir / "server").is_dir() and not (script_dir / "client").is_dir():
        return "server"
    return "client"


def start_server(script_dir: Path) -> None:
    """Launch the FastAPI server over HTTPS."""
    print("Starting Optimizer Server")
    args = [
        "uvicorn",
        "server.app.main:app",
        "--host",
        os.environ.get("AIO_SERVER_ADDRESS", "0.0.0.0"),
        "--port",
        os.environ.get("AIO_SERVER_PORT", "8000"),
    ]

    cert, key = ensure_ssl_cert(script_dir, "AIO_SERVER_SSL_CERT_FILE", "AIO_SERVER_SSL_KEY_FILE")
    args.extend(["--ssl-certfile", str(cert), "--ssl-keyfile", str(key)])

    os.execvp("uvicorn", args)


def start_client(script_dir: Path) -> None:
    """Launch the Streamlit client over HTTPS."""
    print("Starting Optimizer Client")
    prepare_streamlit_authentication()
    args = [sys.executable, "-m", "client.app.web"]

    # server.cookieSecret is marked sensitive=True in Streamlit and is read
    # through its env var. Promote AIO_CLIENT_COOKIE_SECRET into
    # STREAMLIT_SERVER_COOKIE_SECRET so the value is inherited by execvp
    # without adding it to argv. If AIO var is unset, let Streamlit's own
    # per-process default handle the single-replica case.
    cookie_secret = os.environ.get("AIO_CLIENT_COOKIE_SECRET", "")
    if cookie_secret:
        os.environ["STREAMLIT_SERVER_COOKIE_SECRET"] = cookie_secret

    cert, key = ensure_ssl_cert(script_dir, "AIO_CLIENT_SSL_CERT_FILE", "AIO_CLIENT_SSL_KEY_FILE")
    os.environ["AIO_CLIENT_SSL_CERT_FILE"] = str(cert)
    os.environ["AIO_CLIENT_SSL_KEY_FILE"] = str(key)

    os.execvp(sys.executable, args)


def prepare_streamlit_authentication() -> None:
    """Write Streamlit's OIDC configuration from the client environment."""
    names = {
        "issuer": "AIO_OIDC_ISSUER",
        "client_id": "AIO_OIDC_CLIENT_ID",
        "client_secret": "AIO_OIDC_CLIENT_SECRET",
        "redirect_uri": "AIO_OIDC_REDIRECT_URI",
        "cookie_secret": "AIO_CLIENT_COOKIE_SECRET",
    }
    values = {name: os.environ.get(environment_name, "") for name, environment_name in names.items()}
    if not any(values[name] for name in ("issuer", "client_id", "client_secret", "redirect_uri")):
        return
    missing = [names[name] for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"OIDC client configuration is incomplete; missing {', '.join(missing)}")
    try:
        required_scopes = json.loads(os.environ.get("AIO_OIDC_REQUIRED_SCOPES", "[]"))
    except json.JSONDecodeError as exc:
        raise ValueError("AIO_OIDC_REQUIRED_SCOPES must be a JSON array") from exc
    if not isinstance(required_scopes, list) or not all(isinstance(scope, str) for scope in required_scopes):
        raise ValueError("AIO_OIDC_REQUIRED_SCOPES must be a JSON array of strings")
    scopes = " ".join(dict.fromkeys(["openid", "profile", "email", *required_scopes]))
    metadata_url = f"{values['issuer'].rstrip('/')}/.well-known/openid-configuration"
    content = "\n".join(
        (
            "[auth]",
            f"redirect_uri = {json.dumps(values['redirect_uri'])}",
            f"cookie_secret = {json.dumps(values['cookie_secret'])}",
            'expose_tokens = "access"',
            f"client_id = {json.dumps(values['client_id'])}",
            f"client_secret = {json.dumps(values['client_secret'])}",
            f"server_metadata_url = {json.dumps(metadata_url)}",
            f"client_kwargs = {{ scope = {json.dumps(scopes)} }}",
            "",
        )
    )
    secrets_file = Path.home() / ".streamlit" / "secrets.toml"
    secrets_file.parent.mkdir(parents=True, exist_ok=True)
    secrets_file.write_text(content, encoding="utf-8")
    secrets_file.chmod(0o600)


def setup_authentication() -> None:
    """Run the idempotent authentication authority setup command."""
    os.execvp(sys.executable, [sys.executable, "-m", "server.app.auth.setup"])


def main() -> None:
    """Configure the environment and launch the appropriate component."""
    script_dir = Path(__file__).resolve().parent
    setup_pythonpath(script_dir)
    load_env_file(script_dir)
    prepare_oci_config()

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    component = detect_component(script_dir, arg)

    if component == "server":
        start_server(script_dir)
    elif component == "client":
        start_client(script_dir)
    elif component == "auth-setup":
        setup_authentication()
    else:
        print("Usage: entrypoint.py [client|server|auth-setup]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
