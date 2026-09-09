"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

FastAPI application entrypoint.
"""
# spell-checker:ignore fastmcp sqlcl

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastmcp.utilities.lifespan import combine_lifespans

import server.app.core.environ  # noqa: F401, E402  # side-effect: loads .env
from _version import __version__
from server.app.api.mcp.router import router as mcp_router
from server.app.api.v1.router import router as v1_router
from server.app.auth.gateway import create_application as create_auth_gateway_application
from server.app.auth.providers import GitHubProvider, OidcProvider
from server.app.auth.service import GatewayConfig, GatewayService
from server.app.auth.store import OracleAuthStore
from server.app.core.auth import PrincipalAuthMiddleware
from server.app.core.etc import apply_overlay, ensure_core_alias, load_config_file
from server.app.core.mcp import mcp
from server.app.core.secrets import reveal
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
from server.app.embed.jobs import (
    get_embed_job_manager,
    run_heartbeat_loop,
    run_reaper_loop,
)
from server.app.mcp.prompts.registry import load_factory_prompts, reconcile_prompt_customizations, register_mcp_prompts
from server.app.mcp.proxies.sqlcl import close_sqlcl_proxy, register_sqlcl_proxy
from server.app.mcp.tools.registry import register_mcp_tools
from server.app.models.connectivity import check_model_reachability
from server.app.models.ollama import load_ollama_models
from server.app.models.registry import apply_env_overrides, dedupe_model_configs, load_default_models
from server.app.oci.registry import load_oci_profiles
from server.app.otel import init_telemetry, instrument_fastapi

init_telemetry()

LOGGER = logging.getLogger(__name__)


class _EmbeddedUvicornServer(uvicorn.Server):
    """A lifecycle child server that leaves the primary server's signals alone."""

    def install_signal_handlers(self) -> None:
        return


async def _start_auth_gateway() -> tuple[_EmbeddedUvicornServer, asyncio.Task]:
    """Start the embedded OIDC gateway for the selected identity source."""
    gateway = GatewayService(
        GatewayConfig(
            issuer=settings.auth_issuer,
            mode=settings.auth_mode or "local",
            web_client_secret=reveal(settings.auth_web_client_secret) or "",
            web_redirect_uri=settings.auth_web_redirect_uri,
            local_admin_username=settings.auth_local_admin_username,
            local_admin_password=reveal(settings.auth_local_admin_password) or "",
            access_token_minutes=settings.auth_access_token_minutes,
            login_session_hours=settings.auth_login_session_hours,
        ),
        OracleAuthStore(),
    )
    provider = None
    if settings.auth_mode == "github":
        provider = GitHubProvider(
            client_id=settings.auth_github_client_id,
            client_secret=reveal(settings.auth_github_client_secret) or "",
            base_url=settings.auth_github_base_url,
            allowed_users=frozenset(settings.auth_github_allowed_users),
            allowed_organizations=frozenset(settings.auth_github_allowed_organizations),
            administrator_users=frozenset(settings.auth_github_admin_users),
            administrator_teams=frozenset(settings.auth_github_admin_teams),
        )
    elif settings.auth_mode == "oidc":
        provider = OidcProvider(
            issuer=settings.auth_oidc_issuer,
            client_id=settings.auth_oidc_client_id,
            client_secret=reveal(settings.auth_oidc_client_secret) or "",
            scopes=tuple(settings.auth_oidc_scopes),
            signing_algorithms=tuple(settings.auth_oidc_signing_algorithms),
            roles_claim=settings.auth_oidc_roles_claim,
            allowed_claim_values=frozenset(settings.auth_oidc_allowed_claim_values),
            administrator_claim_values=frozenset(settings.auth_admin_claim_values),
        )
    oidc_app = await create_auth_gateway_application(gateway, provider)
    server = _EmbeddedUvicornServer(
        uvicorn.Config(
            oidc_app,
            host=settings.auth_listen_host,
            port=settings.auth_listen_port,
            log_level=settings.log_level.lower(),
        )
    )
    task = asyncio.create_task(server.serve(), name="authentication-gateway")
    for _ in range(100):
        if server.started:
            return server, task
        await asyncio.sleep(0.01)
    server.should_exit = True
    await task
    raise RuntimeError("Authentication gateway did not start")


async def _initialize_core_database() -> None:
    """Initialize CORE before principal-authenticated operation starts."""
    core_db = get_database_settings(settings.database_configs, "CORE")
    if core_db is None:
        return
    try:
        await init_core_database(core_db)
    except Exception:
        LOGGER.exception("CORE database initialization failed — continuing without persistence")
        if settings.auth_mode in {"local", "github", "oidc", "proxy"}:
            raise


#############################################################################
# APP FACTORY
#############################################################################


async def _apply_configured_overlay(
    protected: set[str],
    *,
    include_database: bool = True,
    database_only: bool = False,
    preserve_promoted_core_alias: str | None = None,
) -> tuple[bool, str | None]:
    """Load CONFIGURED settings from file or, when enabled, the database and apply.

    Returns ``(from_file, promoted_alias)`` for the applied source.
    """
    source = load_config_file()
    from_file = source is not None

    if not source and include_database and await row_exists("CONFIGURED"):
        source = await load_settings("CONFIGURED")

    promoted_core_alias: str | None = None
    if source is not None:
        if preserve_promoted_core_alias is not None:
            for db_config in source.database_configs:
                if db_config.alias.casefold() == preserve_promoted_core_alias.casefold():
                    # The bootstrap pass already promoted this source entry to CORE;
                    # normalize it before merging so it is not appended a second time.
                    db_config.alias = "CORE"
                    break
            if (
                "client_settings" in source.model_fields_set
                and source.client_settings.database.alias == preserve_promoted_core_alias
            ):
                source.client_settings.database.alias = "CORE"
        excluded = {"oci_configs", "prompt_configs"}
        if database_only:
            excluded |= source.model_fields_set - {"database_configs"}
        apply_overlay(source, protected, exclude_fields=excluded)
        promoted_core_alias = ensure_core_alias(settings.database_configs, settings.client_settings, _client_store)
        has_models = "model_configs" in source.model_fields_set if from_file else bool(source.model_configs)
        if not database_only and has_models:
            # Restored settings can carry duplicate (provider, id) entries written
            # by older code; the assignment below would otherwise persist them and
            # surface as duplicate rows in the UI. Dedupe so the invariant holds.
            settings.model_configs = dedupe_model_configs(source.model_configs)
            if not from_file:
                apply_env_overrides()
        if not database_only and source.prompt_configs:
            reconcile_prompt_customizations(source.prompt_configs)
    return from_file, promoted_core_alias


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI Lifespan"""
    # --- Phase 1: Bootstrap (.env already loaded at import time) ---
    protected: set[str] = set(settings.model_fields_set)
    if settings.api_key_generated:
        protected.discard("api_key")

    # --- Phase 2: Load file CORE configuration and validate authentication ---
    _, promoted_core_alias = await _apply_configured_overlay(protected, include_database=False, database_only=True)
    settings.validate_authentication_posture()

    # --- Phase 3: Init CORE database ---
    await _initialize_core_database()

    # --- Phase 4: Build FACTORY baseline ---
    await load_default_models()
    apply_env_overrides()
    load_factory_prompts()
    await persist_settings("FACTORY", is_current=False)

    # --- Phase 5: Build/load CONFIGURED and validate authentication ---
    await _apply_configured_overlay(protected, preserve_promoted_core_alias=promoted_core_alias)
    settings.validate_authentication_posture()

    auth_gateway_server: _EmbeddedUvicornServer | None = None
    auth_gateway_task: asyncio.Task | None = None
    if settings.auth_mode in {"local", "github", "oidc"}:
        auth_gateway_server, auth_gateway_task = await _start_auth_gateway()

    # --- Phase 6: Init server client settings ---
    server_cs = await load_client_settings("server")
    if server_cs is None:
        server_cs = settings.client_settings.model_copy(deep=True)
        await persist_client_settings("server", server_cs)
    server_cs.client = "server"
    _client_store["server"] = server_cs

    # --- Phase 7: Post-config startup ---
    await load_oci_profiles()
    await load_ollama_models()
    register_mcp_prompts()
    register_mcp_tools()
    settings.nl2sql_available = await register_sqlcl_proxy() is not None

    # Persist CONFIGURED after load_oci_profiles() so the OCI GenAI overlay
    # picked up from the previous run's row is preserved (an earlier persist
    # would write an empty oci_configs list and erase it).
    await persist_settings("CONFIGURED", is_current=True)

    # --- Phase 8: Model reachability ---
    await check_model_reachability()

    # --- Phase 9: Embed-job heartbeat + reaper ---
    # Each replica heartbeats its own owned rows in aio_embed_jobs and
    # also participates in the cross-pod reaper sweep. This is what
    # turns a pod crash mid-pipeline into a terminal "failed" record
    # for polling clients instead of an indefinite "running" row.
    embed_job_manager = get_embed_job_manager()
    heartbeat_task = asyncio.create_task(
        run_heartbeat_loop(embed_job_manager),
        name="embed-jobs-heartbeat",
    )
    reaper_task = asyncio.create_task(
        run_reaper_loop(embed_job_manager),
        name="embed-jobs-reaper",
    )

    try:
        yield
    finally:
        if auth_gateway_server is not None:
            auth_gateway_server.should_exit = True
        if auth_gateway_task is not None:
            with contextlib.suppress(BaseException):
                await auth_gateway_task
        for task in (heartbeat_task, reaper_task):
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        await close_sqlcl_proxy()
        for db in settings.database_configs:
            await close_pool(db.pool)


URL_PREFIX = settings.server_url_prefix.strip("/")
API_PREFIX = "/v1"
MCP_PREFIX = "/mcp"

mcp_app = mcp.http_app(
    path="/",
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
app.add_middleware(PrincipalAuthMiddleware)
instrument_fastapi(app)

app.include_router(v1_router, prefix=API_PREFIX)
app.include_router(mcp_router, prefix=MCP_PREFIX)
app.mount(MCP_PREFIX, mcp_app)
