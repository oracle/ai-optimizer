"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared schema primitives used across v1 endpoints.
"""

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

# Deny-list targeting exactly the F6 threat model (bug 39236183): any
# character that alters filesystem path semantics or injects into logs.
# The pattern accepts every printable ASCII byte (0x21–0x7E) and the
# AfterValidator then rejects path separators and bare dot-components.
# Everything else — `:`, `+`, `#`, `?`, `$`, `!`, etc. — is allowed so
# that identifiers persisted by the unconstrained v2.1 API (DB column is
# VARCHAR2(255)) stay reachable across the upgrade.
#
# Rejected:
#   * whitespace (space, tab, newline, CR, FF, VT) and control chars
#   * the DEL byte and all non-ASCII (Unicode normalization footgun)
#   * `/` and `\` (path separators)
#   * bare `.` and `..` (path-component escape)
#   * empty string and anything > 255 chars (DB column width)
#
# StringConstraints (not Field) is used here so the pattern is enforced
# when FastAPI resolves Header/Query parameters — Field metadata is only
# read for BaseModel fields.
_CLIENT_ID_PATTERN = r"^[\x21-\x7e]{1,255}$"


def _reject_path_semantics(value: str) -> str:
    if value in (".", ".."):
        raise ValueError("client id cannot be '.' or '..'")
    if "/" in value or "\\" in value:
        raise ValueError("client id cannot contain path separators")
    return value


ClientId = Annotated[
    str,
    StringConstraints(pattern=_CLIENT_ID_PATTERN, min_length=1, max_length=255),
    AfterValidator(_reject_path_semantics),
]
