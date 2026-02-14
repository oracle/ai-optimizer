"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

FastAPI application entrypoint.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from server._version import __version__
from server.app.api.v1.router import router as v1_router
from server.app.core.config import settings
from server.app.db import initialize_schema


#############################################################################
# APP FACTORY
#############################################################################
@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI Lifespan"""
    pool = await initialize_schema()
    try:
        yield
    finally:
        if pool is not None:
            await pool.close()


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
