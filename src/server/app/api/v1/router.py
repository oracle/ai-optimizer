"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth

from fastapi import APIRouter, Depends

from server.app.api.deps import verify_api_key
from server.app.api.v1.endpoints import databases, oci_profiles, probes, settings

router = APIRouter()
router.include_router(probes.noauth, tags=["Probes"])
router.include_router(
    probes.auth,
    tags=["Probes"],
    dependencies=[Depends(verify_api_key)],
)
router.include_router(
    settings.auth,
    tags=["Settings"],
    dependencies=[Depends(verify_api_key)],
)
router.include_router(
    databases.auth,
    tags=["Databases"],
    dependencies=[Depends(verify_api_key)],
)
router.include_router(
    oci_profiles.auth,
    tags=["OCI Profiles"],
    dependencies=[Depends(verify_api_key)],
)
