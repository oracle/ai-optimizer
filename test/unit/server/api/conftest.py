"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for server/api unit tests.
Provides factory fixtures for creating test objects.
"""

# pylint: disable=redefined-outer-name
# Pytest fixtures use parameter injection where fixture names match parameters

from unittest.mock import MagicMock, AsyncMock
import pytest

from common.schema import (
    Database,
    DatabaseAuth,
    Model,
    OracleCloudSettings,
    Settings,
    LargeLanguageSettings,
    DatabaseVectorStorage,
    ChatRequest,
    Configuration,
)


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
        **kwargs,
    ) -> Model:
        return Model(
            id=model_id,
            type=model_type,
            provider=provider,
            enabled=enabled,
            **kwargs,
        )

    return _make_model


@pytest.fixture
def make_oci_config():
    """Factory fixture to create OracleCloudSettings objects."""

    def _make_oci_config(
        auth_profile: str = "DEFAULT",
        genai_region: str = "us-ashburn-1",
        **kwargs,
    ) -> OracleCloudSettings:
        return OracleCloudSettings(
            auth_profile=auth_profile,
            genai_region=genai_region,
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
def make_database_auth():
    """Factory fixture to create DatabaseAuth objects."""

    def _make_database_auth(
        user: str = "test_user",
        password: str = "test_password",
        dsn: str = "localhost:1521/TESTPDB",
        wallet_password: str = None,
        **kwargs,
    ) -> DatabaseAuth:
        return DatabaseAuth(
            user=user,
            password=password,
            dsn=dsn,
            wallet_password=wallet_password,
            **kwargs,
        )

    return _make_database_auth


@pytest.fixture
def make_vector_store():
    """Factory fixture to create DatabaseVectorStorage objects."""

    def _make_vector_store(
        vector_store: str = "VS_TEST",
        model: str = "text-embedding-3-small",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        **kwargs,
    ) -> DatabaseVectorStorage:
        return DatabaseVectorStorage(
            vector_store=vector_store,
            model=model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            **kwargs,
        )

    return _make_vector_store


@pytest.fixture
def make_chat_request():
    """Factory fixture to create ChatRequest objects."""

    def _make_chat_request(
        content: str = "Hello",
        role: str = "user",
        **kwargs,
    ) -> ChatRequest:
        return ChatRequest(
            messages=[{"role": role, "content": content}],
            **kwargs,
        )

    return _make_chat_request


@pytest.fixture
def make_mcp_prompt():
    """Factory fixture to create MCP prompt mock objects."""

    def _make_mcp_prompt(
        name: str = "optimizer_test-prompt",
        description: str = "Test prompt description",
        text: str = "Test prompt text content",
    ):
        mock_prompt = MagicMock()
        mock_prompt.name = name
        mock_prompt.description = description
        mock_prompt.text = text
        mock_prompt.model_dump.return_value = {
            "name": name,
            "description": description,
            "text": text,
        }
        return mock_prompt

    return _make_mcp_prompt


@pytest.fixture
def make_configuration(make_settings):
    """Factory fixture to create Configuration objects."""

    def _make_configuration(
        client: str = "test_client",
        client_settings: Settings = None,
        **kwargs,
    ) -> Configuration:
        if client_settings is None:
            client_settings = make_settings(client=client)
        return Configuration(
            client_settings=client_settings,
            database_configs=[],
            model_configs=[],
            oci_configs=[],
            prompt_configs=[],
            **kwargs,
        )

    return _make_configuration


@pytest.fixture
def mock_fastmcp():
    """Create a mock FastMCP application."""
    mock_mcp = MagicMock()
    mock_mcp.list_tools = AsyncMock(return_value=[])
    mock_mcp.list_resources = AsyncMock(return_value=[])
    mock_mcp.list_prompts = AsyncMock(return_value=[])
    return mock_mcp


@pytest.fixture
def mock_mcp_client():
    """Create a mock MCP client."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.list_prompts = AsyncMock(return_value=[])
    mock_client.get_prompt = AsyncMock(return_value=MagicMock())
    mock_client.close = AsyncMock()
    return mock_client


@pytest.fixture
def mock_db_connection():
    """Create a mock database connection for endpoint tests.

    This mock is used by v1 endpoint tests that mock the underlying
    database utilities. It provides a simple MagicMock that can be
    passed around without needing a real database connection.

    For tests that need actual database operations, use the real
    db_connection or db_transaction fixtures from test/conftest.py.
    """
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock()
    mock_conn.cursor.return_value.__exit__ = MagicMock()
    mock_conn.commit = MagicMock()
    mock_conn.rollback = MagicMock()
    mock_conn.close = MagicMock()
    return mock_conn


@pytest.fixture
def mock_request_app_state(mock_fastmcp):
    """Create a mock FastAPI request with app state."""
    mock_request = MagicMock()
    mock_request.app.state.fastmcp_app = mock_fastmcp
    return mock_request


@pytest.fixture
def mock_bootstrap():
    """Create mocks for bootstrap module dependencies."""
    return {
        "databases": [],
        "models": [],
        "oci_configs": [],
        "prompts": [],
        "settings": [],
    }


def create_mock_aiohttp_session(mock_session_class, mock_response):
    """Helper to create a mock aiohttp ClientSession with response.

    This is a shared utility for tests that need to mock aiohttp.ClientSession.
    It properly sets up async context manager behavior for session.get().

    Args:
        mock_session_class: The patched aiohttp.ClientSession class
        mock_response: The mock response object to return from session.get()

    Returns:
        The configured mock session object
    """
    mock_session = AsyncMock()
    mock_session.get = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
    )
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()
    mock_session_class.return_value = mock_session
    return mock_session
