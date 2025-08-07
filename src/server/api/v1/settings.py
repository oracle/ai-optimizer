"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import json
from typing import Union

from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile
from fastapi.responses import JSONResponse

from server.api.core import settings


import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.settings")

auth = APIRouter()


def _incl_sensitive_param(incl_sensitive: bool = Query(False, include_in_schema=False)):
    return incl_sensitive


def _incl_readonly_param(incl_readonly: bool = Query(False, include_in_schema=False)):
    return incl_readonly


@auth.get(
    "",
    description="Get client settings and configuration",
    response_model=Union[schema.Configuration, schema.Settings],
)
async def settings_get(
    client: schema.ClientIdType,
    full_config: bool = False,
    incl_sensitive: bool = Depends(_incl_sensitive_param),
    incl_readonly: bool = Depends(_incl_readonly_param),
) -> Union[schema.Configuration, schema.Settings, JSONResponse]:
    """Get settings for a specific client by name"""
    try:
        client_settings = settings.get_client_settings(client)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex

    if not full_config:
        return client_settings

    config = settings.get_server_config()
    response = schema.Configuration(
        client_settings=client_settings,
        database_configs=config.get("database_configs"),
        model_configs=config.get("model_configs"),
        oci_configs=config.get("oci_configs"),
        prompt_configs=config.get("prompt_configs"),
        mcp_configs=config.get("mcp_configs", None)
    )
    if incl_sensitive or incl_readonly:
        return JSONResponse(content=response.model_dump_public(incl_sensitive=incl_sensitive, incl_readonly=incl_readonly))
    return response


@auth.patch(
    "",
    description="Update client settings",
)
async def settings_update(
    payload: schema.Settings,
    client: schema.ClientIdType,
) -> schema.Settings:
    """Update a single client settings"""
    logger.debug("Received %s Client Payload: %s", client, payload)

    try:
        return settings.update_client_settings(payload, client)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"Settings: {str(ex)}.") from ex


@auth.post(
    "",
    description="Create new client settings",
    response_model=schema.Settings,
)
async def settings_create(
    client: schema.ClientIdType,
) -> schema.Settings:
    """Create a new client, initialise client settings"""
    logger.debug("Received %s Client create request.", client)

    try:
        new_client = settings.create_client_settings(client)
    except ValueError as ex:
        raise HTTPException(status_code=409, detail=f"Settings: {str(ex)}.") from ex

    return new_client


@auth.post(
    "/load/file",
    description="Load configuration from file",
)
async def load_settings_from_file(
    client: schema.ClientIdType,
    file: UploadFile,
) -> JSONResponse:
    """Load settings for a specific client from uploaded JSON file.
    If `client` param is provided, update that client only.
    Otherwise, update "default" and "server" clients.
    """
    logger.debug("Received %s Client File: %s", client, file)
    try:
        settings.create_client_settings(client)
    except ValueError:  # Client already exists
        pass

    try:
        if not file.filename or not file.filename.endswith(".json"):
            raise HTTPException(status_code=400, detail="Settings: Only JSON files are supported.")
        contents = await file.read()
        config_data = json.loads(contents)
        settings.load_config_from_json_data(config_data, client)
        return JSONResponse(content={"message": "Configuration loaded successfully."})
    except json.JSONDecodeError as ex:
        raise HTTPException(status_code=400, detail="Settings: Invalid JSON file.") from ex
    except KeyError as ex:
        raise HTTPException(status_code=400, detail=f"Settings: {str(ex)}.") from ex
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Settings: {str(ex)}.") from ex


@auth.post(
    "/load/json",
    description="Load configuration from file",
)
async def load_settings_from_json(
    client: schema.ClientIdType,
    payload: schema.Configuration,
) -> JSONResponse:
    """Load settings for a specific client from uploaded JSON payload.
    If `client` param is provided, update that client only.
    Otherwise, update "default" and "server" clients.
    """
    logger.debug("Received %s Client Payload: %s", client, payload)
    try:
        settings.create_client_settings(client)
    except ValueError:  # Client already exists
        pass

    try:
        settings.load_config_from_json_data(payload.model_dump(), client)
        return JSONResponse(content={"message": "Configuration loaded successfully."})
    except json.JSONDecodeError as ex:
        raise HTTPException(status_code=400, detail="Settings: Invalid JSON file.") from ex
    except KeyError as ex:
        raise HTTPException(status_code=400, detail=f"Settings: {str(ex)}.") from ex
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Settings: {str(ex)}.") from ex
