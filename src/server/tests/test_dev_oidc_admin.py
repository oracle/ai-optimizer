"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for local development OIDC administrative commands.
"""

import pytest

from dev_auth_credentials import BootstrapCredential
from server.app import dev_oidc_admin
from server.tests.constants import test_auth as auth_creds


def test_show_bootstrap_password_prints_locally_generated_credential(monkeypatch, capsys):
    """The retrieval command emits the fixed account and the protected local secret."""
    monkeypatch.setattr(
        dev_oidc_admin,
        "read_bootstrap_credential",
        lambda _path: BootstrapCredential(
            **{
                **auth_creds["oidc_admin"],
                **auth_creds["oidc_bootstrap"],
                **auth_creds["oidc_client"],
            }
        ),
    )

    dev_oidc_admin._show_bootstrap_password()

    bootstrap_creds = {**auth_creds["oidc_admin"], **auth_creds["oidc_bootstrap"]}
    assert capsys.readouterr().out == "".join(f"{field.title()}: {value}\n" for field, value in bootstrap_creds.items())


def test_show_bootstrap_password_fails_when_no_local_credential_exists(monkeypatch):
    """Hashes in the database cannot be used to reconstruct a bootstrap password."""
    monkeypatch.setattr(dev_oidc_admin, "read_bootstrap_credential", lambda _path: None)

    with pytest.raises(RuntimeError, match="No locally generated development bootstrap credential"):
        dev_oidc_admin._show_bootstrap_password()
