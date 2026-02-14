"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth fastmcp healthz

from fastapi import APIRouter

from server._version import __version__

noauth = APIRouter()
auth = APIRouter()


@noauth.get("/liveness")
async def liveness_probe():
    """Kubernetes liveness probe"""
    return {"status": "alive"}


@noauth.get("/readiness")
async def readiness_probe():
    """Kubernetes readiness probe"""
    return {"status": "ready"}


@auth.get("/status")
async def get_status():
    """Return application version and status."""
    return {"version": __version__, "status": "ok"}
