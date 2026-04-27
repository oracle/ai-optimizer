"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for the `ClientId` Pydantic type — pin the pattern semantics so
future changes to the rule set are deliberate.
"""
# spell-checker: disable

import pytest
from pydantic import TypeAdapter, ValidationError

from server.app.api.v1.schemas.common import ClientId

_VALIDATOR = TypeAdapter(ClientId)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "server",
        "CONFIGURED",
        "FACTORY",
        "550e8400-e29b-41d4-a716-446655440000",
        "team.alpha",
        "alice@example.com",
        "alice+dev@example.com",
        "user.name+tag@host",
        "team:blue",
        "my-client_01",
        "client#hash",
        "client?query",
        "a$b!c*d",
        "a",  # single character
        "a" * 255,
    ],
)
def test_client_id_accepts(value):
    assert _VALIDATOR.validate_python(value) == value


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "",  # min_length
        ".",  # bare dot component
        "..",  # bare traversal component
        "/abs/path",  # contains path separator
        "../../up/file",
        "client/../etc",
        "client\\with\\backslash",  # Windows-style separator
        "client\nnewline",
        "client withspace",
        "\tindented",
        "trailing ",
        "client\x00nullbyte",
        "café",  # non-ASCII (Unicode normalization footgun)
        "a" * 256,
    ],
)
def test_client_id_rejects(value):
    with pytest.raises(ValidationError):
        _VALIDATOR.validate_python(value)
