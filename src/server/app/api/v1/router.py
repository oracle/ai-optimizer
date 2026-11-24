"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth

from fastapi import APIRouter, Depends

from server.app.api.v1.endpoints import (
    agentspec,
    chat,
    databases,
    deepsec,
    docs,
    embed,
    help_text,
    models,
    oci,
    probes,
    prompts,
    settings,
    testbed,
)
from server.app.auth.policy import enforce_route_policy
from server.app.auth.router import router as auth_router
from server.app.auth.router import users_router

router = APIRouter()
# -- Non Authenticated Endpoints
router.include_router(probes.noauth, tags=["Probes"])
router.include_router(docs.noauth, tags=["Docs"])
router.include_router(auth_router)
router.include_router(users_router)

# -- Authenticated Endpoints
router.include_router(
    settings.auth,
    tags=["Settings"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    databases.auth,
    tags=["Databases"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    models.auth,
    tags=["Models"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    oci.auth,
    tags=["OCI Profiles"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    prompts.auth,
    tags=["Prompts"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    agentspec.auth,
    tags=["AgentSpec"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    help_text.auth,
    tags=["Help"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    chat.auth,
    tags=["Chat"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    testbed.auth,
    tags=["Testbed"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    embed.auth,
    tags=["Embed"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    deepsec.auth,
    tags=["Deep Data Security"],
    dependencies=[Depends(enforce_route_policy)],
)
router.include_router(
    docs.auth,
    tags=["Docs"],
    dependencies=[Depends(enforce_route_policy)],
)
