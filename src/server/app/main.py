"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

FastAPI application entrypoint.
"""
# spell-checker:ignore fastmcp sqlcl

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.middleware import Middleware

import server.app.core.environ  # noqa: F401, E402  # side-effect: loads .env
from _version import __version__
from server.app.api.mcp.router import router as mcp_router
from server.app.api.v1.router import router as v1_router
from server.app.core.etc import apply_overlay, ensure_core_alias, load_config_file
from server.app.core.mcp import MCPApiKeyMiddleware, mcp
from server.app.core.settings import _client_store, settings
from server.app.database.config import close_pool, get_database_settings
from server.app.database.registry import init_core_database
from server.app.database.settings import (
    load_client_settings,
    load_settings,
    persist_client_settings,
    persist_settings,
    row_exists,
)
from server.app.mcp.prompts.registry import load_factory_prompts, reconcile_prompt_customizations, register_mcp_prompts
from server.app.mcp.proxies.sqlcl import close_sqlcl_proxy, register_sqlcl_proxy
from server.app.mcp.tools.registry import register_mcp_tools
from server.app.models.connectivity import check_model_reachability
from server.app.models.ollama import load_ollama_models
from server.app.models.registry import apply_env_overrides, load_default_models
from server.app.oci.registry import load_oci_profiles

LOGGER = logging.getLogger(__name__)
#############################################################################
# APP FACTORY
#############################################################################


async def _apply_configured_overlay(protected: set[str]) -> None:
    """Load CONFIGURED settings from config file or database and apply."""
    source = load_config_file()
    from_file = source is not None

    if not source and await row_exists("CONFIGURED"):
        source = await load_settings("CONFIGURED")

    if source is not None:
        apply_overlay(source, protected, exclude_fields={"oci_configs", "prompt_configs"})
        ensure_core_alias(settings.database_configs, settings.client_settings, _client_store)
        has_models = "model_configs" in source.model_fields_set if from_file else bool(source.model_configs)
        if has_models:
            settings.model_configs = source.model_configs
            if not from_file:
                apply_env_overrides()
        if source.prompt_configs:
            reconcile_prompt_customizations(source.prompt_configs)

    await persist_settings("CONFIGURED", is_current=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI Lifespan"""
    # --- Phase 1: Bootstrap (.env already loaded at import time) ---
    protected: set[str] = set(settings.model_fields_set)
    if settings.api_key_generated:
        protected.discard("api_key")

    # --- Phase 2: Init CORE database ---
    core_db = get_database_settings(settings.database_configs, "CORE")
    if core_db is not None:
        try:
            await init_core_database(core_db)
        except Exception:
            LOGGER.exception("CORE database initialization failed — continuing without persistence")

    # --- Phase 3: Build FACTORY baseline ---
    await load_default_models()
    apply_env_overrides()
    load_factory_prompts()
    await persist_settings("FACTORY", is_current=False)

    # --- Phase 4: Build/load CONFIGURED ---
    await _apply_configured_overlay(protected)

    # --- Phase 4b: Init server client settings ---
    server_cs = await load_client_settings("server")
    if server_cs is None:
        server_cs = settings.client_settings.model_copy(deep=True)
        await persist_client_settings("server", server_cs)
    server_cs.client = "server"
    _client_store["server"] = server_cs

    # --- Phase 5: Post-config startup ---
    await load_oci_profiles()
    await load_ollama_models()
    register_mcp_prompts()
    register_mcp_tools()
    settings.nl2sql_available = await register_sqlcl_proxy() is not None

    # --- Phase 6: Model reachability ---
    await check_model_reachability()

    try:
        yield
    finally:
        await close_sqlcl_proxy()
        for db in settings.database_configs:
            await close_pool(db.pool)


URL_PREFIX = settings.server_url_prefix.strip("/")
API_PREFIX = "/v1"
MCP_PREFIX = "/mcp"

mcp_app = mcp.http_app(
    path="/",
    middleware=[Middleware(MCPApiKeyMiddleware)],
)

app = FastAPI(
    title="Oracle AI Optimizer and Toolkit",
    version=__version__,
    # Docs routes are served by the v1 router behind verify_api_key; disable
    # the built-in unauthenticated ones FastAPI would otherwise register.
    docs_url=None,
    openapi_url=None,
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=None,
    root_path=f"/{URL_PREFIX}" if URL_PREFIX else "",
    lifespan=combine_lifespans(lifespan, mcp_app.lifespan),
    license_info={
        "name": "Universal Permissive License",
        "url": "http://oss.oracle.com/licenses/upl",
    },
)

app.include_router(v1_router, prefix=API_PREFIX)
app.include_router(mcp_router, prefix=MCP_PREFIX)
app.mount(MCP_PREFIX, mcp_app)
