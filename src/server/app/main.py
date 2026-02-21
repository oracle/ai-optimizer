"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

FastAPI application entrypoint.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from _version import __version__
from server.app.core.etc import apply_overlay, load_config_file
from server.app.core.settings import settings
from server.app.api.v1.router import router as v1_router
from server.app.database.registry import init_core_database
from server.app.database.config import get_database_settings, close_pool
from server.app.database.settings import load_settings, persist_settings
from server.app.models.registry import apply_env_overrides, load_default_models
from server.app.oci.registry import load_oci_profiles

LOGGER = logging.getLogger(__name__)
#############################################################################
# APP FACTORY
#############################################################################


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI Lifespan"""
    # --- Source 1: .env (already loaded at import time) ---
    protected: set[str] = set(settings.model_fields_set)
    if settings.api_key_generated:
        protected.discard("api_key")
        LOGGER.warning("AIO_API_KEY not set — using generated key: %s", settings.api_key)

    # --- Source 2: configuration.json overlay ---
    _excl = {"model_configs", "oci_configs"}
    config_source = load_config_file()
    if config_source is not None:
        protected = apply_overlay(config_source, protected, exclude_fields=_excl)

    # --- Initialize CORE database (config may come from env OR config file) ---
    core_cfg = get_database_settings(settings.database_configs, "CORE")
    await init_core_database(core_cfg)

    # --- Source 3: aio_settings DB overlay ---
    db_source = await load_settings()
    if db_source is not None:
        apply_overlay(db_source, protected, exclude_fields=_excl)

    # --- Model configs: first non-empty source wins ---
    config_models = (
        config_source.model_configs
        if config_source and "model_configs" in config_source.model_fields_set
        else []
    )
    db_models = (
        db_source.model_configs
        if db_source and "model_configs" in db_source.model_fields_set
        else []
    )
    if config_models:
        settings.model_configs = config_models
    elif db_models:
        settings.model_configs = db_models
    else:
        await load_default_models()

    if not config_models:
        apply_env_overrides()

    # --- Post-overlay startup tasks ---
    await load_oci_profiles()
    await persist_settings()

    try:
        yield
    finally:
        for db in settings.database_configs:
            await close_pool(db.pool)


API_PREFIX = "/v1"

BASE_PATH = settings.server_url_prefix.strip("/")
BASE_PATH = f"/{BASE_PATH}" if BASE_PATH else ""

app = FastAPI(
    title="Oracle AI Optimizer and Toolkit",
    version=__version__,
    docs_url=f"{API_PREFIX}/docs",
    openapi_url=f"{API_PREFIX}/openapi.json",
    root_path=BASE_PATH,
    lifespan=lifespan,
    license_info={
        "name": "Universal Permissive License",
        "url": "http://oss.oracle.com/licenses/upl",
    },
)

app.include_router(v1_router, prefix=API_PREFIX)
