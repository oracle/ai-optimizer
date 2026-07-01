"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared networking and TLS helpers for the API Server bind/connect distinction.

A bind address (what uvicorn listens on) is not always a usable client target:
wildcard binds such as ``0.0.0.0`` / ``::`` accept connections but cannot be
dialed. These helpers translate bind addresses into connectable hosts, build
IPv6-aware netloc strings, decide when the configured service port belongs in a
URL, and select TLS verification for loopback self-signed certificates — and
generate/resolve those self-signed certificates for optional local TLS.

It lives at the top level so both the client and server trees can import it
(mirrors ``url_safety``); neither tree is guaranteed to be present at runtime.
"""

import datetime
import os
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Wildcard bind addresses mapped to the loopback host used to reach them.
WILDCARD_TO_LOOPBACK = {
    "0.0.0.0": "127.0.0.1",
    "::": "::1",
    "0:0:0:0:0:0:0:0": "::1",
}
# Wildcard bind hosts (listen-on-all); usable for binding, not for connecting.
WILDCARD_HOSTS = frozenset(WILDCARD_TO_LOOPBACK)
# Every host that denotes the local machine: loopback plus wildcard binds.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"}) | WILDCARD_HOSTS
# In-cluster Kubernetes service DNS suffixes that resolve to the app server.
K8S_SERVICE_SUFFIXES = (".svc", ".svc.cluster.local")


def connect_host(host: str | None) -> str:
    """Return a dialable host for a bind/configured host.

    Wildcard bind addresses are useful for listening, but they are not stable
    client targets. Convert only those wildcard values to loopback; leave DNS
    names and concrete IPs untouched so normal resolver behavior applies.
    """
    raw = (host or "").strip()
    normalized = raw.strip("[]").casefold()
    return WILDCARD_TO_LOOPBACK.get(normalized, raw or "127.0.0.1")


def netloc(host: str, port: int | None) -> str:
    """Build a ``host[:port]`` netloc, bracketing bare IPv6 literals."""
    bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{bracketed}:{port}" if port else bracketed


def should_inject_server_port(parsed_hostname: str | None, connect_target: str) -> bool:
    """Return True when the configured service port should be part of the URL.

    External URLs without an explicit port should keep their scheme default
    (e.g. HTTPS -> 443). Local/all-in-one URLs and Kubernetes service DNS
    names use the app server's configured service port.
    """
    host = (parsed_hostname or connect_target).strip("[]").casefold()
    return host in LOCAL_HOSTS or host.endswith(K8S_SERVICE_SUFFIXES)


def verify_for_url(url: str) -> bool:
    """Return whether httpx should verify TLS certificates for *url*.

    The all-in-one local server can run with an auto-generated self-signed
    certificate. Disable verification only for loopback HTTPS targets; keep
    normal certificate verification for every external HTTPS endpoint.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return True
    host = (parsed.hostname or "").strip("[]").casefold()
    return host not in LOCAL_HOSTS


# --- Self-signed certificate generation/resolution for optional local TLS ---
# Both the launcher (``entrypoint``) and the client autostart path either use
# operator-provided cert/key files or fall back to an auto-generated self-signed pair.


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


def resolve_or_generate_cert(cert_file: str, key_file: str, script_dir: Path) -> tuple[Path, Path]:
    """Return ``(cert_path, key_path)``.

    Use *cert_file*/*key_file* when both are provided; otherwise auto-generate a
    self-signed certificate under ``<script_dir>/../tmp/ssl`` (generated once and
    reused on subsequent calls).
    """
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


def ensure_ssl_cert(script_dir: Path, cert_env: str, key_env: str) -> tuple[Path, Path]:
    """Resolve cert/key from environment variable names, generating when unset."""
    return resolve_or_generate_cert(os.environ.get(cert_env, ""), os.environ.get(key_env, ""), script_dir)
