"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore apiserver pypath

import atexit
import logging
import os
import secrets
import subprocess
import sys
import time
from io import TextIOWrapper
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import streamlit as st

from client.app.core.settings import settings

LOGGER = logging.getLogger(__name__)

_SERVER: dict = {"process": None, "log_file": None}


def _spawn_server(port: str, env: dict, log_path: Path) -> tuple[subprocess.Popen, TextIOWrapper]:
    """Spawn a uvicorn server subprocess and return the Popen handle and log file."""
    LOGGER.info("Writing API Server logs to: %s", log_path)
    log_fh = log_path.open("a")
    proc = subprocess.Popen(  # keep handle open for uvicorn logging; closed in _stop_server
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
    LOGGER.info("Starting the AI Optimizer All-In-One mode...")
    proc = _SERVER["process"]
    if proc is not None and proc.poll() is None:
        return

    port = str(settings.server_port)
    src_dir = str(Path(__file__).resolve().parents[3])
    existing_pypath = os.environ.get("PYTHONPATH", "")
    pypath = f"{src_dir}{os.pathsep}{existing_pypath}" if existing_pypath else src_dir
    env = {**os.environ, "PYTHONPATH": pypath}

    # When no API key is configured, generate one so both client and server
    # share the same key.  Without this the server would auto-generate its
    # own key and the client would send an empty one → 403.
    if not settings.api_key:
        shared_key = secrets.token_urlsafe(32)
        env["AIO_API_KEY"] = shared_key
        os.environ["AIO_API_KEY"] = shared_key
        settings.api_key = shared_key
        LOGGER.info("Generated shared AIO API key for all-in-one mode.")

    log_path = Path(src_dir) / f"apiserver_{port}.log"
    proc, log_fh = _spawn_server(port, env, log_path)
    # Give the process a moment to fail on import/startup errors.
    try:
        proc.wait(timeout=2)
        log_fh.close()
        stderr = log_path.read_text()
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


def _base_url(api_prefix: str = "/v1") -> str:
    parsed = urlparse(settings.server_url)
    # Only inject the configured port when the URL doesn't already specify one
    port = parsed.port or settings.server_port
    netloc = f"{parsed.hostname}:{port}" if port else parsed.hostname
    path = (parsed.path.rstrip("/") + settings.server_url_prefix + api_prefix).rstrip("/")
    return urlunparse((parsed.scheme, netloc, path, "", "", ""))


def _headers() -> dict:
    return {"X-API-Key": settings.api_key or ""}


def api_get(
    path: str,
    params: dict | None = None,
    timeout: int = 10,
    api_prefix: str = "/v1",
    extra_headers: dict | None = None,
) -> Any:
    """GET request to the API server. Returns parsed JSON."""
    headers = {**_headers(), **(extra_headers or {})}
    with httpx.Client(headers=headers, timeout=timeout) as client:
        resp = client.get(f"{_base_url(api_prefix)}/{path.lstrip('/')}", params=params)
        resp.raise_for_status()
        return resp.json()


def api_post(
    path: str,
    json: dict | list | None = None,
    files: list[tuple] | None = None,
    data: dict | None = None,
    params: dict | None = None,
    toast: str | None = None,
    timeout: int = 10,
    api_prefix: str = "/v1",
    extra_headers: dict | None = None,
) -> dict:
    """POST request to the API server. Returns parsed JSON.

    When *files* or *data* are provided the request is sent as
    ``multipart/form-data`` instead of JSON.
    """
    headers = {**_headers(), **(extra_headers or {})}
    url = f"{_base_url(api_prefix)}/{path.lstrip('/')}"
    with httpx.Client(headers=headers, timeout=timeout) as client:
        if files is not None or data is not None:
            resp = client.post(url, files=files, data=data, params=params)
        else:
            resp = client.post(url, json=json, params=params)
        resp.raise_for_status()
        if toast:
            st.toast(toast, icon="✅")
        return resp.json()


def api_put(
    path: str,
    json: dict | None = None,
    toast: str | None = None,
    timeout: int = 10,
    api_prefix: str = "/v1",
    params: dict | None = None,
    extra_headers: dict | None = None,
) -> dict:
    """PUT request to the API server. Returns parsed JSON."""
    headers = {**_headers(), **(extra_headers or {})}
    with httpx.Client(headers=headers, timeout=timeout) as client:
        resp = client.put(f"{_base_url(api_prefix)}/{path.lstrip('/')}", json=json, params=params)
        resp.raise_for_status()
        if toast:
            st.toast(toast, icon="✅")
        return resp.json()


def api_patch(
    path: str,
    json: dict | None = None,
    toast: str | None = None,
    timeout: int = 10,
    api_prefix: str = "/v1",
    extra_headers: dict | None = None,
) -> Any:
    """PATCH request to the API server. Returns parsed JSON (or None for 204)."""
    headers = {**_headers(), **(extra_headers or {})}
    with httpx.Client(headers=headers, timeout=timeout) as client:
        resp = client.patch(f"{_base_url(api_prefix)}/{path.lstrip('/')}", json=json)
        resp.raise_for_status()
        if toast:
            st.toast(toast, icon="✅")
        return resp.json() if resp.content else None


def api_delete(
    path: str,
    toast: str | None = None,
    timeout: int = 10,
    api_prefix: str = "/v1",
    extra_headers: dict | None = None,
) -> None:
    """DELETE request to the API server. Expects 204 No Content."""
    headers = {**_headers(), **(extra_headers or {})}
    with httpx.Client(headers=headers, timeout=timeout) as client:
        resp = client.delete(f"{_base_url(api_prefix)}/{path.lstrip('/')}")
        resp.raise_for_status()
        if toast:
            st.toast(toast, icon="✅")


def get_server_settings(
    client: str,
    max_retries: int = 3,
    backoff_delays: list[int] | None = None,
    include_sensitive: bool = True,
) -> dict | None:
    """Fetch server settings (including database and OCI configs) from /settings.

    Retries up to ``max_retries`` times with exponential backoff if the server
    is not yet available.
    """
    if backoff_delays is None:
        backoff_delays = [2, 4, 6, 12, 15, 30]
    base = _base_url()
    headers = _headers()
    params = {"client": client, "include_sensitive": str(include_sensitive).lower()}

    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(headers=headers, timeout=5) as client_settings:
                resp = client_settings.get(f"{base}/settings", params=params)
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
