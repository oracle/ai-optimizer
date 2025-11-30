"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for server/bootstrap integration tests.

Integration tests for bootstrap test the actual bootstrap process with real
file I/O, environment variables, and configuration loading. These tests
verify end-to-end behavior of the bootstrap system.

Note: Shared fixtures (reset_config_store, clean_env, make_database, make_model, etc.)
are automatically available via pytest_plugins in test/conftest.py.
"""

# pylint: disable=redefined-outer-name

import json
import tempfile
from pathlib import Path

import pytest

# Import constants needed by fixtures in this file
from tests.shared_fixtures import (
    DEFAULT_LL_MODEL_CONFIG,
    TEST_INTEGRATION_DB_USER,
    TEST_INTEGRATION_DB_PASSWORD,
    TEST_INTEGRATION_DB_DSN,
    TEST_API_KEY_ALT,
)


@pytest.fixture
@pytest.mark.usefixtures("clean_env")
def clean_bootstrap_env():
    """Alias for clean_env fixture for backwards compatibility.

    This fixture name is used in existing tests. It delegates to the
    shared clean_env fixture loaded via pytest_plugins.
    """
    yield


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
def sample_database_config():
    """Sample database configuration dict."""
    return {
        "name": "INTEGRATION_DB",
        "user": TEST_INTEGRATION_DB_USER,
        "password": TEST_INTEGRATION_DB_PASSWORD,
        "dsn": TEST_INTEGRATION_DB_DSN,
    }


@pytest.fixture
def sample_model_config():
    """Sample model configuration dict."""
    return {
        "id": "integration-model",
        "type": "ll",
        "provider": "openai",
        "enabled": True,
        "api_key": TEST_API_KEY_ALT,
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
        "ll_model": DEFAULT_LL_MODEL_CONFIG.copy(),
    }
