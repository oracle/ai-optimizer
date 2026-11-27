"""Authentication defaults for client content tests."""

import pytest

from client.tests.conftest import AttrDict


@pytest.fixture(autouse=True)
def _admin_principal(monkeypatch):
    monkeypatch.setattr(
        "client.app.core.auth.state",
        AttrDict({"auth_token": "test-token", "auth_principal": {"roles": ["admin"]}}),
    )
