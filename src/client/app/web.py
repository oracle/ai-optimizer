"""Streamlit ASGI launcher with client-owned authentication routes."""

import contextlib
from pathlib import Path

import streamlit as st
from starlette.routing import Route

from client.app.core.local_session import route_paths, session_cookie_route
from client.app.core.settings import settings

app = st.App(
    Path(__file__).with_name("main.py"),
    routes=[Route(path, session_cookie_route, methods=["POST"]) for path in route_paths()],
)


def run() -> None:
    """Run the Streamlit client with its configured listener settings."""
    config: dict[str, object] = {
        "server.port": settings.client_port,
        "server.address": settings.client_address,
    }
    if settings.client_ssl:
        if not settings.client_ssl_cert_file or not settings.client_ssl_key_file:
            raise RuntimeError("Client requires a TLS certificate and private key")
        config["server.sslCertFile"] = settings.client_ssl_cert_file
        config["server.sslKeyFile"] = settings.client_ssl_key_file
    with contextlib.suppress(KeyboardInterrupt):
        app.run(config=config)


if __name__ == "__main__":
    run()
