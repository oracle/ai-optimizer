"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server.app.main (lifespan and _apply_configured_overlay).
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.core.settings import settings

MODULE = "server.app.main"

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_model_configs():
    """Save and restore settings.model_configs around each test."""
    saved = list(settings.model_configs)
    yield
    settings.model_configs = saved


# ---------------------------------------------------------------------------
# _apply_configured_overlay
# ---------------------------------------------------------------------------


class TestApplyConfiguredOverlay:
    """Tests for _apply_configured_overlay."""

    async def test_overlay_from_config_file(self):
        """Config file source should apply overlay and persist."""
        source = MagicMock()
        source.model_fields_set = {"model_configs"}
        source.model_configs = [MagicMock()]
        source.prompt_configs = []

        with (
            patch(f"{MODULE}.load_config_file", return_value=source),
            patch(f"{MODULE}.row_exists", new_callable=AsyncMock),
            patch(f"{MODULE}.apply_overlay") as mock_overlay,
            patch(f"{MODULE}.apply_env_overrides"),
            patch(f"{MODULE}.reconcile_prompt_customizations"),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock) as mock_persist,
        ):
            from server.app.main import _apply_configured_overlay

            await _apply_configured_overlay(set())

        mock_overlay.assert_called_once()
        mock_persist.assert_awaited_once_with("CONFIGURED", is_current=True)

    async def test_overlay_from_database(self):
        """Database source should be used when no config file exists."""
        source = MagicMock()
        source.model_configs = []
        source.prompt_configs = []

        with (
            patch(f"{MODULE}.load_config_file", return_value=None),
            patch(f"{MODULE}.row_exists", new_callable=AsyncMock, return_value=True),
            patch(f"{MODULE}.load_settings", new_callable=AsyncMock, return_value=source) as mock_load,
            patch(f"{MODULE}.apply_overlay") as mock_overlay,
            patch(f"{MODULE}.reconcile_prompt_customizations"),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock),
        ):
            from server.app.main import _apply_configured_overlay

            await _apply_configured_overlay(set())

        mock_load.assert_awaited_once_with("CONFIGURED")
        mock_overlay.assert_called_once()

    async def test_overlay_no_source(self):
        """When no source exists, persist_settings should still be called."""
        with (
            patch(f"{MODULE}.load_config_file", return_value=None),
            patch(f"{MODULE}.row_exists", new_callable=AsyncMock, return_value=False),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock) as mock_persist,
        ):
            from server.app.main import _apply_configured_overlay

            await _apply_configured_overlay(set())

        mock_persist.assert_awaited_once_with("CONFIGURED", is_current=True)


# ---------------------------------------------------------------------------
# lifespan
# ---------------------------------------------------------------------------


class TestLifespan:
    """Tests for the FastAPI lifespan context manager."""

    async def test_core_db_failure_continues(self):
        """CORE database init failure should be logged but not crash the app."""
        mock_db = MagicMock()
        with (
            patch(f"{MODULE}.get_database_settings", return_value=mock_db),
            patch(f"{MODULE}.init_core_database", new_callable=AsyncMock, side_effect=Exception("db down")),
            patch(f"{MODULE}.load_default_models", new_callable=AsyncMock),
            patch(f"{MODULE}.apply_env_overrides"),
            patch(f"{MODULE}.load_factory_prompts"),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock),
            patch(f"{MODULE}._apply_configured_overlay", new_callable=AsyncMock),
            patch(f"{MODULE}.load_client_settings", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.persist_client_settings", new_callable=AsyncMock),
            patch(f"{MODULE}.load_oci_profiles", new_callable=AsyncMock),
            patch(f"{MODULE}.load_ollama_models", new_callable=AsyncMock),
            patch(f"{MODULE}.register_mcp_prompts"),
            patch(f"{MODULE}.register_mcp_tools"),
            patch(f"{MODULE}.register_sqlcl_proxy", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.check_model_reachability", new_callable=AsyncMock),
            patch(f"{MODULE}.close_sqlcl_proxy", new_callable=AsyncMock),
            patch(f"{MODULE}.close_pool", new_callable=AsyncMock),
        ):
            from server.app.main import lifespan

            async with lifespan(MagicMock()):
                pass  # lifespan should yield without error

    async def test_cleanup_on_exit(self):
        """Exiting lifespan should call close_sqlcl_proxy and close_pool."""
        mock_transport = MagicMock()
        saved_db_configs = list(settings.database_configs)
        with (
            patch(f"{MODULE}.get_database_settings", return_value=MagicMock()),
            patch(f"{MODULE}.init_core_database", new_callable=AsyncMock),
            patch(f"{MODULE}.load_default_models", new_callable=AsyncMock),
            patch(f"{MODULE}.apply_env_overrides"),
            patch(f"{MODULE}.load_factory_prompts"),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock),
            patch(f"{MODULE}._apply_configured_overlay", new_callable=AsyncMock),
            patch(f"{MODULE}.load_client_settings", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.persist_client_settings", new_callable=AsyncMock),
            patch(f"{MODULE}.load_oci_profiles", new_callable=AsyncMock),
            patch(f"{MODULE}.load_ollama_models", new_callable=AsyncMock),
            patch(f"{MODULE}.register_mcp_prompts"),
            patch(f"{MODULE}.register_mcp_tools"),
            patch(f"{MODULE}.register_sqlcl_proxy", new_callable=AsyncMock, return_value=mock_transport),
            patch(f"{MODULE}.check_model_reachability", new_callable=AsyncMock),
            patch(f"{MODULE}.close_sqlcl_proxy", new_callable=AsyncMock) as mock_close_sqlcl,
            patch(f"{MODULE}.close_pool", new_callable=AsyncMock) as mock_close_pool,
        ):
            from server.app.main import lifespan

            async with lifespan(MagicMock()):
                pass

            mock_close_sqlcl.assert_awaited_once_with(mock_transport)
            # close_pool called once per database config
            assert mock_close_pool.await_count == len(saved_db_configs)
