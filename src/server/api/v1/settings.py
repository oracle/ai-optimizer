"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging
import json
from typing import Union

from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, Request
from fastapi.responses import JSONResponse

import server.api.utils.settings as utils_settings

from common import schema


LOGGER = logging.getLogger("endpoints.v1.settings")

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
    request: Request,
    client: schema.ClientIdType,
    full_config: bool = False,
    incl_sensitive: bool = Depends(_incl_sensitive_param),
    incl_readonly: bool = Depends(_incl_readonly_param),
) -> Union[schema.Configuration, schema.Settings]:
    """Get settings for a specific client by name"""
    try:
        client_settings = utils_settings.get_client(client)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex

    if not full_config:
        return client_settings

    # Get MCP engine for prompt retrieval
    mcp_engine = request.app.state.fastmcp_app
    config = await utils_settings.get_server(mcp_engine)

    response = schema.Configuration(
        client_settings=client_settings,
        database_configs=config.get("database_configs"),
        model_configs=config.get("model_configs"),
        oci_configs=config.get("oci_configs"),
        prompt_configs=config.get("prompt_configs"),
    )
    return JSONResponse(content=response.model_dump_public(incl_sensitive=incl_sensitive, incl_readonly=incl_readonly))


@auth.patch(
    "",
    description="Update client settings",
)
async def settings_update(
    payload: schema.Settings,
    client: schema.ClientIdType,
) -> schema.Settings:
    """Update a single client settings"""
    LOGGER.debug("Received %s Client Payload: %s", client, payload)

    try:
        return utils_settings.update_client(payload, client)
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
    LOGGER.debug("Received %s Client create request.", client)

    try:
        new_client = utils_settings.create_client(client)
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
    LOGGER.debug("Received %s Client File: %s", client, file)
    try:
        utils_settings.create_client(client)
    except ValueError:  # Client already exists
        pass

    try:
        if not file.filename.endswith(".json"):
            raise HTTPException(status_code=400, detail="Settings: Only JSON files are supported.")
        contents = await file.read()
        config_data = json.loads(contents)
        utils_settings.load_config_from_json_data(config_data, client)
        return {"message": "Configuration loaded successfully."}
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
    LOGGER.debug("Received %s Client Payload: %s", client, payload)
    try:
        utils_settings.create_client(client)
    except ValueError:  # Client already exists
        pass

    try:
        utils_settings.load_config_from_json_data(payload.model_dump(), client)
        return {"message": "Configuration loaded successfully."}
    except json.JSONDecodeError as ex:
        raise HTTPException(status_code=400, detail="Settings: Invalid JSON file.") from ex
    except KeyError as ex:
        raise HTTPException(status_code=400, detail=f"Settings: {str(ex)}.") from ex
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Settings: {str(ex)}.") from ex
