"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared test fixtures.
"""
# spell-checker: disable

import contextlib
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import docker
import oracledb
import pytest
from docker.errors import DockerException
from httpx import ASGITransport, AsyncClient

import server.app.core.environ  # noqa: F401  # side-effect: populates env defaults

# Stub giskard before app import to prevent pyarrow incompatibilities
# during test collection (giskard -> datasets -> pyarrow).
_gsk = MagicMock()
for _name in (
    "giskard",
    "giskard.llm",
    "giskard.llm.client",
    "giskard.llm.errors",
    "giskard.rag",
    "giskard.rag.base",
    "giskard.rag.question_generators",
    "giskard.rag.question_generators.utils",
):
    sys.modules.setdefault(_name, _gsk)

# Prevent LiteLLM from registering its atexit cleanup handler which causes
# "I/O operation on closed file" errors when it tries to log after pytest
# closes stderr. Must be set before any lazy litellm attribute access.
import litellm

litellm._async_client_cleanup_registered = True

# Suppress logging errors during interpreter shutdown (aiohttp unclosed
# client/connector __del__ warnings write to already-closed stderr).
import atexit
import logging

atexit.register(lambda: setattr(logging, "raiseExceptions", False))

# Suppress "Task was destroyed but it is pending!" from asyncio logger.
# oracledb's async pool machinery can leave background connection tasks
# pending when a pool is created against an unreachable host and then closed.
logging.getLogger("asyncio").addFilter(
    lambda record: "Task was destroyed but it is pending" not in record.getMessage()
)

from pyagentspec.flows.flow import Flow
from pyagentspec.flows.nodes import EndNode, LlmNode

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.core.settings import settings
from server.app.database.schemas import DatabaseConfig
from server.app.main import app
from server.app.models.schemas import ModelConfig
from server.app.oci.schemas import OciProfileConfig

try:
    from wayflowcore.agent import Agent as RuntimeAgent  # pyright: ignore[reportMissingImports]
    from wayflowcore.conversation import Conversation  # pyright: ignore[reportMissingImports]
    from wayflowcore.flow import Flow as RuntimeFlow  # pyright: ignore[reportMissingImports]
    from wayflowcore.messagelist import MessageList  # pyright: ignore[reportMissingImports]
    from wayflowcore.models import LlmGenerationConfig  # pyright: ignore[reportMissingImports]

    from server.app.runtime.wayflow.adapters.litellm import (  # pyright: ignore[reportMissingImports]
        LiteLlmModel,
        register_litellm_model_factory,
    )

    WAYFLOWCORE_AVAILABLE = True
except ModuleNotFoundError:
    from typing import Any as _Any

    RuntimeAgent: _Any = None
    Conversation: _Any = None
    RuntimeFlow: _Any = None
    MessageList: _Any = None
    LlmGenerationConfig: _Any = None
    LiteLlmModel: _Any = None
    register_litellm_model_factory: _Any = None
    WAYFLOWCORE_AVAILABLE = False

# Tell pytest to skip collecting wayflowcore-only test modules when the
# package isn't installed. Paths are relative to this conftest.
collect_ignore_glob: list[str] = []
if not WAYFLOWCORE_AVAILABLE:
    collect_ignore_glob.append("runtime/wayflow/*")


@pytest.fixture
def anyio_backend():
    """Force asyncio backend globally to avoid trio dependency."""
    return "asyncio"


# ---------------------------------------------------------------------------
# wayflowcore opt-in gating
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        "--wayflowcore",
        action="store_true",
        default=False,
        help="Run wayflowcore runtime tests (skipped by default).",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests under runtime/wayflow/ and skip unless opted in.

    Opt in with `--wayflowcore` or by selecting the marker via `-m wayflowcore`.
    """
    wayflow_marker = pytest.mark.wayflowcore
    for item in items:
        if "runtime/wayflow" in item.nodeid.replace("\\", "/"):
            item.add_marker(wayflow_marker)

    if config.getoption("--wayflowcore"):
        return

    markexpr = config.getoption("-m", default="") or ""
    if "wayflowcore" in markexpr:
        return

    skip_wayflow = pytest.mark.skip(reason="wayflowcore tests skipped; pass --wayflowcore to run")
    for item in items:
        if "wayflowcore" in item.keywords:
            item.add_marker(skip_wayflow)


# ---------------------------------------------------------------------------
# Oracle container and constants
# ---------------------------------------------------------------------------

TEST_DB_CONFIG = {
    "db_username": "PYTEST",
    "db_password": "OrA_41_3xPl0d3r",
    "db_dsn": "//localhost:1525/FREEPDB1",
}

ORACLE_IMAGE = "container-registry.oracle.com/database/free:latest-lite"
CONTAINER_NAME = "server-test-oracle"
READY_LOG_MARKER = "DATABASE IS READY TO USE!"


@contextmanager
def _oracle_container() -> Generator:
    try:
        client = docker.from_env()
    except DockerException as exc:  # pragma: no cover - unit tests mock this
        pytest.skip(f"Docker not available: {exc}", allow_module_level=True)

    _remove_existing(client)

    temp_dir = Path(tempfile.mkdtemp(prefix="server_db_startup_"))
    temp_dir.chmod(0o755)
    container = None
    try:
        _write_startup_scripts(temp_dir)
        container = client.containers.run(
            ORACLE_IMAGE,
            name=CONTAINER_NAME,
            environment={
                "ORACLE_PWD": TEST_DB_CONFIG["db_password"],
                "ORACLE_PDB": TEST_DB_CONFIG["db_dsn"].rsplit("/", maxsplit=1)[-1],
            },
            ports={"1521/tcp": int(TEST_DB_CONFIG["db_dsn"].split(":")[1].split("/")[0])},
            volumes={str(temp_dir.absolute()): {"bind": "/opt/oracle/scripts/startup", "mode": "ro"}},
            detach=True,
        )
        _wait_for_ready(container)
        yield container
    finally:
        if container is not None:
            try:
                container.stop(timeout=60)
                container.remove()
            except DockerException:
                pass
            time.sleep(1)
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Oracle container helpers
# ---------------------------------------------------------------------------


def _write_startup_scripts(temp_dir: Path) -> None:
    """Write SQL setup files into the temp directory."""
    sql_content = f"""
    alter system set vector_memory_size=512M scope=spfile;

    alter session set container=FREEPDB1;
    CREATE TABLESPACE IF NOT EXISTS USERS DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/users_01.dbf' SIZE 100M;
    CREATE USER IF NOT EXISTS "{TEST_DB_CONFIG["db_username"]}" IDENTIFIED BY {TEST_DB_CONFIG["db_password"]}
        DEFAULT TABLESPACE "USERS"
        TEMPORARY TABLESPACE "TEMP";
    GRANT "DB_DEVELOPER_ROLE" TO "{TEST_DB_CONFIG["db_username"]}";
    ALTER USER "{TEST_DB_CONFIG["db_username"]}" DEFAULT ROLE ALL;
    ALTER USER "{TEST_DB_CONFIG["db_username"]}" QUOTA UNLIMITED ON USERS;

    EXIT;
    """

    temp_sql_file = temp_dir / "01_db_user.sql"
    temp_sql_file.write_text(sql_content, encoding="UTF-8")


def _wait_for_ready(container, timeout: int = 300) -> None:
    start = time.time()
    while time.time() - start < timeout:
        logs = container.logs(tail=200).decode("utf-8", errors="ignore")
        if READY_LOG_MARKER in logs:
            return
        time.sleep(5)
    raise TimeoutError("Oracle container did not become ready in time")


def _remove_existing(client) -> None:
    try:
        existing = client.containers.list(all=True, filters={"name": CONTAINER_NAME})
    except DockerException:
        return
    for container in existing:
        with contextlib.suppress(DockerException):
            container.remove(force=True)
        time.sleep(1)


# ---------------------------------------------------------------------------
# Oracle container fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def oracle_db_container() -> Generator:
    """Session-scoped Oracle container for integration tests."""
    with _oracle_container() as container:
        yield container


@pytest.fixture
def configure_db_env(monkeypatch, oracle_db_container):
    """Set database environment variables for the server during tests."""
    del oracle_db_container
    monkeypatch.setenv("AIO_DB_USERNAME", TEST_DB_CONFIG["db_username"])
    monkeypatch.setenv("AIO_DB_PASSWORD", TEST_DB_CONFIG["db_password"])
    monkeypatch.setenv("AIO_DB_DSN", TEST_DB_CONFIG["db_dsn"])
    monkeypatch.delenv("AIO_DB_WALLET_PASSWORD", raising=False)
    yield


# ---------------------------------------------------------------------------
# App-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def app_client():
    """Async HTTP client wired to the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def auth_headers():
    """Headers dict with a valid API key."""
    return {"X-API-Key": settings.api_key}


# ---------------------------------------------------------------------------
# Shared test-data factories
# ---------------------------------------------------------------------------


def make_test_database_config(**overrides) -> DatabaseConfig:
    """Standard TEST database config used across API tests."""
    defaults = {"alias": "TEST", "username": "testuser", "password": "secret", "wallet_password": "wallet_secret"}
    return DatabaseConfig(**{**defaults, **overrides})


def make_test_oci_profile(**overrides) -> OciProfileConfig:
    """Standard TEST OCI profile config used across API tests."""
    defaults = {
        "auth_profile": "TEST",
        "fingerprint": "aa:bb:cc",
        "key_content": "private-key-data",
        "key_file": "/path/to/key",
        "pass_phrase": "passphrase",
        "security_token_file": "/path/to/token",
        "tenancy": "ocid1.tenancy.oc1..test",
    }
    return OciProfileConfig(**{**defaults, **overrides})


def make_test_model_config(**overrides) -> ModelConfig:
    """Standard test model config used across API tests."""
    defaults = {"id": "test-model", "type": "ll", "provider": "openai", "api_key": "sk-secret-key"}
    return ModelConfig(**{**defaults, **overrides})


def make_test_vs_config(**overrides):
    """Standard VectorStoreConfig used across embed and database tests."""
    from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

    from server.app.embed.schemas import VectorStoreConfig
    from server.app.models.schemas import ModelIdentity

    defaults = {
        "vector_store": "VS_TEST",
        "embedding_model": ModelIdentity(provider="openai", id="text-embedding-3-small"),
        "chunk_size": 1000,
        "chunk_overlap": 100,
        "distance_strategy": DistanceStrategy.COSINE,
        "index_type": "HNSW",
    }
    return VectorStoreConfig(**{**defaults, **overrides})


def assert_no_sensitive_keys(entries: list[dict], sensitive_keys: set, identity_key: str) -> None:
    """Assert that no entry in the list contains any sensitive key, and that identity_key is present."""
    for entry in entries:
        for key in sensitive_keys:
            assert key not in entry
        assert identity_key in entry


def make_core_db_config(**overrides) -> DatabaseConfig:
    """Build a CORE DatabaseConfig from the test container credentials."""
    defaults = {
        "alias": "CORE",
        "username": TEST_DB_CONFIG["db_username"],
        "password": TEST_DB_CONFIG["db_password"],
        "dsn": TEST_DB_CONFIG["db_dsn"],
    }
    return DatabaseConfig(**{**defaults, **overrides})


@pytest.fixture
async def async_oracle_connection(oracle_db_container):
    """Async Oracle connection for integration tests."""
    del oracle_db_container
    conn = await oracledb.connect_async(
        user=TEST_DB_CONFIG["db_username"],
        password=TEST_DB_CONFIG["db_password"],
        dsn=TEST_DB_CONFIG["db_dsn"],
    )
    try:
        yield conn
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# AgentSpec / WayFlow constants
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_PROVIDER = "ollama"
OLLAMA_MODEL = "qwen3:8b"

MOCK_SERVER_URL = "http://127.0.0.1:8001/mcp"
MOCK_API_KEY = "test-key"

SAMPLE_CLIENT_SETTINGS = {
    "ll_model": {
        "provider": "ollama",
        "id": "qwen3:8b",
        "max_tokens": 512,
        "temperature": 0.1,
        "top_p": 1,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "chat_history": True,
    },
    "database": {
        "alias": "CORE",
    },
    "vector_search": {
        "discovery": True,
        "rephrase": True,
        "grade": True,
        "top_k": 4,
        "score_threshold": 0.85,
        "search_type": "Similarity",
    },
}

# Typed ClientSettings object for runtime tests that now require it.
from server.app.core.schemas import ClientSettings  # noqa: E402

SAMPLE_CLIENT_SETTINGS_OBJ = ClientSettings.model_validate(SAMPLE_CLIENT_SETTINGS)


MOCK_SYSTEM_PROMPT = "You are a test assistant."


# ---------------------------------------------------------------------------
# Model configs fixture (used by LiteLlmModelSpec)
# ---------------------------------------------------------------------------


from server.app.models.schemas import ModelConfig  # noqa: E402


@pytest.fixture(autouse=True)
def _ensure_model_configs():
    """Ensure ollama/qwen3:8b and openai/gpt-4o exist in model_configs for tests.

    LiteLlmModelSpec requires the model to be present in settings.model_configs.
    """
    original = settings.model_configs[:]
    defaults = [
        ModelConfig(provider="ollama", id="qwen3:8b", type="ll", api_base="http://localhost:11434"),
        ModelConfig(provider="openai", id="gpt-4o", type="ll"),
    ]
    existing = {(mc.provider, mc.id) for mc in settings.model_configs}
    for mc in defaults:
        if (mc.provider, mc.id) not in existing:
            settings.model_configs.append(mc)
    yield
    settings.model_configs = original


# ---------------------------------------------------------------------------
# AgentSpec / WayFlow helpers
# ---------------------------------------------------------------------------


def mock_flow(content: str = "answer", execute_side_effect: Exception | None = None) -> MagicMock:
    """Create a mock WayFlow flow with a canned response."""
    if not WAYFLOWCORE_AVAILABLE:
        pytest.skip("wayflowcore not installed")
    mock = MagicMock(spec=RuntimeFlow)
    mock_conv = MagicMock(spec=Conversation)
    mock_status = MagicMock()
    mock_status.output_values = {"answer": content}
    mock_conv.execute_async = AsyncMock(return_value=mock_status, side_effect=execute_side_effect)
    mock_conv.get_last_message.return_value = MagicMock(content=content)
    mock.start_conversation.return_value = mock_conv
    return mock


def mock_agent_conv(
    content: str = "reply",
    execute_side_effect: Exception | None = None,
) -> tuple:
    """Create a mock Agent + Conversation wired with a real MessageList.

    Returns (agent, conv) where conv.append_user_message uses the real
    MessageList so rollback tests work correctly.
    """
    if not WAYFLOWCORE_AVAILABLE:
        pytest.skip("wayflowcore not installed")
    agent = MagicMock(spec=RuntimeAgent)
    conv = MagicMock(spec=Conversation)
    conv.execute_async = AsyncMock(side_effect=execute_side_effect)
    conv.get_last_message.return_value = MagicMock(content=content)
    conv.conversation_id = "c1"
    conv.message_list = MessageList()
    conv.status = None
    conv.append_user_message = conv.message_list.append_user_message
    agent.start_conversation.return_value = conv
    return agent, conv


def assert_flow_basics(flow: Flow, expected_id: str, expected_name: str) -> None:
    """Assert common flow structure: type, id, name, start/end nodes."""
    assert isinstance(flow, Flow)
    assert flow.id == expected_id
    assert flow.name == expected_name


def assert_flow_end_node_has_answer(flow: Flow) -> None:
    """Assert the flow's EndNode has an 'answer' output."""
    end_nodes = [n for n in flow.nodes if isinstance(n, EndNode)]
    assert end_nodes[0].outputs is not None
    output_names = [o.title for o in end_nodes[0].outputs]
    assert "answer" in output_names


def assert_flow_llm_nodes_use_litellm(flow: Flow) -> None:
    """Assert all LlmNodes in the flow use LiteLlmConfig."""
    llm_nodes = [n for n in flow.nodes if isinstance(n, LlmNode)]
    for node in llm_nodes:
        assert isinstance(node.llm_config, LiteLlmConfig)


# ---------------------------------------------------------------------------
# AgentSpec / WayFlow fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def register_factory():
    """Register the LiteLLM model factory once per test session."""
    if not WAYFLOWCORE_AVAILABLE:
        return
    register_litellm_model_factory()


@pytest.fixture
def litellm_model():
    """Create a LiteLlmModel configured for local Ollama."""
    if not WAYFLOWCORE_AVAILABLE:
        pytest.skip("wayflowcore not installed")
    return LiteLlmModel(
        provider=OLLAMA_PROVIDER,
        model_id=OLLAMA_MODEL,
        api_base=OLLAMA_BASE_URL,
        generation_config=LlmGenerationConfig.from_dict({"max_tokens": 512, "temperature": 0.1}),
    )
