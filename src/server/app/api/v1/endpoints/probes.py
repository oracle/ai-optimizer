"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth fastmcp healthz

from fastapi import APIRouter

from _version import __version__
from server.app.api.v1.schemas.probes import ProbeResponse, StatusResponse

noauth = APIRouter()


@noauth.get("/liveness", response_model=ProbeResponse)
async def liveness_probe():
    """Kubernetes liveness probe"""
    return {"status": "alive"}


@noauth.get("/readiness", response_model=ProbeResponse)
async def readiness_probe():
    """Kubernetes readiness probe"""
    return {"status": "ready"}


@noauth.get("/healthz", response_model=StatusResponse)
async def get_status():
    """Return application version and status."""
    return {"version": __version__, "status": "ok"}
