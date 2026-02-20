"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

import server.api.utils.models as utils_models

from common import schema

LOGGER = logging.getLogger("endpoints.v1.models")

auth = APIRouter()


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
    LOGGER.debug("Received models_list - type: %s; include_disabled: %s", model_type, include_disabled)
    models_ret = utils_models.get(model_type=model_type, include_disabled=include_disabled)
    print(models_ret)

    return models_ret


@auth.get(
    "/supported",
    description="Get supported providers and models",
    response_model=list[dict[str, Any]],
)
async def models_supported(
    model_provider: Optional[schema.ModelProviderType] = Query(None),
    model_type: Optional[schema.ModelTypeType] = Query(None),
) -> list[dict[str, Any]]:
    """List all model Providers"""
    LOGGER.debug("Received models_supported")

    return utils_models.get_supported(model_provider=model_provider, model_type=model_type)


@auth.get(
    "/{model_provider}/{model_id:path}",
    description="Get a single model (provider/name)",
    response_model=schema.Model,
)
async def models_get(
    model_provider: schema.ModelProviderType,
    model_id: schema.ModelIdType,
) -> schema.Model:
    """List a specific model"""
    LOGGER.debug("Received models_get - model: %s/%s", model_provider, model_id)

    try:
        (models_ret,) = utils_models.get(model_provider=model_provider, model_id=model_id)
    except utils_models.UnknownModelError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex
    except ValueError as ex:
        # happens if >1 results
        raise HTTPException(status_code=404, detail="Multiple models returned") from ex

    return models_ret


@auth.patch(
    "/{model_provider}/{model_id:path}",
    description="Update a model",
    response_model=schema.Model,
)
async def models_update(payload: schema.Model) -> schema.Model:
    """Update a model"""
    LOGGER.debug("Received models_update - payload: %s", payload)
    try:
        return utils_models.update(payload=payload)
    except utils_models.UnknownModelError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex
    except utils_models.URLUnreachableError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex


@auth.post("", description="Create a model", response_model=schema.Model, status_code=201)
async def models_create(
    payload: schema.Model,
) -> schema.Model:
    """Create a model"""
    LOGGER.debug("Received model_create - payload: %s", payload)

    try:
        return utils_models.create(payload)
    except utils_models.ExistsModelError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex


@auth.delete(
    "/{model_provider}/{model_id:path}",
    description="Delete a model",
)
async def models_delete(
    model_provider: schema.ModelProviderType,
    model_id: schema.ModelIdType,
) -> JSONResponse:
    """Delete a model"""
    LOGGER.debug("Received models_delete - model: %s/%s", model_provider, model_id)
    utils_models.delete(model_provider=model_provider, model_id=model_id)
    return JSONResponse(status_code=200, content={"message": f"Model: {model_provider}/{model_id} deleted."})
