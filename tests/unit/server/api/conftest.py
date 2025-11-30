"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for server/api unit tests.
Provides factory fixtures for creating test objects.

Note: Shared fixtures (make_database, make_model, etc.) are automatically
available via pytest_plugins in test/conftest.py. Only import constants
and helper functions that are needed in this file.
"""

# pylint: disable=redefined-outer-name

from unittest.mock import MagicMock, AsyncMock

import pytest

from common.schema import (
    DatabaseAuth,
    DatabaseVectorStorage,
    ChatRequest,
)
# Import constants needed by fixtures in this file
from tests.shared_fixtures import (
    TEST_DB_USER,
    TEST_DB_PASSWORD,
    TEST_DB_DSN,
)


@pytest.fixture
def make_database_auth():
    """Factory fixture to create DatabaseAuth objects."""

    def _make_database_auth(**overrides) -> DatabaseAuth:
        defaults = {
            "user": TEST_DB_USER,
            "password": TEST_DB_PASSWORD,
            "dsn": TEST_DB_DSN,
            "wallet_password": None,
        }
        defaults.update(overrides)
        return DatabaseAuth(**defaults)

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
