"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File
from fastapi.responses import JSONResponse

from server.api.core import bootstrap, settings


import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.settings")

auth = APIRouter()


def _incl_sensitive_param(incl_sensitive: bool = Query(False, include_in_schema=False)):
    return incl_sensitive


@auth.get("/", description="Get client settings and configuration", response_model=schema.Configuration)
async def settings_get(
    client: schema.ClientIdType, full_config: bool = False, incl_sensitive: bool = Depends(_incl_sensitive_param)
) -> schema.Configuration:
    """Get settings for a specific client by name"""
    try:
        client_settings = settings.get_client_settings(client)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex

    if not full_config:
        config = schema.Configuration(client_settings=client_settings)
        return JSONResponse(content=config.model_dump(exclude_none=True))

    config = settings.get_server_config()
    response = schema.Configuration(
        client_settings=client_settings,
        database_configs=config.get("database_configs"),
        model_configs=config.get("model_configs"),
        oci_configs=config.get("oci_configs"),
        prompt_configs=config.get("prompt_configs"),
    )
    return JSONResponse(content=response.model_dump_public(incl_sensitive=incl_sensitive))


@auth.patch("/", description="Update client settings")
async def settings_update(payload: schema.Settings, client: schema.ClientIdType) -> schema.Settings:
    """Update a single client settings"""
    logger.debug("Received %s Client Payload: %s", client, payload)

    try:
        return settings.update_client_settings(payload, client)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex


@auth.post("/", description="Create new client settings", response_model=schema.Settings)
async def settings_create(client: schema.ClientIdType) -> schema.Settings:
    """Create a new client, initialise client settings"""
    settings_objects = bootstrap.SETTINGS_OBJECTS

    if any(settings.client == client for settings in settings_objects):
        raise HTTPException(status_code=409, detail=f"Client: {client} already exists.")
    default_settings = next((settings for settings in settings_objects if settings.client == "default"), None)

    # Copy the default settings
    client_settings = schema.Settings(**default_settings.model_dump())
    client_settings.client = client
    settings_objects.append(client_settings)

    return client_settings


@auth.post("/load", description="Load configuration from file")
async def load_settings_from_file(
    file: UploadFile = File(...), client: Optional[schema.ClientIdType] = Query(None)
) -> JSONResponse:
    """Load settings for a specific client from uploaded JSON file.

    If `client` param is provided, update that client only.
    Otherwise, update "default" and "server" clients.
    """
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are supported.")

    try:
        contents = await file.read()
        config_data = json.loads(contents)
        settings.load_config_from_json_data(config_data, client)
        return {"message": "Configuration loaded successfully."}
    except json.JSONDecodeError as ex:
        raise HTTPException(status_code=400, detail="Invalid JSON file.") from ex
    except KeyError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex)) from ex
