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
    return request.app.state.mcp


@auth.get(
    "/tools",
    description="List available MCP tools",
    response_model=dict,
)
async def mcp_get_tools(mcp_engine: FastMCP = Depends(get_mcp)) -> dict:
    """List MCP tools"""
    tools_info = []
    try:
        client = Client(mcp_engine)
        async with client:
            tools = await client.list_tools()
            logger.debug("MCP Tools: %s", tools)
            for tool_object in tools:
                tools_info.append(
                    {
                        "name": tool_object.name,
                        "description": tool_object.description,
                        "input_schema": getattr(tool_object, "inputSchema", None),
                    }
                )
    finally:
        await client.close()

    return {"tools": tools_info}


@auth.get(
    "/resources",
    description="Get MCP resources",
    response_model=dict,
)
async def mcp_get_resources(mcp_engine: FastMCP = Depends(get_mcp)) -> dict:
    """Get MCP Resources"""
    resources = await mcp_engine.get_resources()
    logger.debug("MCP Resources: %s", resources)
    return {
        "static": list(getattr(mcp_engine, "static_resources", {}).keys()),
        "dynamic": getattr(mcp_engine, "dynamic_resources", []),
    }


@auth.get(
    "/prompts",
    description="Get MCP prompts",
    response_model=dict,
)
async def mcp_get_prompts(mcp_engine: FastMCP = Depends(get_mcp)) -> dict:
    """Get MCP prompts"""
    prompts = await mcp_engine.get_prompts()
    logger.debug("MCP Prompts: %s", prompts)
    return {"prompts": list(getattr(mcp_engine, "available_prompts", {}).keys())}


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
