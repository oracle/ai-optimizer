"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models and dataclasses for database configuration.
"""

from typing import Annotated, Optional

import oracledb
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from server.app.embed.schemas import VectorStoreConfig

# SQLcl's stdin parser treats newline as a command boundary regardless of
# quoting, so a newline in a credential/path field escapes into a new SQLcl
# command. Reject control chars at the schema boundary for fields where
# they have no legitimate use.
_FORBIDDEN_CONTROL_CHARS = frozenset({"\n", "\r", "\x00"})


def _reject_chars(
    value: Optional[str], field_name: Optional[str], forbidden: frozenset[str]
) -> Optional[str]:
    if value is None:
        return value
    bad = sorted({c for c in value if c in forbidden})
    if bad:
        raise ValueError(
            f"{field_name or 'value'} must not contain control characters "
            f"{[repr(c) for c in bad]}"
        )
    return value


def _descriptor_has_linebreak_inside_quote(dsn: str) -> bool:
    """Return True if *dsn* contains a CR or LF inside a double-quoted span."""
    in_quote = False
    for ch in dsn:
        if ch == '"':
            in_quote = not in_quote
        elif in_quote and ch in ("\n", "\r"):
            return True
    return False


# Characters that mark the boundary between tokens inside a connect descriptor.
# A line break adjacent to one of these (after skipping other whitespace) sits
# between tokens rather than inside a value, so the SQLcl-sink flatten is safe.
# Note: `,` is NOT structural — it is value content (e.g. inside an unquoted
# X.500 DN like CN=adb,OU=Oracle), so a line break next to a comma still
# sits inside a value and must be rejected.
_DESCRIPTOR_STRUCTURAL_CHARS = frozenset('()="')


def _descriptor_has_linebreak_inside_unquoted_value(dsn: str) -> bool:
    """Return True if *dsn* has a CR/LF inside an unquoted value token.

    A line break between two value-content characters (e.g.
    ``(HOST=adb\\nhost)`` or ``(MY_WALLET_DIRECTORY=/opt/my\\nwallet)``)
    is inside a value. oracledb and SQLcl parse such inputs differently,
    and the sink-level newline-to-space flatten would silently mutate the
    SQLcl copy of the value. Reject fast at the schema so both paths
    always see the same input.

    Line breaks adjacent to ``(``, ``)``, ``=``, or ``"`` (after skipping
    other whitespace) are considered structural and allowed.
    """
    n = len(dsn)
    in_quote = False
    for i, ch in enumerate(dsn):
        if ch == '"':
            in_quote = not in_quote
            continue
        if in_quote or ch not in "\n\r":
            continue

        # Previous non-whitespace character.
        j = i - 1
        while j >= 0 and dsn[j] in " \t\n\r":
            j -= 1
        prev = dsn[j] if j >= 0 else None

        # Next non-whitespace character.
        k = i + 1
        while k < n and dsn[k] in " \t\n\r":
            k += 1
        nxt = dsn[k] if k < n else None

        if (
            prev is not None
            and nxt is not None
            and prev not in _DESCRIPTOR_STRUCTURAL_CHARS
            and nxt not in _DESCRIPTOR_STRUCTURAL_CHARS
        ):
            return True
    return False


def _validate_dsn(value: Optional[str], field_name: Optional[str]) -> Optional[str]:
    """Validate a DSN: reject NUL; allow line breaks only inside descriptors.

    Oracle connect descriptors (``(DESCRIPTION=...)``) are legitimately
    multi-line (see ``docs/content/help/troubleshooting/_index.md``). Their
    internal whitespace is preserved verbatim because descriptor *values*
    (e.g. ``SSL_SERVER_CERT_DN``, wallet paths) can contain meaningful
    spaces that must not be rewritten.

    Line breaks inside a double-quoted descriptor value are rejected:
    they would diverge the oracledb path (which keeps the newline inside
    the value) from the SQLcl path (whose stdin parser would still break
    on the newline even if we preserved it inside the quote), so such a
    DSN cannot be used reliably. Failing fast at validation is clearer
    than a silent path-dependent connection failure.

    Easy Connect strings and TNS aliases are single-line by construction;
    a line break there is almost always a copy-paste mishap and should
    fail fast rather than be silently reshaped. Outer whitespace is
    trimmed so a trailing newline from clipboard paste does not trip the
    descriptor check.

    Downstream consumers handle descriptor-internal whitespace themselves:
    the retry-token strip in ``database.config`` is quote-aware, and the
    SQLcl proxy collapses CR/LF to spaces at the sink (Oracle ignores
    descriptor whitespace, but SQLcl's stdin parser treats newlines as
    command boundaries).
    """
    if value is None:
        return value
    name = field_name or "value"
    if "\x00" in value:
        raise ValueError(f"{name} must not contain NUL")

    trimmed = value.strip()
    if trimmed.startswith("("):
        if _descriptor_has_linebreak_inside_quote(trimmed):
            raise ValueError(
                f"{name} contains a line break inside a quoted "
                f"descriptor value; remove the line break from the quoted "
                f"value (Oracle ignores descriptor whitespace outside "
                f"quotes, but inside a quote the newline changes the value)"
            )
        if _descriptor_has_linebreak_inside_unquoted_value(trimmed):
            raise ValueError(
                f"{name} contains a line break inside an unquoted "
                f"descriptor value; line breaks are only permitted between "
                f"structural tokens ((, ), =), not inside a value"
            )
        return trimmed
    if "\n" in trimmed or "\r" in trimmed:
        raise ValueError(
            f"{name} contains a line break but is not an Oracle "
            f"connect descriptor; only (DESCRIPTION=...) descriptors may "
            f"span multiple lines"
        )
    return trimmed


class DatabaseSensitive(BaseModel):
    """Sensitive database fields."""

    password: Optional[str] = None
    wallet_password: Optional[str] = None

    @field_validator("password", "wallet_password")
    @classmethod
    def _no_control_chars_sensitive(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        return _reject_chars(v, info.field_name, _FORBIDDEN_CONTROL_CHARS)


class DatabaseConfig(DatabaseSensitive):
    """Database configurations."""

    model_config = {"arbitrary_types_allowed": True}

    alias: str
    username: Optional[str] = None
    dsn: Optional[str] = None
    wallet_location: Optional[str] = None
    config_dir: Optional[str] = None
    tcp_connect_timeout: int = 30
    vector_stores: list[VectorStoreConfig] = Field(
        default=[], description="Vector Storage (read-only)", json_schema_extra={"readOnly": True}
    )
    usable: bool = False
    pool: Annotated[Optional[oracledb.AsyncConnectionPool], Field(exclude=True)] = None

    @field_validator("alias", "username", "wallet_location", "config_dir")
    @classmethod
    def _no_control_chars_config(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        return _reject_chars(v, info.field_name, _FORBIDDEN_CONTROL_CHARS)

    @field_validator("dsn")
    @classmethod
    def _validate_dsn(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        return _validate_dsn(v, info.field_name)


class DatabaseUpdate(DatabaseSensitive):
    """Fields allowed in a database config update (all optional)."""

    username: Optional[str] = None
    dsn: Optional[str] = None
    wallet_location: Optional[str] = None
    config_dir: Optional[str] = None
    tcp_connect_timeout: Optional[int] = None

    @field_validator("username", "wallet_location", "config_dir")
    @classmethod
    def _no_control_chars_update(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        return _reject_chars(v, info.field_name, _FORBIDDEN_CONTROL_CHARS)

    @field_validator("dsn")
    @classmethod
    def _validate_dsn_update(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        return _validate_dsn(v, info.field_name)
