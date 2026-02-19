"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
This file is being used in APIs, and not the backend.py file.
"""
# spell-checker:ignore noauth fastmcp healthz

from fastapi import APIRouter, Depends, HTTPException, Body
from fastmcp import FastMCP, Client
import mcp

from server.api.v1.mcp import get_mcp
from server.mcp.prompts import cache
import server.api.utils.mcp as utils_mcp
import server.api.utils.settings as utils_settings

from common import logging_config

logger = logging_config.logging.getLogger("api.v1.mcp_prompts")

auth = APIRouter()


@auth.get(
    "/prompts",
    description="List MCP prompts",
    response_model=list[dict],
)
async def mcp_list_prompts(mcp_engine: FastMCP = Depends(get_mcp), full: bool = False) -> list[dict]:
    """List MCP Prompts

    Args:
        full: If True, include resolved text content. If False, return metadata only (MCP standard).
    """

    if full:
        # Return prompts with resolved text (default + overrides)
        prompts = await utils_settings.get_mcp_prompts_with_overrides(mcp_engine)
        logger.debug("MCP Prompts (full): %s", prompts)
        return [prompt.model_dump() for prompt in prompts]

    # Return MCP standard format (metadata only)
    prompts = await utils_mcp.list_prompts(mcp_engine)
    logger.debug("MCP Prompts (metadata): %s", prompts)

    prompts_info = []
    for prompts_object in prompts:
        if prompts_object.name.startswith("optimizer_"):
            prompts_info.append(prompts_object.model_dump())

    return prompts_info


@auth.get(
    "/prompts/{name}",
    description="Get MCP prompt",
    response_model=mcp.types.GetPromptResult,
)
async def mcp_get_prompt(name: str, mcp_engine: FastMCP = Depends(get_mcp)) -> mcp.types.GetPromptResult:
    """Get MCP Prompts"""
    try:
        client = Client(mcp_engine)
        async with client:
            prompt = await client.get_prompt(name=name)
            logger.debug("MCP Resources: %s", prompt)
    finally:
        await client.close()

    return prompt


@auth.patch(
    "/prompts/{name}",
    description="Update an existing MCP prompt text",
    response_model=dict,
)
async def mcp_update_prompt(
    name: str,
    payload: dict = Body(...),
    mcp_engine: FastMCP = Depends(get_mcp),
) -> dict:
    """Update an existing MCP prompt text while preserving title and tags"""
    logger.info("Updating MCP prompt: %s", name)

    instructions = payload.get("instructions")
    if instructions is None:
        raise HTTPException(status_code=400, detail="Missing 'instructions' in payload")

    try:
        # Verify the prompt exists
        client = Client(mcp_engine)
        async with client:
            prompts = await client.list_prompts()
            prompt_found = any(p.name == name for p in prompts)

            if not prompt_found:
                raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

        # Store the updated text in the shared cache
        # The prompt functions in defaults.py check this cache and return the override
        # This preserves the decorator metadata (title, tags) while updating the text
        cache.set_override(name, instructions)

        logger.info("Successfully updated MCP prompt text: %s", name)
        return {
            "message": f"Prompt '{name}' text updated successfully",
            "name": name,
        }

    except HTTPException:
        raise
    except Exception as ex:
        logger.error("Failed to update MCP prompt '%s': %s", name, ex)
        raise HTTPException(status_code=500, detail=f"Failed to update prompt: {str(ex)}") from ex


@auth.get(
    "/prompts/{name}/has-override",
    description="Check if a prompt has a cached override",
    response_model=dict,
)
async def mcp_check_prompt_override(name: str) -> dict:
    """Check if a prompt has been customized (has cache override)"""
    has_override = cache.get_override(name) is not None
    return {
        "name": name,
        "has_override": has_override,
    }


@auth.post(
    "/prompts/reset",
    description="Reset all MCP prompts to their default values",
    response_model=dict,
)
async def mcp_reset_prompts() -> dict:
    """Reset all MCP prompt overrides to their default values"""
    logger.info("Resetting all MCP prompt overrides")

    try:
        # Clear all prompt overrides from cache
        cache.clear_all_overrides()

        logger.info("Successfully reset all MCP prompt overrides")
        return {
            "message": "All prompts reset to default values successfully",
        }

    except Exception as ex:
        logger.error("Failed to reset MCP prompts: %s", ex)
        raise HTTPException(status_code=500, detail=f"Failed to reset prompts: {str(ex)}") from ex
