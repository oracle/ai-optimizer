"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Internal helpers shared across v1 endpoint modules.
"""

from logging import Logger
from typing import Any

from fastapi import Request
from pydantic import BaseModel, SecretStr


def _is_blank_secret(v: Any) -> bool:
    """True when *v* is an empty / None secret value.

    Used by update handlers to skip overwriting an existing value when the
    client submits a blank value.
    """
    if v is None or v == "":
        return True
    return isinstance(v, SecretStr) and not v.get_secret_value()


def _build_updates(body: BaseModel, secret_fields: frozenset[str]) -> dict[str, Any]:
    """Build the field→value dict to apply for a PUT update body.

    Reads attributes directly from *body* (no ``model_dump``) so SecretStr
    fields flow through as SecretStr. Drops keys in *secret_fields* whose
    submitted value is blank.
    """
    return {
        field: getattr(body, field)
        for field in body.model_fields_set
        if not (field in secret_fields and _is_blank_secret(getattr(body, field)))
    }


def _log_sensitive_read(logger: Logger, resource: str, resource_id: str, request: Request) -> None:
    """Emit the audit line for an explicit single-resource read."""
    logger.info(
        "configuration read: %s/%s (remote=%s)",
        resource,
        resource_id,
        request.client.host if request.client else "unknown",
    )
