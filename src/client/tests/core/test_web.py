"""Tests for the HTTPS-only Streamlit launcher."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.app import web


def test_run_requires_certificate_pair(monkeypatch):
    monkeypatch.setattr(
        web,
        "settings",
        SimpleNamespace(
            client_port=8501,
            client_address="localhost",
            client_ssl_cert_file="",
            client_ssl_key_file="",
        ),
    )

    with pytest.raises(RuntimeError, match="requires a TLS certificate"):
        web.run()


def test_run_configures_https_listener(monkeypatch):
    run = Mock()
    monkeypatch.setattr(web, "app", SimpleNamespace(run=run))
    monkeypatch.setattr(
        web,
        "settings",
        SimpleNamespace(
            client_port=8502,
            client_address="0.0.0.0",
            client_ssl_cert_file="/tls/cert.pem",
            client_ssl_key_file="/tls/key.pem",
        ),
    )

    web.run()

    run.assert_called_once_with(
        config={
            "server.port": 8502,
            "server.address": "0.0.0.0",
            "server.sslCertFile": "/tls/cert.pem",
            "server.sslKeyFile": "/tls/key.pem",
        }
    )


def test_run_handles_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr(web, "app", SimpleNamespace(run=Mock(side_effect=KeyboardInterrupt)))
    monkeypatch.setattr(
        web,
        "settings",
        SimpleNamespace(
            client_port=8501,
            client_address="localhost",
            client_ssl_cert_file="/tls/cert.pem",
            client_ssl_key_file="/tls/key.pem",
        ),
    )

    web.run()
