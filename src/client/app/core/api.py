"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore apiserver pypath

import atexit
import json
import logging
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Generator
from io import TextIOWrapper
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import streamlit as st
from pydantic import SecretStr

from client.app.core.secrets import reveal
from client.app.core.settings import settings
from entrypoint import ensure_ssl_cert

LOGGER = logging.getLogger(__name__)

_SERVER: dict = {"process": None, "log_file": None}

_SERVER_READY_TIMEOUT_SECONDS = float(os.environ.get("AIO_SERVER_READY_TIMEOUT", "180"))
_SERVER_READY_POLL_INTERVAL = 5.0


_SRC_DIR = Path(__file__).resolve().parents[3]


def _server_module_available() -> bool:
    """The spawn path runs `uvicorn server.app.main:app`, which only resolves
    when the server source ships in this image. Component-specific Docker
    images and Helm split-pod deployments strip the unused tree (mirrors
    entrypoint.py:detect_component), so an absent `server/` directory is
    hard proof that the server is running in another process or pod."""
    return (_SRC_DIR / "server").is_dir()


def _spawn_server(port: str, env: dict, log_path: Path) -> tuple[subprocess.Popen, TextIOWrapper]:
    """Spawn a uvicorn server subprocess and return the Popen handle and log file."""
    LOGGER.info("Writing API Server logs to: %s", log_path)
    log_fh = log_path.open("a")
    args = [
        sys.executable,
        "-m",
        "uvicorn",
        "server.app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]

    if settings.server_ssl:
        cert, key = ensure_ssl_cert(_SRC_DIR, "AIO_SERVER_SSL_CERT_FILE", "AIO_SERVER_SSL_KEY_FILE")
        args.extend(["--ssl-certfile", str(cert), "--ssl-keyfile", str(key)])

    proc = subprocess.Popen(  # keep handle open for uvicorn logging; closed in _stop_server
        args,
        env=env,
        stdout=log_fh,
        stderr=log_fh,
    )
    return proc, log_fh


def _wait_for_server_ready(proc: subprocess.Popen, timeout: float = _SERVER_READY_TIMEOUT_SECONDS) -> bool:
    """Poll the no-auth liveness endpoint until it responds or the process exits.

    The probe is independent of the server's log level (unlike scraping uvicorn
    stderr). Returns True once /liveness returns 200, False if the subprocess
    exits early or the timeout is reached.
    """
    url = f"{_local_server_base_url()}/liveness"
    request_kwargs: dict[str, Any] = {"timeout": 1.0}
    if settings.server_ssl:
        request_kwargs["verify"] = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            resp = httpx.get(url, **request_kwargs)
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(_SERVER_READY_POLL_INTERVAL)
    return False


def start_server() -> None:
    """Start the server as a subprocess."""
    if not _server_module_available():
        LOGGER.info("Server source not present in this image; skipping local spawn.")
        return
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
        settings.api_key = SecretStr(shared_key)
        LOGGER.info("Generated shared AIO API key for all-in-one mode.")

    log_path = Path(src_dir) / f"apiserver_{port}.log"
    proc, log_fh = _spawn_server(port, env, log_path)

    # Track the subprocess immediately so it isn't killed on timeout — slow
    # imports (langchain, etc.) can push first-byte well past any sane wait,
    # and the next Streamlit rerun will pick it up once it's actually ready.
    _SERVER["process"] = proc
    _SERVER["log_file"] = log_fh
    atexit.register(_stop_server)

    if not _wait_for_server_ready(proc):
        if proc.poll() is not None:
            stderr = log_path.read_text()
            LOGGER.error(
                "Server process exited (code %d). PYTHONPATH=%s\nSee %s\n%s",
                proc.returncode,
                src_dir,
                log_path,
                stderr.strip(),
            )
            _SERVER["process"] = None
            log_fh.close()
            _SERVER["log_file"] = None
            return
        LOGGER.warning(
            "Server not ready after %.0fs; leaving it running (set AIO_SERVER_READY_TIMEOUT to extend). See %s",
            _SERVER_READY_TIMEOUT_SECONDS,
            log_path,
        )


def _local_server_base_url(api_prefix: str = "/v1") -> str:
    """Return the direct URL for the locally spawned API server."""
    scheme = "https" if settings.server_ssl else "http"
    return f"{scheme}://127.0.0.1:{settings.server_port}{api_prefix.rstrip('/')}"


def _stop_process(proc: subprocess.Popen) -> None:
    """Terminate a subprocess, escalating to kill if needed."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _stop_server() -> None:
    """Terminate the server subprocess if it is still running."""
    proc = _SERVER["process"]
    if proc is not None:
        _stop_process(proc)
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
    return {"X-API-Key": reveal(settings.api_key) or ""}


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


def api_post_stream(
    path: str,
    json_body: dict | None = None,
    timeout: int = 600,
    api_prefix: str = "/v1",
) -> Generator[dict, None, None]:
    """Streaming POST request to the API server. Yields parsed NDJSON dicts."""
    url = f"{_base_url(api_prefix)}/{path.lstrip('/')}"
    with (
        httpx.Client(headers=_headers(), timeout=timeout) as client,
        client.stream("POST", url, json=json_body) as resp,
    ):
        resp.raise_for_status()
        for raw_line in resp.iter_lines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError:
                continue


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


def get_server_settings(client: str, include_sensitive: bool = False) -> dict | None:
    """Fetch server settings (including database and OCI configs) from /settings.

    Returns ``None`` on any HTTP error so callers can decide how to recover
    (e.g. spawn the subprocess server in All-In-One mode).

    When *include_sensitive* is True, this routes through the dedicated
    export endpoint. For ``include_sensitive=False`` the response uses the
    standard settings endpoint.
    """
    if include_sensitive:
        return export_server_settings(client)

    base = _base_url()
    headers = _headers()
    params = {"client": client}
    try:
        with httpx.Client(headers=headers, timeout=5) as client_settings:
            resp = client_settings.get(f"{base}/settings", params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        LOGGER.warning("Failed to fetch server settings from %s", base)
        return None


def export_server_settings(client: str) -> dict | None:
    """Fetch the explicit settings export. Returns ``None`` on HTTP error."""
    base = _base_url()
    headers = {**_headers(), "X-Confirm-Export": "true"}
    params = {"client": client}
    try:
        with httpx.Client(headers=headers, timeout=5) as client_settings:
            resp = client_settings.post(f"{base}/settings/export", params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        LOGGER.warning("Failed to export server settings from %s", base)
        return None
