"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore apiserver

import atexit
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

LOGGER = logging.getLogger(__name__)

_SERVER: dict = {"process": None, "log_file": None}


def _spawn_server(port: str, env: dict) -> tuple[subprocess.Popen, "IO"]:
    """Spawn a uvicorn server subprocess and return the Popen handle and log file."""
    log_path = Path(f"apiserver_{port}.log")
    log_fh = log_path.open("a")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            port,
        ],
        env=env,
        stdout=log_fh,
        stderr=log_fh,
    )
    return proc, log_fh


def start_server() -> None:
    """Start the server as a subprocess."""
    proc = _SERVER["process"]
    if proc is not None and proc.poll() is None:
        return

    port = os.getenv("AIO_SERVER_PORT", "8000")
    src_dir = str(Path(__file__).resolve().parents[3])
    env = {**os.environ, "PYTHONPATH": src_dir}

    proc, log_fh = _spawn_server(port, env)
    log_path = f"apiserver_{port}.log"
    # Give the process a moment to fail on import/startup errors.
    try:
        proc.wait(timeout=2)
        log_fh.close()
        stderr = Path(log_path).read_text()
        LOGGER.error(
            "Server process exited immediately (code %d). PYTHONPATH=%s\nSee %s\n%s",
            proc.returncode,
            src_dir,
            log_path,
            stderr.strip(),
        )
        return
    except subprocess.TimeoutExpired:
        pass  # Still running — expected.

    _SERVER["process"] = proc
    _SERVER["log_file"] = log_fh
    atexit.register(_stop_server)


def _stop_server() -> None:
    """Terminate the server subprocess if it is still running."""
    proc = _SERVER["process"]
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    _SERVER["process"] = None
    log_fh = _SERVER["log_file"]
    if log_fh:
        log_fh.close()
    _SERVER["log_file"] = None


def _base_url() -> str:
    port = os.getenv("AIO_SERVER_PORT", "8000")
    prefix = os.getenv("AIO_SERVER_URL_PREFIX", "")
    return f"http://localhost:{port}{prefix}/v1"


def _headers() -> dict:
    return {"X-API-Key": os.getenv("AIO_API_KEY", "")}


def get_server_settings(
    max_retries: int = 5,
    backoff_delays: list[int] | None = None,
    include_secrets: bool = False,
) -> dict | None:
    """Fetch server settings (including database and OCI configs) from /settings.

    Retries up to ``max_retries`` times with exponential backoff if the server
    is not yet available.
    """
    if backoff_delays is None:
        backoff_delays = [2, 4, 8, 16, 30]
    base = _base_url()
    headers = _headers()
    params = {"include_secrets": "true"} if include_secrets else {}

    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(headers=headers, timeout=5) as client:
                resp = client.get(f"{base}/settings", params=params)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError:
            if attempt < max_retries:
                delay = backoff_delays[attempt]
                LOGGER.warning(
                    "Server not ready, retrying in %ds (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(delay)
            else:
                LOGGER.error(
                    "Failed to fetch server settings from %s after %d attempts",
                    base,
                    max_retries + 1,
                )
                return None
    return None
