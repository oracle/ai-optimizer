"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for server/bootstrap unit tests.
"""

# pylint: disable=redefined-outer-name protected-access too-few-public-methods

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.schema import (
    Configuration,
    Database,
    Model,
    OracleCloudSettings,
    Settings,
    LargeLanguageSettings,
)
from server.bootstrap.configfile import ConfigStore


@pytest.fixture
def make_database():
    """Factory fixture to create Database objects."""

    def _make_database(
        name: str = "TEST_DB",
        user: str = "test_user",
        password: str = "test_password",
        dsn: str = "localhost:1521/TESTPDB",
        wallet_password: str = None,
        **kwargs,
    ) -> Database:
        return Database(
            name=name,
            user=user,
            password=password,
            dsn=dsn,
            wallet_password=wallet_password,
            **kwargs,
        )

    return _make_database


@pytest.fixture
def make_model():
    """Factory fixture to create Model objects."""

    def _make_model(
        model_id: str = "gpt-4o-mini",
        model_type: str = "ll",
        provider: str = "openai",
        enabled: bool = True,
        api_key: str = "test-key",
        api_base: str = "https://api.openai.com/v1",
        **kwargs,
    ) -> Model:
        return Model(
            id=model_id,
            type=model_type,
            provider=provider,
            enabled=enabled,
            api_key=api_key,
            api_base=api_base,
            **kwargs,
        )

    return _make_model


@pytest.fixture
def make_oci_config():
    """Factory fixture to create OracleCloudSettings objects.

    Note: The 'user' field requires OCID format pattern matching.
    Use None to skip the user field in tests that don't need it.
    """

    def _make_oci_config(
        auth_profile: str = "DEFAULT",
        tenancy: str = "test-tenancy",
        region: str = "us-ashburn-1",
        user: str = None,  # Use None by default - OCID pattern required
        fingerprint: str = "test-fingerprint",
        key_file: str = "/path/to/key",
        **kwargs,
    ) -> OracleCloudSettings:
        return OracleCloudSettings(
            auth_profile=auth_profile,
            tenancy=tenancy,
            region=region,
            user=user,
            fingerprint=fingerprint,
            key_file=key_file,
            **kwargs,
        )

    return _make_oci_config


@pytest.fixture
def make_ll_settings():
    """Factory fixture to create LargeLanguageSettings objects."""

    def _make_ll_settings(
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        chat_history: bool = True,
        **kwargs,
    ) -> LargeLanguageSettings:
        return LargeLanguageSettings(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            chat_history=chat_history,
            **kwargs,
        )

    return _make_ll_settings


@pytest.fixture
def make_settings(make_ll_settings):
    """Factory fixture to create Settings objects."""

    def _make_settings(
        client: str = "test_client",
        ll_model: LargeLanguageSettings = None,
        **kwargs,
    ) -> Settings:
        if ll_model is None:
            ll_model = make_ll_settings()
        return Settings(
            client=client,
            ll_model=ll_model,
            **kwargs,
        )

    return _make_settings


@pytest.fixture
def make_configuration(make_settings):
    """Factory fixture to create Configuration objects."""

    def _make_configuration(
        client_settings: Settings = None,
        database_configs: list = None,
        model_configs: list = None,
        oci_configs: list = None,
        **kwargs,
    ) -> Configuration:
        return Configuration(
            client_settings=client_settings or make_settings(),
            database_configs=database_configs or [],
            model_configs=model_configs or [],
            oci_configs=oci_configs or [],
            prompt_configs=[],
            **kwargs,
        )

    return _make_configuration


@pytest.fixture
def temp_config_file(make_settings):
    """Create a temporary configuration JSON file."""

    def _create_temp_config(
        client_settings: Settings = None,
        database_configs: list = None,
        model_configs: list = None,
        oci_configs: list = None,
    ):
        config_data = {
            "client_settings": (client_settings or make_settings()).model_dump(),
            "database_configs": [
                (db if isinstance(db, dict) else db.model_dump())
                for db in (database_configs or [])
            ],
            "model_configs": [
                (m if isinstance(m, dict) else m.model_dump())
                for m in (model_configs or [])
            ],
            "oci_configs": [
                (o if isinstance(o, dict) else o.model_dump())
                for o in (oci_configs or [])
            ],
            "prompt_configs": [],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as temp_file:
            json.dump(config_data, temp_file)
            return Path(temp_file.name)

    return _create_temp_config


@pytest.fixture
def reset_config_store():
    """Reset ConfigStore singleton state before and after each test."""
    # Reset before test
    ConfigStore._config = None

    yield ConfigStore

    # Reset after test
    ConfigStore._config = None


@pytest.fixture
def mock_oci_config_parser():
    """Mock OCI config parser for testing OCI bootstrap."""
    with patch("configparser.ConfigParser") as mock_parser:
        mock_instance = MagicMock()
        mock_instance.sections.return_value = []
        mock_parser.return_value = mock_instance
        yield mock_parser


@pytest.fixture
def mock_oci_config_from_file():
    """Mock oci.config.from_file for testing OCI bootstrap."""
    with patch("oci.config.from_file") as mock_from_file:
        yield mock_from_file


@pytest.fixture
def mock_is_url_accessible():
    """Mock is_url_accessible for testing model bootstrap."""
    with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
        mock_accessible.return_value = (True, "OK")
        yield mock_accessible


@pytest.fixture
def clean_env():
    """Fixture to temporarily clear relevant environment variables."""
    env_vars = [
        "DB_USERNAME",
        "DB_PASSWORD",
        "DB_DSN",
        "DB_WALLET_PASSWORD",
        "TNS_ADMIN",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "PPLX_API_KEY",
        "ON_PREM_OLLAMA_URL",
        "ON_PREM_VLLM_URL",
        "ON_PREM_HF_URL",
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
