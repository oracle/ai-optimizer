"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for server/bootstrap integration tests.

Integration tests for bootstrap test the actual bootstrap process with real
file I/O, environment variables, and configuration loading. These tests
verify end-to-end behavior of the bootstrap system.
"""

# pylint: disable=redefined-outer-name protected-access

import json
import os
import tempfile
from pathlib import Path

import pytest

from server.bootstrap.configfile import ConfigStore


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def make_config_file(temp_dir):
    """Factory fixture to create real configuration JSON files."""

    def _make_config_file(
        filename: str = "configuration.json",
        client_settings: dict = None,
        database_configs: list = None,
        model_configs: list = None,
        oci_configs: list = None,
        prompt_configs: list = None,
    ):
        config_data = {
            "client_settings": client_settings or {"client": "test_client"},
            "database_configs": database_configs or [],
            "model_configs": model_configs or [],
            "oci_configs": oci_configs or [],
            "prompt_configs": prompt_configs or [],
        }

        file_path = temp_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        return file_path

    return _make_config_file


@pytest.fixture
def make_oci_config_file(temp_dir):
    """Factory fixture to create real OCI configuration files."""

    def _make_oci_config_file(
        filename: str = "config",
        profiles: dict = None,
    ):
        """Create an OCI-style config file.

        Args:
            filename: Name of the config file
            profiles: Dict of profile_name -> dict of key-value pairs
                     e.g., {"DEFAULT": {"tenancy": "...", "region": "..."}}
        """
        if profiles is None:
            profiles = {
                "DEFAULT": {
                    "tenancy": "ocid1.tenancy.oc1..testtenancy",
                    "region": "us-ashburn-1",
                    "fingerprint": "test:fingerprint",
                }
            }

        file_path = temp_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            for profile_name, settings in profiles.items():
                f.write(f"[{profile_name}]\n")
                for key, value in settings.items():
                    f.write(f"{key}={value}\n")
                f.write("\n")

        return file_path

    return _make_oci_config_file


@pytest.fixture
def clean_bootstrap_env():
    """Fixture to clean environment variables that affect bootstrap.

    This fixture saves current env vars, clears them for the test,
    and restores them afterward.
    """
    env_vars = [
        # Database vars
        "DB_USERNAME",
        "DB_PASSWORD",
        "DB_DSN",
        "DB_WALLET_PASSWORD",
        "TNS_ADMIN",
        # Model API keys
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "PPLX_API_KEY",
        # On-prem model URLs
        "ON_PREM_OLLAMA_URL",
        "ON_PREM_VLLM_URL",
        "ON_PREM_HF_URL",
        # OCI vars
        "OCI_CLI_CONFIG_FILE",
        "OCI_CLI_TENANCY",
        "OCI_CLI_REGION",
        "OCI_CLI_USER",
        "OCI_CLI_FINGERPRINT",
        "OCI_CLI_KEY_FILE",
        "OCI_CLI_SECURITY_TOKEN_FILE",
        "OCI_CLI_AUTH",
        "OCI_GENAI_COMPARTMENT_ID",
        "OCI_GENAI_REGION",
        "OCI_GENAI_SERVICE_ENDPOINT",
    ]

    original_values = {}
    for var in env_vars:
        original_values[var] = os.environ.pop(var, None)

    yield

    # Restore original values
    for var, value in original_values.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]


@pytest.fixture
def reset_config_store():
    """Reset ConfigStore singleton state before and after each test."""
    # Reset before test
    ConfigStore._config = None

    yield ConfigStore

    # Reset after test
    ConfigStore._config = None


@pytest.fixture
def sample_database_config():
    """Sample database configuration dict."""
    return {
        "name": "INTEGRATION_DB",
        "user": "integration_user",
        "password": "integration_pass",
        "dsn": "localhost:1521/INTPDB",
    }


@pytest.fixture
def sample_model_config():
    """Sample model configuration dict."""
    return {
        "id": "integration-model",
        "type": "ll",
        "provider": "openai",
        "enabled": True,
        "api_key": "test-api-key",
        "api_base": "https://api.openai.com/v1",
        "max_tokens": 4096,
    }


@pytest.fixture
def sample_oci_config():
    """Sample OCI configuration dict."""
    return {
        "auth_profile": "INTEGRATION",
        "tenancy": "ocid1.tenancy.oc1..integration",
        "region": "us-phoenix-1",
        "fingerprint": "integration:fingerprint",
    }


@pytest.fixture
def sample_settings_config():
    """Sample settings configuration dict."""
    return {
        "client": "integration_client",
        "ll_model": {
            "model": "gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": 4096,
            "chat_history": True,
        },
    }
