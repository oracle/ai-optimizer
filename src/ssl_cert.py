"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Self-signed certificate generation and resolution for optional TLS.

Both the launcher (``entrypoint``) and the client autostart path either use
operator-provided cert/key files or fall back to an auto-generated self-signed
pair. The resolution lives here so neither caller re-implements it and the
client tree does not need to import the launcher module.
"""

import datetime
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


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
