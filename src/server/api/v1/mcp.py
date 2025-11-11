"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
This file is being used in APIs, and not the backend.py file.
"""

# spell-checker:ignore noauth fastmcp healthz
from fastapi import APIRouter, Request, Depends, HTTPException
from fastmcp import FastMCP, Client
from fastmcp.prompts.prompt import PromptMessage, TextContent
import mcp

import server.api.utils.mcp as utils_mcp

from common import logging_config

logger = logging_config.logging.getLogger("api.v1.mcp")

auth = APIRouter()


def get_mcp(request: Request) -> FastMCP:
    """Get the MCP engine from the app state"""
    return request.app.state.fastmcp_app


@auth.get(
    "/client",
    description="Get MCP Client Configuration",
    response_model=dict,
)
async def get_client(server: str = None, port: int = None) -> dict:
    "Get MCP Client Configuration"
    return utils_mcp.get_client(server, port)


@auth.get(
    "/tools",
    description="List available MCP tools",
    response_model=list[dict],
)
async def get_tools(mcp_engine: FastMCP = Depends(get_mcp)) -> list[dict]:
    """List MCP tools"""
    tools_info = []
    try:
        client = Client(mcp_engine)
        async with client:
            tools = await client.list_tools()
            logger.debug("MCP Tools: %s", tools)
            for tool_object in tools:
                tools_info.append(tool_object.model_dump())
    finally:
        await client.close()

    return tools_info


@auth.get(
    "/resources",
    description="List MCP resources",
    response_model=list[dict],
)
async def mcp_list_resources(mcp_engine: FastMCP = Depends(get_mcp)) -> list[dict]:
    """List MCP Resources"""
    resources_info = []
    try:
        client = Client(mcp_engine)
        async with client:
            resources = await client.list_resources()
            logger.debug("MCP Resources: %s", resources)
            for resources_object in resources:
                resources_info.append(resources_object.model_dump())
    finally:
        await client.close()

    return resources_info


@auth.get(
    "/prompts",
    description="List MCP prompts",
    response_model=list[dict],
)
async def mcp_list_prompts(mcp_engine: FastMCP = Depends(get_mcp)) -> list[dict]:
    """List MCP Prompts"""
    prompts_info = []
    try:
        client = Client(mcp_engine)
        async with client:
            prompts = await client.list_prompts()
            logger.debug("MCP Resources: %s", prompts)
            for prompts_object in prompts:
                prompts_info.append(prompts_object.model_dump())
    finally:
        await client.close()

    return prompts_info


@auth.get(
    "/prompt/{prompt_name}",
    description="Get MCP prompt",
    response_model=mcp.types.GetPromptResult,
)
async def mcp_get_prompt(prompt_name: str, mcp_engine: FastMCP = Depends(get_mcp)) -> mcp.types.GetPromptResult:
    """Get MCP Prompts"""
    try:
        client = Client(mcp_engine)
        async with client:
            prompt = await client.get_prompt(name=prompt_name)
            logger.debug("MCP Resources: %s", prompt)
    finally:
        await client.close()

    return prompt


@auth.put(
    "/prompt/{prompt_name}",
    description="Update an existing MCP prompt text",
    response_model=dict,
)
async def mcp_update_prompt(
    prompt_name: str,
    prompt_text: str,
    mcp_engine: FastMCP = Depends(get_mcp),
) -> dict:
    """Update an existing MCP prompt with new text"""
    logger.info("Updating MCP prompt: %s", prompt_name)

    try:
        # Check if prompt exists (will raise 404 if not found)
        await mcp_get_prompt(prompt_name, mcp_engine)

        # Re-register the prompt (this will override the existing one)
        mcp_engine.prompt(name=prompt_name)(
            lambda: PromptMessage(role="assistant", content=TextContent(type="text", text=prompt_text))
        )

        logger.info("Successfully updated MCP prompt: %s", prompt_name)
        return {
            "message": f"Prompt '{prompt_name}' updated successfully",
            "name": prompt_name,
        }

    except HTTPException:
        raise
    except Exception as ex:
        logger.error("Failed to update MCP prompt '%s': %s", prompt_name, ex)
        raise HTTPException(status_code=500, detail=f"Failed to update prompt: {str(ex)}") from ex
