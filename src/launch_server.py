"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore fastapi laddr checkpointer langgraph litellm fastmcp getpid procs
# spell-checker:ignore noauth apiserver configfile selectai giskard ollama llms
# pylint: disable=redefined-outer-name,wrong-import-position

from contextlib import asynccontextmanager
import os

# Set OS Environment (Don't move their position to reflect on imports)
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["LITELLM_DISABLE_SPEND_LOGS"] = "True"
os.environ["LITELLM_DISABLE_SPEND_UPDATES"] = "True"
os.environ["LITELLM_DISABLE_END_USER_COST_TRACKING"] = "True"
os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["GSK_DISABLE_SENTRY"] = "true"
os.environ["GSK_DISABLE_ANALYTICS"] = "true"
os.environ["USER_AGENT"] = "ai-optimizer"
app_home = os.path.dirname(os.path.abspath(__file__))
if "TNS_ADMIN" not in os.environ:
    os.environ["TNS_ADMIN"] = os.path.join(app_home, "tns_admin")

# Patch litellm for Giskard/Ollama issue
import server.patches.litellm_patch  # pylint: disable=unused-import

import argparse

# import json
import queue
import secrets
import socket
import subprocess
import threading
from typing import Annotated
from pathlib import Path
import uvicorn


import psutil

# from client.mcp.client import MCPClient
from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastmcp import FastMCP, settings
from fastmcp.server.auth import StaticTokenVerifier

# Logging
import common.logging_config as logging_config
from common._version import __version__

# Configuration
import server.bootstrap.configfile as configfile
# from server.bootstrap import mcp as mcp_bootstrap

logger = logging_config.logging.getLogger("launch_server")


##########################################
# Process Control
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

    def start_subprocess(port: int, logfile: bool) -> subprocess.Popen:
        """Start the uvicorn server as a subprocess when started via the client."""
        logger.info("API server starting on port: %i", port)
        log_file = open(f"apiserver_{port}.log", "a", encoding="utf-8") if logfile else None
        stdout = stderr = log_file if logfile else subprocess.PIPE
        process = subprocess.Popen(
            [
                "uvicorn",
                "launch_server:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
                "--timeout-graceful-shutdown",
                "5",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        logger.info("API server started on Port: %i; PID: %i", port, process.pid)
        return process

    port = port or find_available_port()
    if existing_pid := get_pid_using_port(port):
        logger.info("API server already running on port: %i (PID: %i)", port, existing_pid)
        return existing_pid

    popen_queue = queue.Queue()
    thread = threading.Thread(
        target=lambda: popen_queue.put(start_subprocess(port, logfile)),
        daemon=True,
    )
    thread.start()

    return popen_queue.get().pid


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


def register_endpoints(mcp: FastMCP, auth: APIRouter, noauth: APIRouter):
    """Register API Endpoints - Imports to avoid bootstrapping before config file read
    New endpoints need to be registered in server.api.v1.__init__.py
    """
    # pylint: disable=import-outside-toplevel
    import server.api.v1 as api_v1
    from server.mcp import register_all_mcp

    # No-Authentication (probes only)
    noauth.include_router(api_v1.probes.noauth, prefix="/v1", tags=["Probes"])

    # Authenticated
    auth.include_router(api_v1.chat.auth, prefix="/v1/chat", tags=["Chatbot"])
    auth.include_router(api_v1.databases.auth, prefix="/v1/databases", tags=["Config - Databases"])
    auth.include_router(api_v1.embed.auth, prefix="/v1/embed", tags=["Embeddings"])
    auth.include_router(api_v1.models.auth, prefix="/v1/models", tags=["Config - Models"])
    auth.include_router(api_v1.oci.auth, prefix="/v1/oci", tags=["Config - Oracle Cloud Infrastructure"])
    auth.include_router(api_v1.prompts.auth, prefix="/v1/prompts", tags=["Tools - Prompts"])
    auth.include_router(api_v1.selectai.auth, prefix="/v1/selectai", tags=["SelectAI"])
    auth.include_router(api_v1.settings.auth, prefix="/v1/settings", tags=["Tools - Settings"])
    auth.include_router(api_v1.testbed.auth, prefix="/v1/testbed", tags=["Tools - Testbed"])
    auth.include_router(api_v1.mcp.auth, prefix="/v1/mcp", tags=["Config - MCP Servers"])

    # Auto-discover all MCP tools and register HTTP + MCP endpoints
    mcp_router = APIRouter(prefix="/mcp", tags=["MCP Tools"])
    register_all_mcp(mcp, auth)
    auth.include_router(mcp_router)


#############################################################################
# APP FACTORY
#############################################################################
def create_app(config: str = "") -> FastAPI:
    """Create and configure the FastAPI app."""

    def fastapi_verify_key(
        http_auth: Annotated[
            HTTPAuthorizationCredentials,
            Depends(HTTPBearer(description="Please provide API_SERVER_KEY.")),
        ],
    ) -> None:
        """FastAPI: Verify that the provided API key is correct."""
        if http_auth.credentials != get_api_key():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    ### Start
    if not config:
        config = configfile.config_file_path()
    config_file = Path(os.getenv("CONFIG_FILE", config))
    configfile.ConfigStore.load_from_file(config_file)

    fastmcp_verifier = StaticTokenVerifier(
        tokens={get_api_key(): {"client_id": "optimizer", "scopes": ["read", "write"]}}
    )

    # MCP Server
    settings.stateless_http = True
    mcp = FastMCP(name="Optimizer MCP Server", auth=fastmcp_verifier)
    mcp_app = mcp.http_app(path="/")

    @asynccontextmanager
    async def combined_lifespan(app):
        async with mcp_app.lifespan(app):
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

    # API Server
    app = FastAPI(
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
    app.state.mcp = mcp

    # Setup Routes and Register non-MCP endpoints
    noauth = APIRouter()
    auth = APIRouter(dependencies=[Depends(fastapi_verify_key)])

    register_endpoints(mcp, auth, noauth)

    # Register MCP Server into FastAPI
    app.mount("/mcp", mcp_app)

    app.include_router(noauth)
    app.include_router(auth)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=configfile.config_file_path(),
        help="Full path to configuration file (JSON)",
    )
    args = parser.parse_args()

    PORT = int(os.getenv("API_SERVER_PORT", "8000"))
    logger.info("API Server Using port: %i", PORT)

    app = create_app(args.config)
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=PORT,
            timeout_graceful_shutdown=5,
            log_config=logging_config.LOGGING_CONFIG,
        )
    except Exception as ex:
        logger.info("Forced Shutdown: %s", ex)
