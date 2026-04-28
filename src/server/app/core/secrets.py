"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Helpers for working with ``SecretStr`` typed fields.
"""

from typing import Annotated, Any, Optional, Union

from pydantic import PlainSerializer, SecretStr, SerializationInfo

# Context-dict key consumed by ``serialize_secret`` for callers that need
# non-default serialization.
REVEAL_KEY = "reveal"

# Sentinel emitted by the field serializer when the reveal context is absent.
# Distinct from ``logging_redaction.REDACTED`` ("<redacted>") because that
# value lives in log lines, while this one mirrors Pydantic's stock
# ``SecretStr`` repr and any code that scans API responses for it.
MASKED_SENTINEL = "**********"


def reveal(v: Union[SecretStr, str, None]) -> Optional[str]:
    """Return the plain string of a ``SecretStr`` (or pass through ``str``).

    Accepting both ``SecretStr`` and plain ``str`` keeps tests, monkeypatches,
    and any transitional call sites working during migration without
    forcing every read site to switch in lockstep.
    """
    if isinstance(v, SecretStr):
        return v.get_secret_value()
    return v


def serialize_secret(v: Union[SecretStr, str, None], info: SerializationInfo) -> Optional[str]:
    """Emit the unmasked value when ``info.context`` carries
    ``{REVEAL_KEY: True}``; otherwise return ``MASKED_SENTINEL``.
    """
    if v is None:
        return None
    if info.context and info.context.get(REVEAL_KEY):
        return v.get_secret_value() if isinstance(v, SecretStr) else v
    return MASKED_SENTINEL


# Single field-type alias used by every sensitive Pydantic field.  Replaces
# the per-schema ``@field_serializer`` boilerplate.
SecretField = Annotated[
    Optional[SecretStr],
    PlainSerializer(serialize_secret, when_used="always"),
]


def coerce_secret_str(v: Any) -> Any:
    """Wrap a plain ``str`` in ``SecretStr``; pass other values through.

    Used by registry override paths that ``setattr`` raw env-var strings
    onto ``SecretStr``-typed fields where assignment validation is off.
    """
    return SecretStr(v) if isinstance(v, str) else v
