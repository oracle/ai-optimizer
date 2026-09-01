"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth

from fastapi import APIRouter, Depends

from server.app.api.deps import require_administrator, require_principal
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

router = APIRouter()
# -- Non Authenticated Endpoints
router.include_router(probes.noauth, tags=["Probes"])
router.include_router(docs.noauth, tags=["Docs"])

# -- Authenticated Endpoints
router.include_router(
    settings.auth,
    tags=["Settings"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    databases.auth,
    tags=["Databases"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    models.auth,
    tags=["Models"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    oci.auth,
    tags=["OCI Profiles"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    prompts.auth,
    tags=["Prompts"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    agentspec.auth,
    tags=["AgentSpec"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    help_text.auth,
    tags=["Help"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    chat.auth,
    tags=["Chat"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    testbed.auth,
    tags=["Testbed"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    embed.auth,
    tags=["Embed"],
    dependencies=[Depends(require_principal)],
)
router.include_router(
    deepsec.auth,
    tags=["Deep Data Security"],
    dependencies=[Depends(require_administrator)],
)
router.include_router(
    docs.auth,
    tags=["Docs"],
    dependencies=[Depends(require_principal)],
)
