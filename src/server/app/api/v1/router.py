"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth

from fastapi import APIRouter, Depends

from server.app.api.deps import verify_api_key
from server.app.api.v1.endpoints import probes

router = APIRouter()
router.include_router(probes.noauth, tags=["Probes"])
router.include_router(
    probes.auth,
    tags=["Probes"],
    dependencies=[Depends(verify_api_key)],
)
