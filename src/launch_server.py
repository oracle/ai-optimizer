"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore configfile fastmcp noauth getpid procs litellm giskard ollama
# spell-checker:ignore dotenv apiserver laddr

# Patch litellm for Giskard/Ollama issue
import server.patches.litellm_patch  # pylint: disable=unused-import, wrong-import-order

# Set OS Environment before importing other modules
# Set OS Environment (Don't move their position to reflect on imports)
# pylint: disable=wrong-import-position
import os

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["GSK_DISABLE_SENTRY"] = "true"
os.environ["GSK_DISABLE_ANALYTICS"] = "true"
os.environ["USER_AGENT"] = "ai-optimizer"
app_home = os.path.dirname(os.path.abspath(__file__))
if "TNS_ADMIN" not in os.environ:
    os.environ["TNS_ADMIN"] = os.path.join(app_home, "tns_admin")
# pylint: enable=wrong-import-position

import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from typing import Annotated
import uvicorn

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastmcp import FastMCP, settings
from fastmcp.server.auth import StaticTokenVerifier
import psutil

# Configuration
from server.bootstrap import configfile  # pylint: disable=ungrouped-imports

# Logging
from common import logging_config
from common._version import __version__

logger = logging_config.logging.getLogger("launch_server")


##########################################
# Client Process Control
##########################################
def start_server(port: int = 8000, logfile: bool = False) -> int:
    """Start the uvicorn server for FastAPI"""
    logger.info("Starting Oracle AI Optimizer and Toolkit")

    def find_available_port() -> int:
        """If port 8000 is not available, find another open one"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("0.0.0.0", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def get_pid_using_port(port: int) -> int:
        """Find the PID of the process using the specified port."""
        for proc in psutil.process_iter(attrs=["pid", "name"]):
            try:
                for conn in proc.net_connections(kind="inet"):
                    if conn.status == "LISTEN" and conn.laddr.port == port:
                        return proc.info["pid"]
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return None

    port = port or find_available_port()
    if existing_pid := get_pid_using_port(port):
        logger.info("API server already running on port: %i (PID: %i)", port, existing_pid)
        return existing_pid

    client_args = [sys.executable, __file__, "--port", str(port)]
    if logfile:
        log_file = open(f"apiserver_{port}.log", "a", encoding="utf-8")  # pylint: disable=consider-using-with
        stdout = stderr = log_file
    else:
        stdout = stderr = subprocess.PIPE

    process = subprocess.Popen(client_args, stdout=stdout, stderr=stderr)  # pylint: disable=consider-using-with
    logger.info("Server started on port %i with PID %i", port, process.pid)
    return process.pid


def stop_server(pid: int) -> None:
    """Stop the uvicorn server for FastAPI when started via the client"""
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait()
        logger.info("API server stopped.")
    except (psutil.NoSuchProcess, psutil.AccessDenied) as ex:
        logger.error("Failed to terminate process with PID: %i - %s", pid, ex)


##########################################
# Server App and API Key
##########################################
def generate_auth_key(length: int = 32) -> str:
    """Generate and return a URL-safe API key."""
    return secrets.token_urlsafe(length)


def get_api_key() -> str:
    """Retrieve API key from environment or generate one."""
    if not os.getenv("API_SERVER_KEY"):
        logger.info("API_SERVER_KEY not set; generating.")
        os.environ["API_SERVER_KEY"] = generate_auth_key()
    return os.getenv("API_SERVER_KEY")


def fastapi_verify_key(
    http_auth: Annotated[
        HTTPAuthorizationCredentials,
        Depends(HTTPBearer(description="Please provide API_SERVER_KEY.")),
    ],
) -> None:
    """FastAPI: Verify that the provided API key is correct."""
    if http_auth.credentials != get_api_key():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


##########################################
# Endpoint Registration
##########################################
async def register_endpoints(mcp: FastMCP, auth: APIRouter, noauth: APIRouter):
    """Register API Endpoints - Imports to avoid bootstrapping before config file read
    New endpoints need to be registered in server.api.v1.__init__.py
    """
    logger.debug("Starting Endpoint Registration")
    # pylint: disable=import-outside-toplevel
    import server.api.v1 as api_v1
    from server.mcp import register_all_mcp

    # No-Authentication (probes only)
    noauth.include_router(api_v1.probes.noauth, prefix="/v1", tags=["Probes"])

    # Authenticated
    auth.include_router(api_v1.chat.auth, prefix="/v1/chat", tags=["Chatbot"])
    auth.include_router(api_v1.embed.auth, prefix="/v1/embed", tags=["Embeddings"])
    auth.include_router(api_v1.selectai.auth, prefix="/v1/selectai", tags=["SelectAI"])
    auth.include_router(api_v1.mcp_prompts.auth, prefix="/v1/mcp", tags=["Tools - MCP Prompts"])
    auth.include_router(api_v1.testbed.auth, prefix="/v1/testbed", tags=["Tools - Testbed"])
    auth.include_router(api_v1.settings.auth, prefix="/v1/settings", tags=["Config - Settings"])
    auth.include_router(api_v1.databases.auth, prefix="/v1/databases", tags=["Config - Databases"])
    auth.include_router(api_v1.models.auth, prefix="/v1/models", tags=["Config - Models"])
    auth.include_router(api_v1.oci.auth, prefix="/v1/oci", tags=["Config - Oracle Cloud Infrastructure"])
    auth.include_router(api_v1.mcp.auth, prefix="/v1/mcp", tags=["Config - MCP Servers"])

    # Auto-discover all MCP tools and register HTTP + MCP endpoints
    mcp_router = APIRouter(prefix="/mcp", tags=["MCP Tools"])
    await register_all_mcp(mcp, auth)
    auth.include_router(mcp_router)
    logger.debug("Finished Endpoint Registration")


#############################################################################
# APP FACTORY
#############################################################################
async def create_app(config: str = "") -> FastAPI:
    """FastAPI Application Factory"""

    if not config:
        config = configfile.config_file_path()
    config_file = Path(os.getenv("CONFIG_FILE", config))
    configfile.ConfigStore.load_from_file(config_file)

    # FastMCP Server
    fastmcp_verifier = StaticTokenVerifier(
        tokens={get_api_key(): {"client_id": "optimizer", "scopes": ["read", "write"]}}
    )
    settings.stateless_http = True
    fastmcp_app = FastMCP(
        name="Oracle AI Optimizer and Toolkit MCP Server",
        version=__version__,
        auth=fastmcp_verifier,
        include_fastmcp_meta=False,
    )
    fastmcp_engine = fastmcp_app.http_app(path="/")

    @asynccontextmanager
    async def combined_lifespan(fastapi_app: FastAPI):
        """Ensures all MCP Servers are cleaned up"""
        async with fastmcp_engine.lifespan(fastapi_app):
            yield
        # Shutdown cleanup
        logger.info("Cleaning up leftover processes...")
        parent = psutil.Process(os.getpid())
        children = parent.children(recursive=True)
        for p in children:
            try:
                p.terminate()
            except psutil.NoSuchProcess:
                continue
        # Wait synchronously, outside the event loop
        _, still_alive = psutil.wait_procs(children, timeout=3)
        for p in still_alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                continue

    # FastAPI Server
    fastapi_app = FastAPI(
        title="Oracle AI Optimizer and Toolkit",
        version=__version__,
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
        lifespan=combined_lifespan,
        license_info={
            "name": "Universal Permissive License",
            "url": "http://oss.oracle.com/licenses/upl",
        },
    )
    # Store MCP in the app state
    fastapi_app.state.fastmcp_app = fastmcp_app
    # Register MCP Server into FastAPI
    fastapi_app.mount("/mcp", fastmcp_engine)

    # Setup Routes and Register non-MCP endpoints
    noauth = APIRouter()
    auth = APIRouter(dependencies=[Depends(fastapi_verify_key)])

    # Register the endpoints
    await register_endpoints(fastmcp_app, auth, noauth)
    fastapi_app.include_router(noauth)
    fastapi_app.include_router(auth)

    return fastapi_app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=configfile.config_file_path(),
        help="Full path to configuration file (JSON)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to start server",
    )
    args = parser.parse_args()

    PORT = int(os.getenv("API_SERVER_PORT", "8000"))
    logger.info("API Server Using port: %i", PORT)

    # Sync entrypoint, but calls async factory before running Uvicorn
    app = asyncio.run(create_app(args.config))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        timeout_graceful_shutdown=5,
        log_config=logging_config.LOGGING_CONFIG,
    )
