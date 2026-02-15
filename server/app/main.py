"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

FastAPI application entrypoint.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from server._version import __version__
from server.app.api.v1.router import router as v1_router
from server.app.core.config import settings
from server.app.database import close_pool, get_all_registered_databases, initialize_schema


#############################################################################
# APP FACTORY
#############################################################################
LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI Lifespan"""
    if settings.api_key_generated:
        LOGGER.warning("AIO_API_KEY not set — using generated key: %s", settings.api_key)
    await initialize_schema()
    try:
        yield
    finally:
        for db in get_all_registered_databases():
            await close_pool(db.pool)


API_PREFIX = "/v1"

BASE_PATH = settings.url_prefix.strip("/")
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
