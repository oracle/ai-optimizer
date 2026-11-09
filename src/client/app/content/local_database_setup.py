"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Restricted local Oracle AI Database setup page.
"""

import streamlit as st
from pydantic import SecretStr, ValidationError

from client.app.core.local_bootstrap import LocalCoreConfig


def display_local_database_setup(
    current: LocalCoreConfig | None = None, error: str | None = None
) -> LocalCoreConfig | None:
    """Render the local setup form and return a submitted configuration."""
    st.title("Configure Oracle AI Database")
    st.write("Connect to Oracle AI Database to start the AI Optimizer.")
    st.markdown(
        "For connection requirements and examples, see "
        "[Oracle AI Database](https://oracle.github.io/ai-optimizer/docs/guides/database/)."
    )

    if error:
        st.error(error)

    with st.form("local_core_database_setup"):
        username = st.text_input("Username", value=current.username if current else "AI_OPTIMIZER")
        password = st.text_input("Password", type="password", key="local_core_password")
        dsn = st.text_area("Connection string", value=current.dsn if current else "")
        wallet_location = st.text_input(
            "Wallet location (optional)", value=(current.wallet_location or "") if current else ""
        )
        wallet_password = st.text_input("Wallet password (optional)", type="password", key="local_core_wallet_password")
        submitted = st.form_submit_button("Connect and start", type="primary")

    if not submitted:
        return None
    try:
        return LocalCoreConfig(
            username=username,
            password=SecretStr(password),
            dsn=dsn,
            wallet_location=wallet_location or None,
            wallet_password=SecretStr(wallet_password) if wallet_password else None,
        )
    except ValidationError as exc:
        field_labels = {
            "dsn": "connection string",
            "password": "password",
            "username": "username",
            "wallet_location": "wallet location",
            "wallet_password": "wallet password",
        }
        invalid_fields = {
            field_labels.get(str(validation_error["loc"][0]), str(validation_error["loc"][0]))
            for validation_error in exc.errors()
        }
        st.error(f"Check these database fields: {', '.join(sorted(invalid_fields))}")
        return None
