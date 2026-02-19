"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared pytest fixtures for unit and integration tests.

This module is loaded via pytest_plugins in test/conftest.py, making all
fixtures automatically available to all tests without explicit imports.

FIXTURES (auto-loaded via pytest_plugins):
    - make_database: Factory for Database objects
    - make_model: Factory for Model objects
    - make_oci_config: Factory for OracleCloudSettings objects
    - make_ll_settings: Factory for LargeLanguageSettings objects
    - make_settings: Factory for Settings objects
    - make_configuration: Factory for Configuration objects
    - temp_config_file: Creates temporary JSON config files
    - reset_config_store: Resets ConfigStore singleton state
    - clean_env: Clears bootstrap-related environment variables
    - sample_vector_store_data: Sample vector store configuration
    - sample_vector_store_data_alt: Alternative vector store configuration
    - sample_vector_stores_list: List of sample vector stores

CONSTANTS (require explicit import in test files):
    - TEST_DB_USER, TEST_DB_PASSWORD, TEST_DB_DSN, TEST_DB_WALLET_PASSWORD
    - TEST_API_KEY, TEST_API_KEY_ALT, TEST_AUTH_TOKEN
    - TEST_INTEGRATION_DB_USER, TEST_INTEGRATION_DB_PASSWORD, TEST_INTEGRATION_DB_DSN
    - DEFAULT_LL_MODEL_CONFIG, BOOTSTRAP_ENV_VARS
    - SAMPLE_VECTOR_STORE_DATA, SAMPLE_VECTOR_STORE_DATA_ALT

HELPER FUNCTIONS (require explicit import in test files):
    - assert_database_list_valid, assert_has_default_database, get_database_by_name
    - assert_model_list_valid, get_model_by_id
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

# API server environment variables
API_SERVER_ENV_VARS = [
    "API_SERVER_KEY",
    "API_SERVER_URL",
    "API_SERVER_PORT",
]

# Config file environment variables
CONFIG_ENV_VARS = [
    "CONFIG_FILE",
    "OCI_CLI_CONFIG_FILE",
]

# All test-relevant environment variables (union of all categories)
ALL_TEST_ENV_VARS = list(set(BOOTSTRAP_ENV_VARS + API_SERVER_ENV_VARS + CONFIG_ENV_VARS))


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


def _get_dynamic_oci_vars() -> list[str]:
    """Get list of OCI_ prefixed environment variables currently set.

    Returns all environment variables starting with OCI_ that aren't
    in our static list (catches user-specific OCI vars).
    """
    static_oci_vars = {v for v in BOOTSTRAP_ENV_VARS if v.startswith("OCI_")}
    return [v for v in os.environ if v.startswith("OCI_") and v not in static_oci_vars]


@pytest.fixture
def clean_env(monkeypatch):
    """Fixture to clear bootstrap-related environment variables using monkeypatch.

    Uses pytest's monkeypatch for proper isolation - changes are automatically
    reverted after the test completes, even if the test fails.

    This fixture clears:
    - Database variables (DB_USERNAME, DB_PASSWORD, etc.)
    - Model API keys (OPENAI_API_KEY, COHERE_API_KEY, etc.)
    - OCI variables (all OCI_* prefixed vars)

    Usage:
        def test_bootstrap_without_env(clean_env):
            # Environment is clean, no DB/API/OCI vars set
            result = bootstrap.main()
            assert result uses defaults
    """
    # Clear all known bootstrap vars
    for var in BOOTSTRAP_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    # Clear any dynamic OCI_ vars not in our static list
    for var in _get_dynamic_oci_vars():
        monkeypatch.delenv(var, raising=False)

    yield


@pytest.fixture
def clean_all_env(monkeypatch):
    """Fixture to clear ALL test-related environment variables.

    More aggressive than clean_env - also clears API server and config vars.
    Use this when you need complete environment isolation.

    Usage:
        def test_with_clean_slate(clean_all_env):
            # No test-related env vars are set
            pass
    """
    for var in ALL_TEST_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    # Clear any dynamic OCI_ vars
    for var in _get_dynamic_oci_vars():
        monkeypatch.delenv(var, raising=False)

    yield


@pytest.fixture
def isolated_env(monkeypatch):
    """Fixture providing isolated environment with test defaults.

    Clears all test-related vars and sets safe defaults for test execution.
    Use this when tests need a known, controlled environment state.

    Sets:
    - CONFIG_FILE: /non/existent/path/config.json (forces empty config)
    - OCI_CLI_CONFIG_FILE: /non/existent/path (prevents OCI config pickup)

    Usage:
        def test_with_defaults(isolated_env):
            # Environment has safe test defaults
            pass
    """
    # Clear all test-related vars first
    for var in ALL_TEST_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    # Clear dynamic OCI vars
    for var in _get_dynamic_oci_vars():
        monkeypatch.delenv(var, raising=False)

    # Set safe test defaults
    monkeypatch.setenv("CONFIG_FILE", "/non/existent/path/config.json")
    monkeypatch.setenv("OCI_CLI_CONFIG_FILE", "/non/existent/path")

    yield monkeypatch  # Yield monkeypatch so tests can add more vars if needed


def setup_test_env_vars(
    monkeypatch,
    auth_token: str = None,
    server_url: str = "http://localhost",
    server_port: int = 8000,
    config_file: str = "/non/existent/path/config.json",
) -> None:
    """Helper function to set up common test environment variables.

    This is a utility function (not a fixture) that can be called from
    fixtures or tests to set up the environment consistently.

    Args:
        monkeypatch: pytest monkeypatch fixture
        auth_token: API server authentication token
        server_url: API server URL (default: http://localhost)
        server_port: API server port (default: 8000)
        config_file: Path to config file (default: non-existent for empty config)

    Usage:
        @pytest.fixture
        def my_env(monkeypatch):
            setup_test_env_vars(monkeypatch, auth_token="my-token", server_port=8015)
            yield
    """
    # Clear existing vars
    for var in ALL_TEST_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    # Clear dynamic OCI vars
    for var in _get_dynamic_oci_vars():
        monkeypatch.delenv(var, raising=False)

    # Set config vars
    monkeypatch.setenv("CONFIG_FILE", config_file)
    monkeypatch.setenv("OCI_CLI_CONFIG_FILE", "/non/existent/path")

    # Set API server vars if token provided
    if auth_token:
        monkeypatch.setenv("API_SERVER_KEY", auth_token)
        monkeypatch.setenv("API_SERVER_URL", server_url)
        monkeypatch.setenv("API_SERVER_PORT", str(server_port))


#################################################
# Session-scoped Environment Helpers
#################################################
# These helpers are for session-scoped fixtures that can't use monkeypatch.
# They manually save/restore environment state.


def save_env_state() -> dict:
    """Save the current state of test-related environment variables.

    Returns a dict mapping var names to their values (or None if not set).
    Also captures dynamic OCI_ vars not in our static list.

    Usage:
        original_env = save_env_state()
        # ... modify environment ...
        restore_env_state(original_env)
    """
    original_env = {var: os.environ.get(var) for var in ALL_TEST_ENV_VARS}

    # Also capture dynamic OCI_ vars
    for var in _get_dynamic_oci_vars():
        original_env[var] = os.environ.get(var)

    return original_env


def clear_env_state(original_env: dict) -> None:
    """Clear all test-related environment variables.

    Clears all vars in ALL_TEST_ENV_VARS plus any dynamic OCI_ vars
    that were captured in original_env.

    Args:
        original_env: Dict from save_env_state() (used to get dynamic var names)
    """
    for var in ALL_TEST_ENV_VARS:
        os.environ.pop(var, None)

    # Clear dynamic OCI vars that were in original_env
    for var in original_env:
        if var not in ALL_TEST_ENV_VARS:
            os.environ.pop(var, None)


def restore_env_state(original_env: dict) -> None:
    """Restore environment variables to their original state.

    Args:
        original_env: Dict from save_env_state()
    """
    for var, value in original_env.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]


def make_auth_headers(auth_token: str, client_id: str) -> dict:
    """Create standard auth headers dict for testing.

    Returns a dict with 'no_auth', 'invalid_auth', and 'valid_auth' keys,
    each containing the appropriate headers for that auth scenario.

    Args:
        auth_token: Valid authentication token
        client_id: Client identifier for the client header

    Returns:
        Dict with auth header configurations for testing
    """
    return {
        "no_auth": {},
        "invalid_auth": {"Authorization": "Bearer invalid-token", "client": client_id},
        "valid_auth": {"Authorization": f"Bearer {auth_token}", "client": client_id},
    }


#################################################
# Spring AI Test Helpers
#################################################


def call_spring_ai_obaas_with_mocks(mock_state, template_content, spring_ai_obaas_func):
    """Call spring_ai_obaas with standard mocking setup.

    This helper encapsulates the common patching pattern for spring_ai_obaas tests,
    reducing code duplication between unit and integration tests.

    Args:
        mock_state: The state object to use (mock or real session_state)
        template_content: The template file content to return from mock open
        spring_ai_obaas_func: The spring_ai_obaas function to call

    Returns:
        The result from calling spring_ai_obaas
    """
    # pylint: disable=import-outside-toplevel
    from unittest.mock import patch, mock_open

    with patch("client.content.config.tabs.settings.state", mock_state):
        with patch("client.content.config.tabs.settings.st_common.state_configs_lookup") as mock_lookup:
            with patch("builtins.open", mock_open(read_data=template_content)):
                mock_lookup.return_value = {"DEFAULT": {"user": "test_user"}}
                return spring_ai_obaas_func(
                    Path("/test/path"),
                    "start.sh",
                    "openai",
                    {"model": "gpt-4"},
                    {"model": "text-embedding-ada-002"},
                )


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
