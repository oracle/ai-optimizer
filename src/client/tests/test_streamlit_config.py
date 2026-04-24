"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Regression gates for the committed Streamlit config at client/app/.streamlit/config.toml.
"""
# spell-checker: disable

import tomllib
from pathlib import Path

STREAMLIT_CONFIG = (
    Path(__file__).resolve().parent.parent / "app" / ".streamlit" / "config.toml"
)


class TestStreamlitConfigIntegrity:
    """Regression gates for src/client/app/.streamlit/config.toml."""

    def test_config_file_exists(self):
        """The committed Streamlit config must exist so the other assertions are meaningful."""
        assert STREAMLIT_CONFIG.is_file()

    def test_no_committed_cookie_secret(self):
        """server.cookieSecret must not be baked into source control.

        Streamlit uses this value to sign XSRF tokens. A committed secret makes the
        signing key public and lets any attacker forge valid XSRF tokens for every
        deployment that doesn't override it. The runtime entrypoint supplies a
        per-instance value via STREAMLIT_SERVER_COOKIE_SECRET instead.
        """
        with STREAMLIT_CONFIG.open("rb") as handle:
            config = tomllib.load(handle)
        server_section = config.get("server", {})
        assert "cookieSecret" not in server_section, (
            "cookieSecret must not be committed to .streamlit/config.toml; "
            "it is injected at runtime by src/entrypoint.py"
        )
