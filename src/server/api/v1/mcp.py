"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
This file is being used in APIs, and not the backend.py file.
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.mcp")

auth = APIRouter()

def mcp_engine_obj():
    """Check if the MCP engine is initialized."""
    try:
        from launch_server import get_mcp_engine
        mcp_engine = get_mcp_engine()
    except ImportError:
        return None
    return mcp_engine

class McpToolCallRequest(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any]

class ChatRequest(BaseModel):
    query: str
    prompt_name: Optional[str] = None
    resource_uri: Optional[str] = None
    message_history: Optional[list] = None

@auth.get(
    "/tools",
    description="List available MCP tools",
    response_model=dict
)
async def list_mcp_tools():
    # Import here to avoid circular imports
    mcp_engine = mcp_engine_obj()
    if not mcp_engine:
        raise HTTPException(status_code=503, detail="MCP Engine not initialized.")
    try:
        await mcp_engine._rebuild_mcp_tool_schemas()
    except Exception as e:
        logger.error(f"Error rebuilding tool schemas: {e}")
    
    tools_info = []
    for tool_name, (session, tool_object) in mcp_engine.tool_to_session.items():
        tools_info.append({
            "name": tool_object.name,
            "description": tool_object.description,
            "input_schema": tool_object.inputSchema
        })
    return {"tools": tools_info}

@auth.post(
    "/execute",
    description="Execute an MCP tool",
    response_model=dict
)
async def execute_mcp_tool(request: McpToolCallRequest):
    # Import here to avoid circular imports
    mcp_engine = mcp_engine_obj()
    if not mcp_engine:
        raise HTTPException(status_code=503, detail="MCP Engine not initialized.")
    try:
        result = await mcp_engine.execute_mcp_tool(request.tool_name, request.tool_args)
        return {"result": result}
    except Exception as e:
        logger.error(f"Error executing MCP tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@auth.post(
    "/chat",
    description="Chat with MCP engine",
    response_model=dict
)
async def chat_endpoint(request: ChatRequest):
    mcp_engine = mcp_engine_obj()
    if not mcp_engine:
        raise HTTPException(status_code=503, detail="MCP Engine not initialized.")
    try:
        message_history = request.message_history or [{"role": "user", "content": request.query}]
        response_text, _ = await mcp_engine.invoke(
            message_history=message_history
        )
        return {"response": response_text}
    except Exception as e:
        logger.error(f"Error in MCP chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@auth.get(
    "/resources",
    description="List MCP resources",
    response_model=dict
)
async def list_resources():
    # Import here to avoid circular imports
    mcp_engine = mcp_engine_obj()
    if not mcp_engine:
        raise HTTPException(status_code=503, detail="MCP Engine not initialized.")
    
    try:
        # This will trigger loading if not already loaded
        _ = await mcp_engine._rebuild_mcp_tool_schemas()
    except Exception as e:
        logger.error(f"Error loading resources: {e}")
    
    return {
        "static": list(getattr(mcp_engine, "static_resources", {}).keys()),
        "dynamic": getattr(mcp_engine, "dynamic_resources", [])
    }

@auth.get(
    "/prompts",
    description="List MCP prompts",
    response_model=dict
)
async def list_prompts():
    mcp_engine = mcp_engine_obj()
    if not mcp_engine:
        raise HTTPException(status_code=503, detail="MCP Engine not initialized.")
    try:
        # This will trigger loading if not already loaded
        _ = await mcp_engine._rebuild_mcp_tool_schemas()
    except Exception as e:
        logger.error(f"Error loading prompts: {e}")
    
    return {
        "prompts": list(getattr(mcp_engine, "available_prompts", {}).keys())
    }

@auth.get("/health", response_model=dict)
async def health_check():
    """Check MCP engine health status"""
    actual_mcp_engine = mcp_engine_obj()
    return {
        "status": "initialized" if actual_mcp_engine else "not_initialized",
        "engine_type": str(type(actual_mcp_engine)) if actual_mcp_engine else None,
        "available_tools": len(getattr(actual_mcp_engine, "available_tools", [])) if actual_mcp_engine else 0,
        "timestamp": datetime.now().isoformat()
    }
