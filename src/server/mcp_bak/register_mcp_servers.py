from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from mcp.server import Server
import json

def mount_mcp(router: APIRouter, prefix: str, mcp_server: Server):
    @router.get(f"{prefix}/.well-known/mcp.json")
    async def manifest():
        return JSONResponse(content=mcp_server.manifest.dict())

    @router.post(f"{prefix}/mcp")
    async def mcp_api(request: Request):
        body = await request.body()
        resp = mcp_server.handle_http(body)
        try:
            return JSONResponse(content=json.loads(resp))
        except Exception:
            return PlainTextResponse(content=resp)

def register_mcp_servers(app: FastAPI):
    # Create routers for MCP endpoints
    mcp_router = APIRouter()

    # Define MCP servers
    mcp_sqlcl = Server(name="Built-in SQLcl MCP Server")

    # Example tools
    @mcp.tool()
    def greet(name: str) -> str:
        return f"Hello from MCP Server One, {name}!"

    # Mount MCP servers into the router under prefixes
    mount_mcp(app, "/mcp_sqlcl", mcp_sqlcl)

    # Include the MCP router into the main app
    app.include_router(mcp_router)