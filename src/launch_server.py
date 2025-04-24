"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore fastapi, laddr, checkpointer, langgraph, litellm, noauth
# pylint: disable=redefined-outer-name,wrong-import-position

import os

# Set OS Environment (Don't move their position to reflect on imports)
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["GSK_DISABLE_SENTRY"] = "true"
os.environ["GSK_DISABLE_ANALYTICS"] = "true"
os.environ["USER_AGENT"] = "ai-optimizer"
app_home = os.path.dirname(os.path.abspath(__file__))
if "TNS_ADMIN" not in os.environ:
    os.environ["TNS_ADMIN"] = os.path.join(app_home, "tns_admin")

import queue
import secrets
import socket
import subprocess
import threading
from typing import Annotated
import uvicorn

import psutil

from fastapi import FastAPI, HTTPException, Depends, status, APIRouter
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Logging
import common.logging_config as logging_config

# Endpoints
from server.endpoints import register_endpoints

logger = logging_config.logging.getLogger("launch_server")


##########################################
# Process Control
##########################################
def start_server(port: int = 8000) -> int:
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

    def start_subprocess(port: int) -> subprocess.Popen:
        """Start the uvicorn server as a subprocess."""
        logger.info("API server starting on port: %i", port)
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("API server started on Port: %i; PID: %i", port, process.pid)
        return process

    port = port or find_available_port()
    existing_pid = get_pid_using_port(port)
    if existing_pid:
        logger.info("API server already running on port: %i (PID: %i)", port, existing_pid)
        return existing_pid

    popen_queue = queue.Queue()
    thread = threading.Thread(
        target=lambda: popen_queue.put(start_subprocess(port)),
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
    except (psutil.NoSuchProcess, psutil.AccessDenied) as ex:
        logger.error("Failed to terminate process with PID: %i - %s", pid, ex)

    logger.info("API server stopped.")


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


#############################################################################
# APP FACTORY
#############################################################################
def create_app() -> FastAPI:
    """Create and configure the FastAPI app."""
    app = FastAPI(
        title="Oracle AI Optimizer and Toolkit",
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
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
    PORT = int(os.getenv("API_SERVER_PORT", "8000"))
    logger.info("API Server Using port: %i", PORT)

    endpoints.load_shared_objects()
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
