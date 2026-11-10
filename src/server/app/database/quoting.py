"""Validated quoting for Oracle DDL values that cannot use bind variables."""

import re

_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,127}")


def quote_identifier(name: str, *, upper: bool = True) -> str:
    if not isinstance(name, str) or _IDENTIFIER_RE.fullmatch(name) is None:
        raise ValueError(f"Invalid identifier: {name!r}")
    return '"' + (name.upper() if upper else name) + '"'


def quote_password(value: str) -> str:
    if not value or any(character in value for character in "\x00\n\r"):
        raise ValueError("Invalid password")
    return '"' + value.replace('"', '""') + '"'
