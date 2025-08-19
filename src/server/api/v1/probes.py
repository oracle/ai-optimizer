"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker:ignore noauth fastmcp healthz
from datetime import datetime
from fastapi import APIRouter, Request, Depends
from fastmcp import FastMCP

noauth = APIRouter()


def get_mcp(request: Request) -> FastMCP:
    """Get the MCP engine from the app state"""
    return request.app.state.fastmcp_app


@noauth.get("/liveness")
async def liveness_probe():
    """Kubernetes liveness probe"""
    return {"status": "alive"}


@noauth.get("/readiness")
async def readiness_probe():
    """Kubernetes readiness probe"""
    return {"status": "ready"}


@noauth.get("/mcp/healthz")
def mcp_healthz(mcp_engine: FastMCP = Depends(get_mcp)):
    """Check if MCP server is ready."""
    if mcp_engine is None:
        return {"status": "not ready"}
    else:
        server = mcp_engine.__dict__["_mcp_server"].__dict__
        return {
            "status": "ready",
            "name": server["name"],
            "version": server["version"],
            "available_tools": len(getattr(mcp_engine, "available_tools", [])) if mcp_engine else 0,
            "timestamp": datetime.now().isoformat(),
        }
