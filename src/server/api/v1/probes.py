"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth

from fastapi import APIRouter

noauth = APIRouter()


@noauth.get("/liveness")
async def liveness_probe():
    """Kubernetes liveness probe"""
    return {"status": "alive"}


@noauth.get("/readiness")
async def readiness_probe():
    """Kubernetes readiness probe"""
    return {"status": "ready"}
