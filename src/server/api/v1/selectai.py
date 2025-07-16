"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai

import json

from fastapi import APIRouter, Header

from server.api.core import settings, databases
from server.api.util import selectai

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.selectai")

auth = APIRouter()


@auth.get(
    "/objects",
    description="Get SelectAI Profile Object List",
    response_model=list[schema.DatabaseSelectAIObjects],
)
async def selectai_get_objects(
    client: schema.ClientIdType = Header(default="server"),
) -> list[schema.DatabaseSelectAIObjects]:
    """Get DatabaseSelectAIObjects"""
    client_settings = settings.get_client_settings(client)
    db_conn = databases.get_client_db(client).connection
    select_ai_objects = selectai.get_objects(db_conn, client_settings.selectai.profile)
    return select_ai_objects


@auth.patch(
    "/objects",
    description="Update SelectAI Profile Object List",
    response_model=list[schema.DatabaseSelectAIObjects],
)
async def selectai_update_objects(
    payload: list[schema.DatabaseSelectAIObjects],
    client: schema.ClientIdType = Header(default="server"),
) -> list[schema.DatabaseSelectAIObjects]:
    """Update DatabaseSelectAIObjects"""
    logger.debug("Received selectai_update - payload: %s", payload)
    client_settings = settings.get_client_settings(client)
    object_list = json.dumps([obj.model_dump(include={"owner", "name"}) for obj in payload])
    db_conn = databases.get_client_db(client).connection
    selectai.set_profile(db_conn, client_settings.selectai.profile, "object_list", object_list)
    return selectai.get_objects(db_conn, client_settings.selectai.profile)
