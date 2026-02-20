"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

FastAPI application entrypoint.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from _version import __version__
from server.app.core.settings import settings
from server.app.api.v1.router import router as v1_router
from server.app.database import init_core_database
from server.app.database.config import get_database_settings, close_pool
from server.app.database.settings import persist_settings
from server.app.oci import load_oci_profiles

LOGGER = logging.getLogger(__name__)
#############################################################################
# APP FACTORY
#############################################################################


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI Lifespan"""
    if settings.api_key_generated:
        LOGGER.warning("AIO_API_KEY not set — using generated key: %s", settings.api_key)
    core_cfg = get_database_settings(settings.database_configs, "CORE")
    await init_core_database(core_cfg)
    await load_oci_profiles()
    # await load_persisted_settings()
    # persisted, _ = await load_core_settings()
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
