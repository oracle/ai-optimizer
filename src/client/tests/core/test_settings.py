"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.core.settings
"""
# spell-checker: disable

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# ClientSettings — field types and explicit values
# ---------------------------------------------------------------------------
class TestClientSettingsFields:
    """Verify field types and that explicitly supplied values stick."""

    def _make(self, **kwargs):
        """Instantiate ClientSettings with env-file loading disabled."""
        from client.app.core.settings import ClientSettings

        # Bypass .env file by providing _env_file=None
        return ClientSettings(_env_file=None, **kwargs)  # type: ignore[call-arg]

    def test_api_key_none_by_default(self, monkeypatch):
        """Default api_key is None when env var is absent."""
        monkeypatch.delenv("AIO_API_KEY", raising=False)
        s = self._make()
        assert s.api_key is None

    def test_api_key_accepts_string(self):
        """Explicit string api_key is preserved."""
        s = self._make(api_key="my-secret")
        assert s.api_key == "my-secret"

    def test_server_url_default(self):
        """Default server_url is http://localhost."""
        s = self._make()
        assert s.server_url == "http://localhost"

    def test_server_url_explicit(self):
        """Explicit server_url overrides the default."""
        s = self._make(server_url="https://example.com")
        assert s.server_url == "https://example.com"

    def test_server_port_default(self):
        """Default server_port is 8000."""
        s = self._make()
        assert s.server_port == 8000

    def test_server_port_explicit(self):
        """Explicit server_port overrides the default."""
        s = self._make(server_port=9000)
        assert s.server_port == 9000

    def test_server_url_prefix_default(self):
        """Default server_url_prefix is empty string."""
        s = self._make()
        assert s.server_url_prefix == ""

    def test_client_address_default(self):
        """Default client_address is localhost."""
        s = self._make()
        assert s.client_address == "localhost"

    def test_client_port_default(self):
        """Default client_port is 8501."""
        s = self._make()
        assert s.client_port == 8501

    def test_client_url_prefix_default(self):
        """Default client_url_prefix is empty string."""
        s = self._make()
        assert s.client_url_prefix == ""


# ---------------------------------------------------------------------------
# _normalize_url_prefix validator
# ---------------------------------------------------------------------------
class TestNormalizeUrlPrefix:
    """Tests for the ``server_url_prefix`` field validator."""

    def _make(self, prefix):
        from client.app.core.settings import ClientSettings

        return ClientSettings(_env_file=None, server_url_prefix=prefix)  # type: ignore[call-arg]

    def test_empty_string_unchanged(self):
        """Empty string passes through unchanged."""
        assert self._make("").server_url_prefix == ""

    def test_trailing_slash_stripped(self):
        """Trailing slash is removed."""
        assert self._make("/api/").server_url_prefix == "/api"

    def test_missing_leading_slash_added(self):
        """Leading slash is prepended when missing."""
        assert self._make("api").server_url_prefix == "/api"

    def test_whitespace_stripped(self):
        """Surrounding whitespace is stripped."""
        assert self._make("  /api  ").server_url_prefix == "/api"

    def test_already_correct(self):
        """Already-correct prefix is unchanged."""
        assert self._make("/v2").server_url_prefix == "/v2"

    def test_multiple_trailing_slashes(self):
        """Multiple trailing slashes are all removed."""
        assert self._make("/api///").server_url_prefix == "/api"


# ---------------------------------------------------------------------------
# Module-level ``settings`` singleton
# ---------------------------------------------------------------------------
class TestSettingsSingleton:
    """Verify the module-level ``settings`` object exists and is correct type."""

    def test_singleton_is_client_settings_instance(self):
        """Module-level settings is a ClientSettings instance."""
        from client.app.core.settings import ClientSettings, settings

        assert isinstance(settings, ClientSettings)
