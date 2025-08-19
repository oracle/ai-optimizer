"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
This file is being used in APIs, and not the backend.py file.
"""

# spell-checker:ignore noauth fastmcp healthz
from fastapi import APIRouter, Request, Depends
from fastmcp import FastMCP, Client

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.v1.mcp")

auth = APIRouter()


def get_mcp(request: Request) -> FastMCP:
    """Get the MCP engine from the app state"""
    return request.app.state.fastmcp_app


@auth.get(
    "/tools",
    description="List available MCP tools",
    response_model=list[dict],
)
async def mcp_get_tools(mcp_engine: FastMCP = Depends(get_mcp)) -> list[dict]:
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


# @auth.post("/execute", description="Execute an MCP tool", response_model=dict)
# async def mcp_execute_tool(request: McpToolCallRequest):
#     """Execute MCP Tool"""
#     mcp_engine = mcp_engine_obj()
#     if not mcp_engine:
#         raise HTTPException(status_code=503, detail="MCP Engine not initialized.")
#     try:
#         result = await mcp_engine.execute_mcp_tool(request.tool_name, request.tool_args)
#         return {"result": result}
#     except Exception as ex:
#         logger.error("Error executing MCP tool: %s", ex)
#         raise HTTPException(status_code=500, detail=str(ex)) from ex


# @auth.post("/chat", description="Chat with MCP engine", response_model=dict)
# async def chat_endpoint(request: ChatRequest):
#     """Chat with MCP Engine"""
#     mcp_engine = mcp_engine_obj()
#     if not mcp_engine:
#         raise HTTPException(status_code=503, detail="MCP Engine not initialized.")
#     try:
#         message_history = request.message_history or [{"role": "user", "content": request.query}]
#         response_text, _ = await mcp_engine.invoke(message_history=message_history)
#         return {"response": response_text}
#     except Exception as ex:
#         logger.error("Error in MCP chat: %s", ex)
#         raise HTTPException(status_code=500, detail=str(ex)) from ex
