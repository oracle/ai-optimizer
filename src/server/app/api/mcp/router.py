"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth

from fastapi import APIRouter, Depends

from server.app.api.deps import verify_api_key
from server.app.api.mcp.endpoints import client_config, probes, prompts, resources, tools

router = APIRouter()
router.include_router(probes.noauth, tags=["Probes"])
router.include_router(
    prompts.auth,
    tags=["Prompts", "Model Context Protocol"],
    dependencies=[Depends(verify_api_key)],
)
router.include_router(
    tools.auth,
    tags=["Model Context Protocol"],
    dependencies=[Depends(verify_api_key)],
)
router.include_router(
    resources.auth,
    tags=["Model Context Protocol"],
    dependencies=[Depends(verify_api_key)],
)
router.include_router(
    client_config.auth,
    tags=["Model Context Protocol"],
    dependencies=[Depends(verify_api_key)],
)
