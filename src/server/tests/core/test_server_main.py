"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server.app.main (lifespan and _apply_configured_overlay).
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.core.settings import SettingsBase, settings
from server.app.database.schemas import DatabaseConfig

MODULE = "server.app.main"

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_settings_state():
    """Save and restore settings state around each test."""
    saved_models = list(settings.model_configs)
    saved_dbs = list(settings.database_configs)
    saved_cs = settings.client_settings.model_copy(deep=True)
    yield
    settings.model_configs = saved_models
    settings.database_configs = saved_dbs
    settings.client_settings = saved_cs


# ---------------------------------------------------------------------------
# _apply_configured_overlay
# ---------------------------------------------------------------------------


class TestApplyConfiguredOverlay:
    """Tests for _apply_configured_overlay."""

    async def test_overlay_from_config_file(self):
        """Config file source should apply overlay (persist happens later in lifespan)."""
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
        mock_persist.assert_not_awaited()

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

    async def test_overlay_no_source_does_not_persist(self):
        """No source means no in-memory changes; persist is deferred to lifespan."""
        with (
            patch(f"{MODULE}.load_config_file", return_value=None),
            patch(f"{MODULE}.row_exists", new_callable=AsyncMock, return_value=False),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock) as mock_persist,
        ):
            from server.app.main import _apply_configured_overlay

            await _apply_configured_overlay(set())

        mock_persist.assert_not_awaited()

    async def test_overlay_promotes_first_db_to_core_when_no_core(self):
        """When no CORE exists, the first DB is promoted to CORE and clients are synced."""
        settings.database_configs = []
        settings.client_settings.database.alias = "DEFAULT"
        source = SettingsBase.model_validate({"database_configs": [{"alias": "DEFAULT", "dsn": "//host/svc"}]})

        with (
            patch(f"{MODULE}.load_config_file", return_value=source),
            patch(f"{MODULE}.row_exists", new_callable=AsyncMock),
            patch(f"{MODULE}.reconcile_prompt_customizations"),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock),
        ):
            from server.app.main import _apply_configured_overlay

            await _apply_configured_overlay(set())

        assert settings.database_configs[0].alias == "CORE"
        assert settings.database_configs[0].dsn == "//host/svc"
        assert settings.client_settings.database.alias == "CORE"

    async def test_overlay_no_promotion_when_core_exists(self):
        """When CORE already exists, the source DB alias is not changed."""
        settings.database_configs = [DatabaseConfig(alias="CORE")]
        source = SettingsBase.model_validate({"database_configs": [{"alias": "DEFAULT", "dsn": "//host/svc"}]})

        with (
            patch(f"{MODULE}.load_config_file", return_value=source),
            patch(f"{MODULE}.row_exists", new_callable=AsyncMock),
            patch(f"{MODULE}.reconcile_prompt_customizations"),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock),
        ):
            from server.app.main import _apply_configured_overlay

            await _apply_configured_overlay(set())

        aliases = [db.alias for db in settings.database_configs]
        assert "CORE" in aliases
        assert "DEFAULT" in aliases

    async def test_overlay_normalizes_lowercase_core(self):
        """A lowercase 'core' alias from config file is normalized to exact 'CORE'."""
        settings.database_configs = []
        source = SettingsBase.model_validate({"database_configs": [{"alias": "core", "dsn": "//host/svc"}]})

        with (
            patch(f"{MODULE}.load_config_file", return_value=source),
            patch(f"{MODULE}.row_exists", new_callable=AsyncMock),
            patch(f"{MODULE}.reconcile_prompt_customizations"),
            patch(f"{MODULE}.persist_settings", new_callable=AsyncMock),
        ):
            from server.app.main import _apply_configured_overlay

            await _apply_configured_overlay(set())

        assert settings.database_configs[0].alias == "CORE"
        assert settings.database_configs[0].dsn == "//host/svc"


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

    async def test_configured_persist_runs_after_load_oci_profiles(self):
        """Regression: persisting CONFIGURED before OCI load erases the saved GenAI overlay.

        load_oci_profiles() is what populates settings.oci_configs and applies the
        persisted overlay; the CONFIGURED row must be rewritten only afterwards.
        """
        call_order: list[str] = []

        async def _track_oci():
            call_order.append("load_oci_profiles")

        async def _track_persist(client, is_current=True):
            del is_current
            call_order.append(f"persist_settings:{client}")

        with (
            patch(f"{MODULE}.get_database_settings", return_value=MagicMock()),
            patch(f"{MODULE}.init_core_database", new_callable=AsyncMock),
            patch(f"{MODULE}.load_default_models", new_callable=AsyncMock),
            patch(f"{MODULE}.apply_env_overrides"),
            patch(f"{MODULE}.load_factory_prompts"),
            patch(f"{MODULE}.persist_settings", side_effect=_track_persist),
            patch(f"{MODULE}._apply_configured_overlay", new_callable=AsyncMock),
            patch(f"{MODULE}.load_client_settings", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.persist_client_settings", new_callable=AsyncMock),
            patch(f"{MODULE}.load_oci_profiles", side_effect=_track_oci),
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
                pass

        oci_idx = call_order.index("load_oci_profiles")
        configured_persists = [i for i, evt in enumerate(call_order) if evt == "persist_settings:CONFIGURED"]
        assert configured_persists, "lifespan must persist CONFIGURED"
        assert all(i > oci_idx for i in configured_persists), (
            f"CONFIGURED persist must run after load_oci_profiles; got {call_order}"
        )

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

            mock_close_sqlcl.assert_awaited_once_with()
            # close_pool called once per database config
            assert mock_close_pool.await_count == len(saved_db_configs)
