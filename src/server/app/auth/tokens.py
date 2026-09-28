"""Token, PKCE, password, and signing-key primitives for the auth gateway."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any

import jwt
from authlib.common.security import generate_token
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from server.app.auth.models import PrincipalRecord, SigningKey

_PASSWORD_N = 2**14
_PASSWORD_R = 8
_PASSWORD_P = 1
PKCE_VALUE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


def digest(value: str) -> str:
    """Return the database-safe digest for a secret bearer value."""
    return hashlib.sha256(value.encode()).hexdigest()


def random_token() -> str:
    """Return a high-entropy opaque protocol value."""
    return generate_token(48)


def pkce_challenge(verifier: str) -> str:
    """Return an S256 PKCE challenge."""
    encoded = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def hash_password(password: str) -> str:
    """Hash a local account password using the existing scrypt parameters."""
    salt = generate_token(24).encode()
    derived = hashlib.scrypt(password.encode(), salt=salt, n=_PASSWORD_N, r=_PASSWORD_R, p=_PASSWORD_P)
    return "$".join(
        (
            "scrypt",
            str(_PASSWORD_N),
            str(_PASSWORD_R),
            str(_PASSWORD_P),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(derived).decode(),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify an existing local account scrypt password hash."""
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode(),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(derived, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def generate_signing_key() -> SigningKey:
    """Create the initial RSA signing key for an embedded gateway."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return SigningKey(key_id=f"aio-{random_token()[:16]}", private_key_pem=pem)


def load_rsa_private_key(private_key_pem: bytes) -> rsa.RSAPrivateKey:
    """Load a persisted RSA private key."""
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("Authentication signing key is not RSA")
    return key


def jwks_document(key: SigningKey) -> dict[str, list[dict[str, Any]]]:
    """Return the public JWKS representation of a signing key."""
    public_jwk = json.loads(RSAAlgorithm.to_jwk(load_rsa_private_key(key.private_key_pem).public_key()))
    public_jwk.update({"kid": key.key_id, "use": "sig", "alg": "RS256"})
    return {"keys": [public_jwk]}


def issue_id_token(
    *, issuer: str, client_id: str, principal: PrincipalRecord, nonce: str, signing_key: SigningKey, lifetime: int
) -> str:
    """Sign the ID token consumed by Streamlit and downstream OIDC clients."""
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": issuer,
        "sub": principal.principal_id,
        "aud": client_id,
        "iat": now,
        "exp": now + lifetime,
        "nonce": nonce,
        "name": principal.display_name,
    }
    if principal.email:
        claims.update({"email": principal.email, "email_verified": True})
    return jwt.encode(
        claims,
        load_rsa_private_key(signing_key.private_key_pem),
        algorithm="RS256",
        headers={"kid": signing_key.key_id},
    )
