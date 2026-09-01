"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for local development OIDC administrative commands.
"""

import pytest

from dev_auth_credentials import BootstrapCredential
from server.app import dev_oidc_admin


def test_show_bootstrap_password_prints_locally_generated_credential(monkeypatch, capsys):
    """The retrieval command emits the fixed account and the protected local secret."""
    monkeypatch.setattr(
        dev_oidc_admin,
        "read_bootstrap_credential",
        lambda _path: BootstrapCredential(
            username="admin@example.test", password="generated-password", web_client_secret="web-client-secret"
        ),
    )

    dev_oidc_admin._show_bootstrap_password()

    assert capsys.readouterr().out == "Username: admin@example.test\nPassword: generated-password\n"


def test_show_bootstrap_password_fails_when_no_local_credential_exists(monkeypatch):
    """Hashes in the database cannot be used to reconstruct a bootstrap password."""
    monkeypatch.setattr(dev_oidc_admin, "read_bootstrap_credential", lambda _path: None)

    with pytest.raises(RuntimeError, match="No locally generated development bootstrap credential"):
        dev_oidc_admin._show_bootstrap_password()
