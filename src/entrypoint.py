#!/usr/bin/env python3
"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Container / CLI entrypoint — configures the environment and launches the server (uvicorn) or client (streamlit).
"""
# spell-checker: ignore streamlit sslcertfile sslkeyfile

import datetime
import os
import re
import shutil
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from dotenv import load_dotenv


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


def generate_self_signed_cert(cert_path: Path, key_path: Path) -> None:
    """Generate a self-signed RSA-2048 X.509 certificate valid for 365 days (CN=localhost)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def ensure_ssl_cert(script_dir: Path, cert_env: str, key_env: str) -> tuple[Path, Path]:
    """Return (cert_path, key_path), auto-generating a self-signed certificate if neither env var is set."""
    cert_file = os.environ.get(cert_env, "")
    key_file = os.environ.get(key_env, "")
    if cert_file and key_file:
        return Path(cert_file), Path(key_file)

    ssl_dir = script_dir.parent / "tmp" / "ssl"
    ssl_dir.mkdir(parents=True, exist_ok=True)
    cert_path = ssl_dir / "cert.pem"
    key_path = ssl_dir / "key.pem"

    if not cert_path.exists() or not key_path.exists():
        print("Generating self-signed SSL certificate")
        generate_self_signed_cert(cert_path, key_path)

    return cert_path, key_path


def start_server(script_dir: Path) -> None:
    """Launch uvicorn for the FastAPI server, with optional TLS."""
    print("Starting Optimizer Server")
    args = ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", os.environ.get("AIO_SERVER_PORT", "8000")]

    if os.environ.get("AIO_SERVER_SSL", "false").lower() == "true":
        cert, key = ensure_ssl_cert(script_dir, "AIO_SERVER_SSL_CERT_FILE", "AIO_SERVER_SSL_KEY_FILE")
        args.extend(["--ssl-certfile", str(cert), "--ssl-keyfile", str(key)])

    os.execvp("uvicorn", args)


def start_client(script_dir: Path) -> None:
    """Launch streamlit for the client UI, with optional TLS."""
    print("Starting Optimizer Client")
    args = [
        "streamlit",
        "run",
        str(script_dir / "client" / "app" / "main.py"),
        "--server.port",
        os.environ.get("AIO_CLIENT_PORT", "8501"),
        "--server.address",
        os.environ.get("AIO_CLIENT_ADDRESS", "localhost"),
    ]

    if os.environ.get("AIO_CLIENT_SSL", "false").lower() == "true":
        cert, key = ensure_ssl_cert(script_dir, "AIO_CLIENT_SSL_CERT_FILE", "AIO_CLIENT_SSL_KEY_FILE")
        args.extend(["--server.sslCertFile", str(cert), "--server.sslKeyFile", str(key)])

    os.execvp("streamlit", args)


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
    else:
        print("Usage: entrypoint.py [client|server]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
