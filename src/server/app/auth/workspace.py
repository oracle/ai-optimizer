"""Persistent settings workspaces owned by authenticated users."""

from uuid import UUID

from fastmcp.server.dependencies import get_access_token

from server.app.auth.models import workspace_key
from server.app.core.settings import (
    _apply_default_ll_model,
    _client_store,
    _client_store_lock,
    _ensure_capacity,
    _settings_lock,
    settings,
)
from server.app.database.settings import load_client_settings, persist_client_settings


async def ensure_workspace(key: str) -> None:
    """Load or create the persistent settings workspace for ``key``."""
    with _client_store_lock:
        if key in _client_store:
            _client_store.move_to_end(key)
            return

    async with _settings_lock:
        with _client_store_lock:
            if key in _client_store:
                _client_store.move_to_end(key)
                return

        workspace = await load_client_settings(key)
        if workspace is None:
            configured = await load_client_settings("CONFIGURED")
            workspace = (configured or settings.client_settings).model_copy(deep=True)
            workspace.client = key
            _apply_default_ll_model(workspace)
            if not await persist_client_settings(key, workspace):
                raise RuntimeError("Workspace settings could not be persisted")

        workspace.client = key
        with _client_store_lock:
            _ensure_capacity()
            _client_store[key] = workspace


async def mcp_workspace_key(fallback: str) -> str:
    """Resolve the workspace owned by the active MCP principal."""
    token = get_access_token()
    if token is None or not token.client_id:
        return fallback
    key = workspace_key(UUID(token.client_id))
    await ensure_workspace(key)
    return key
