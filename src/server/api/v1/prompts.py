"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai

from typing import Optional
from fastapi import APIRouter, HTTPException

from server.api.core import prompts

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.prompts")

auth = APIRouter()


@auth.get(
    "",
    description="Get all prompt configurations",
    response_model=list[schema.Prompt],
)
async def prompts_list(
    category: Optional[schema.PromptCategoryType] = None,
) -> list[schema.Prompt]:
    """List all prompts after applying filters if specified"""
    return prompts.get_prompts(category=category)


@auth.get(
    "/{category}/{name}",
    description="Get single prompt configuration",
    response_model=schema.Prompt,
)
async def prompts_get(
    category: schema.PromptCategoryType,
    name: schema.PromptNameType,
) -> schema.Prompt:
    """Get a single prompt"""
    try:
        return prompts.get_prompts(category=category, name=name)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"Prompt: {str(ex)}.") from ex


@auth.patch(
    "/{category}/{name}",
    description="Update Prompt Configuration",
    response_model=schema.Prompt,
)
async def prompts_update(
    category: schema.PromptCategoryType,
    name: schema.PromptNameType,
    payload: schema.PromptText,
) -> schema.Prompt:
    """Update a single Prompt"""
    logger.debug("Received %s (%s) Prompt Payload: %s", name, category, payload)
    prompt_upd = await prompts_get(category, name)
    prompt_upd.prompt = payload.prompt

    return await prompts_get(category, name)
