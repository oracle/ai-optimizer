"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore fastapi laddr checkpointer langgraph litellm
# spell-checker:ignore noauth apiserver configfile selectai giskard ollama llms
# pylint: disable=redefined-outer-name,wrong-import-position

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
import json
import queue
import secrets
import socket
import subprocess
import threading
from typing import Annotated, Any, Dict, Optional
from pathlib import Path
import uvicorn
from contextlib import asynccontextmanager

import psutil

from client.mcp.client import MCPClient
from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# Logging
import common.logging_config as logging_config
from common._version import __version__

# Configuration
import server.bootstrap.configfile as configfile
from server.bootstrap import mcp as mcp_bootstrap

logger = logging_config.logging.getLogger("launch_server")
mcp_engine: Optional[MCPClient] = None

def get_mcp_engine() -> Optional[MCPClient]:
    """Get the current MCP engine instance."""
    global mcp_engine
    logger.debug(f"get_mcp_engine() called, returning: {mcp_engine}")
    # Additional debugging to check if the variable exists
    if 'mcp_engine' in globals():
        print(f"DEBUG: mcp_engine in globals: {globals().get('mcp_engine')}")
    else:
        print("DEBUG: mcp_engine not in globals")
    # Print the module name to see which module this is
    print(f"DEBUG: This is module: {__name__}")
    return mcp_engine

async def initialize_mcp_engine_with_model(model_name: str) -> Optional[MCPClient]:
    """Initialize or reinitialize the MCP engine with a specific model."""
    global mcp_engine
    
    # Clean up existing engine if it exists
    if mcp_engine:
        try:
            await mcp_engine.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up existing MCP engine: {e}")
    
    # Initialize new engine with the specified model
    try:
        mcp_engine = MCPClient(client_settings={'ll_model': {'model': model_name}})
        logger.info("MCP Client created with model %s, connecting to servers...", model_name)
        await mcp_engine.connect_to_servers()
        logger.info("MCP Engine initialized successfully with model %s", model_name)
        return mcp_engine
    except Exception as e:
        logger.error(f"Failed to initialize MCP Engine with model {model_name}: {e}", exc_info=True)
        mcp_engine = None
        return None

class McpToolCallRequest(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any]

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
        """Start the uvicorn server as a subprocess."""
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
    """Stop the uvicorn server for FastAPI."""
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


def verify_key(
    http_auth: Annotated[
        HTTPAuthorizationCredentials,
        Depends(HTTPBearer(description="Please provide API_SERVER_KEY.")),
    ],
) -> None:
    """Verify that the provided API key is correct."""
    if http_auth.credentials != get_api_key():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


def register_endpoints(noauth: APIRouter, auth: APIRouter):
    """Register API Endpoints - Imports to avoid bootstrapping before config file read
    New endpoints need to be registered in server.api.v1.__init__.py
    """
    import server.api.v1 as api_v1  # pylint: disable=import-outside-toplevel

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


#############################################################################
# APP FACTORY
#############################################################################
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI startup/shutdown lifecycle for the MCP Engine."""
    logger.info("Starting API Server...")
    global mcp_engine

    # Define a single, authoritative path for the configuration file.
    config_path = Path("server/etc/mcp_config.json")

    # 1. Handle the missing configuration file as a critical error.
    if not config_path.exists():
        logger.error(
            f"CRITICAL: MCP configuration file not found at '{config_path}'. "
            "MCP Engine cannot be initialized."
        )
        # Yield control to allow the server to run, but without the MCP engine.
        yield
        return

    # 2. Load the configuration and initialize the engine.
    try:
        logger.info(f"Loading MCP configuration from '{config_path}'...")
        with open(config_path, encoding='utf-8') as f:
            mcp_config = json.load(f)
        
        mcp_bootstrap.load_mcp_settings(mcp_config)

        # 3. Check if MCP is enabled in the loaded configuration.
        if mcp_bootstrap.MCP_SETTINGS and mcp_bootstrap.MCP_SETTINGS.enabled:
            logger.info("MCP is enabled. Initializing MCP Engine...")
            
            # This structure assumes MCPClient can be initialized with just the default model.
            client_init_settings = {
                'll_model': {'model': mcp_bootstrap.MCP_SETTINGS.default_model}
            }
            mcp_engine = MCPClient(client_settings=client_init_settings)
            
            await mcp_engine.connect_to_servers()
            logger.info("MCP Engine initialized successfully.")
        else:
            logger.warning("MCP is disabled in the configuration file. Skipping initialization.")

    except Exception as e:
        logger.error(f"Failed to initialize MCP Engine from configuration: {e}", exc_info=True)
        # Ensure the engine is not set if initialization fails.
        mcp_engine = None
    
    # Yield control to the running application.
    yield

    # Shutdown the engine if it was successfully initialized.
    if mcp_engine:
        logger.info("Shutting down MCP Engine...")
        try:
            await mcp_engine.cleanup()
            logger.info("MCP Engine cleanup completed.")
        except Exception as e:
            logger.error(f"Error during MCP Engine cleanup: {e}")

def create_app(config: str = "") -> FastAPI:
    """Create and configure the FastAPI app."""
    if not config:
        config = configfile.config_file_path()
    config_file = Path(os.getenv("CONFIG_FILE", config))
    configfile.ConfigStore.load_from_file(config_file)

    app = FastAPI(
        title="Oracle AI Optimizer and Toolkit",
        version=__version__,
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
        lifespan=lifespan,
        license_info={
            "name": "Universal Permissive License",
            "url": "http://oss.oracle.com/licenses/upl",
        },
    )

    noauth = APIRouter()
    auth = APIRouter(dependencies=[Depends(verify_key)])

    # Register Endpoints
    register_endpoints(noauth, auth)
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
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_config=logging_config.LOGGING_CONFIG)
