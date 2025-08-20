"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai

from typing import Optional, get_args
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

import server.api.core.models as core_models
import server.api.utils.models as util_models

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.models")

auth = APIRouter()


@auth.get(
    "/provider",
    description="Get support model providers",
    response_model=list,
)
async def models_list_provider() -> list[schema.Model]:
    """List all models APIs after applying filters if specified"""
    logger.debug("Received models_list_provider")
    return list(get_args(schema.ModelProviders))


@auth.get(
    "",
    description="Get all models (by default, only enabled)",
    response_model=list[schema.Model],
)
async def models_list(
    model_type: Optional[schema.ModelTypeType] = Query(None),
    include_disabled: schema.ModelEnabledType = Query(False, description="Include disabled models"),
) -> list[schema.Model]:
    """List all models after applying filters if specified"""
    logger.debug("Received models_list - type: %s", model_type)
    models_ret = core_models.get_model(model_type=model_type, include_disabled=include_disabled)

    return models_ret


@auth.get(
    "/{model_id:path}",
    description="Get a single model",
    response_model=schema.Model,
)
async def models_get(
    model_id: schema.ModelIdType,
) -> schema.Model:
    """List a specific model"""
    logger.debug("Received models_get - model_id: %s", model_id)

    try:
        models_ret = core_models.get_model(model_id=model_id)
    except core_models.UnknownModelError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex

    return models_ret


@auth.patch(
    "/{model_id:path}",
    description="Update a model",
    response_model=schema.Model,
)
async def models_update(
    model_id: schema.ModelIdType,
    payload: schema.Model,
) -> schema.Model:
    """Update a model"""
    logger.debug("Received models_update - model_id: %s; payload: %s", model_id, payload)
    try:
        return util_models.update_model(model_id=model_id, payload=payload)
    except core_models.UnknownModelError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex
    except core_models.URLUnreachableError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex


@auth.post("", description="Create a model", response_model=schema.Model, status_code=201)
async def models_create(
    payload: schema.Model,
) -> schema.Model:
    """Update a model"""
    logger.debug("Received model_create - payload: %s", payload)

    try:
        return core_models.create_model(payload)
    except core_models.ExistsModelError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex


@auth.delete(
    "/{model_id:path}",
    description="Delete a model",
)
async def models_delete(
    model_id: schema.ModelIdType,
) -> JSONResponse:
    """Delete a model"""
    logger.debug("Received models_delete - model_id: %s", model_id)
    core_models.delete_model(model_id)
    return JSONResponse(status_code=200, content={"message": f"Model: {model_id} deleted."})
