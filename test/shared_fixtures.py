"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared pytest fixtures for unit and integration tests.

This module contains common fixture factories and utilities that are shared
across multiple test conftest files to avoid code duplication.
"""

# pylint: disable=redefined-outer-name

import json
import os
import tempfile
from pathlib import Path

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


#################################################
# Test Credentials Constants
#################################################
# Centralized fake credentials for testing.
# These are NOT real secrets - they are placeholder values used in tests.
# Using constants ensures consistent values across tests and allows
# security scanners to be configured to ignore this single location.

# Database credentials (fake - for testing only)
TEST_DB_USER = "test_user"
TEST_DB_PASSWORD = "test_password"  # noqa: S105 - not a real password
TEST_DB_DSN = "localhost:1521/TESTPDB"
TEST_DB_WALLET_PASSWORD = "test_wallet_pass"  # noqa: S105 - not a real password

# API keys (fake - for testing only)
TEST_API_KEY = "test-key"  # noqa: S105 - not a real API key
TEST_API_KEY_ALT = "test-api-key"  # noqa: S105 - not a real API key
TEST_AUTH_TOKEN = "integration-test-token"  # noqa: S105 - not a real token

# Integration test database credentials (fake - for testing only)
TEST_INTEGRATION_DB_USER = "integration_user"
TEST_INTEGRATION_DB_PASSWORD = "integration_pass"  # noqa: S105 - not a real password
TEST_INTEGRATION_DB_DSN = "localhost:1521/INTPDB"


# Default test model settings - shared across test fixtures
DEFAULT_LL_MODEL_CONFIG = {
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "max_tokens": 4096,
    "chat_history": True,
}

# Environment variables used by bootstrap modules
BOOTSTRAP_ENV_VARS = [
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


#################################################
# Schema Factory Fixtures
#################################################


@pytest.fixture
def make_database():
    """Factory fixture to create Database objects."""

    def _make_database(
        name: str = "TEST_DB",
        user: str = TEST_DB_USER,
        password: str = TEST_DB_PASSWORD,
        dsn: str = TEST_DB_DSN,
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
    """Factory fixture to create Model objects.

    Supports both `model_id` and `id` parameter names for backwards compatibility.
    """

    def _make_model(
        model_id: str = None,
        model_type: str = "ll",
        provider: str = "openai",
        enabled: bool = True,
        api_key: str = TEST_API_KEY,
        api_base: str = "https://api.openai.com/v1",
        **kwargs,
    ) -> Model:
        # Support both 'id' kwarg and 'model_id' parameter for backwards compat
        resolved_id = kwargs.pop("id", None) or model_id or "gpt-4o-mini"
        return Model(
            id=resolved_id,
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


#################################################
# Config File Fixtures
#################################################


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
    ConfigStore.reset()

    yield ConfigStore

    # Reset after test
    ConfigStore.reset()


#################################################
# Test Helper Functions (shared assertions to reduce duplication)
#################################################


def assert_database_list_valid(result):
    """Assert that result is a valid list of Database objects."""
    assert isinstance(result, list)
    assert all(isinstance(db, Database) for db in result)


def assert_has_default_database(result):
    """Assert that DEFAULT database is in the result."""
    db_names = [db.name for db in result]
    assert "DEFAULT" in db_names


def get_database_by_name(result, name):
    """Get a database from results by name."""
    return next(db for db in result if db.name == name)


def assert_model_list_valid(result):
    """Assert that result is a valid list of Model objects."""
    assert isinstance(result, list)
    assert all(isinstance(m, Model) for m in result)


def get_model_by_id(result, model_id):
    """Get a model from results by id."""
    return next(m for m in result if m.id == model_id)


#################################################
# Environment Fixtures
#################################################


@pytest.fixture
def clean_env():
    """Fixture to temporarily clear relevant environment variables."""
    original_values = {}
    for var in BOOTSTRAP_ENV_VARS:
        original_values[var] = os.environ.pop(var, None)

    yield

    # Restore original values
    for var, value in original_values.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]


#################################################
# Vector Store Test Data
#################################################

# Shared vector store test data used across client tests
SAMPLE_VECTOR_STORE_DATA = {
    "alias": "test_alias",
    "model": "openai/text-embed-3",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "distance_metric": "cosine",
    "index_type": "IVF",
    "vector_store": "vs_test",
}

SAMPLE_VECTOR_STORE_DATA_ALT = {
    "alias": "alias2",
    "model": "openai/text-embed-3",
    "chunk_size": 500,
    "chunk_overlap": 100,
    "distance_metric": "euclidean",
    "index_type": "HNSW",
    "vector_store": "vs2",
}


@pytest.fixture
def sample_vector_store_data():
    """Sample vector store data for testing - standard configuration."""
    return SAMPLE_VECTOR_STORE_DATA.copy()


@pytest.fixture
def sample_vector_store_data_alt():
    """Alternative sample vector store data for testing - different configuration."""
    return SAMPLE_VECTOR_STORE_DATA_ALT.copy()


@pytest.fixture
def sample_vector_stores_list():
    """List of sample vector stores with different aliases for filtering tests."""
    vs1 = SAMPLE_VECTOR_STORE_DATA.copy()
    vs1["alias"] = "vs1"
    vs1.pop("vector_store", None)

    vs2 = SAMPLE_VECTOR_STORE_DATA_ALT.copy()
    vs2["alias"] = "vs2"
    vs2.pop("vector_store", None)

    return [vs1, vs2]
