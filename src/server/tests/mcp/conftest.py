"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared fixtures for MCP-related tests (tools, prompts, proxies).
"""
# spell-checker: disable

import asyncio
import contextlib
import json
from copy import deepcopy
from typing import AsyncIterator, Callable, Iterator

import pytest
from fastmcp import Client
from pydantic import SecretStr

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.database.config import close_pool
from server.app.database.registry import init_core_database
from server.app.database.schemas import DatabaseConfig
from server.app.database.sql import execute_sql
from server.app.mcp.prompts.schemas import PromptConfig
from server.app.mcp.tools.registry import register_mcp_tools
from server.app.models.schemas import ModelConfig
from server.tests.conftest import make_core_db_config


@pytest.fixture(autouse=True)
def _restore_settings_state() -> Iterator[None]:
    """Snapshot settings and FastMCP provider state around each test."""
    saved_state = {
        "log_level": settings.log_level,
        "api_key": settings.api_key,
        "api_key_generated": getattr(settings, "_api_key_generated", False),
        "client_settings": deepcopy(settings.client_settings),
        "database_configs": list(settings.database_configs),
        "model_configs": list(settings.model_configs),
        "oci_configs": list(settings.oci_configs),
        "prompt_configs": list(settings.prompt_configs),
    }

    async def _list_tools() -> set[str]:
        tools = await mcp.local_provider.list_tools()
        return {tool.name for tool in tools}

    async def _list_prompts() -> set[str]:
        prompts = await mcp.local_provider.list_prompts()
        return {prompt.name for prompt in prompts}

    loop = asyncio.new_event_loop()
    try:
        original_tools = loop.run_until_complete(_list_tools())
        original_prompts = loop.run_until_complete(_list_prompts())
    finally:
        loop.close()

    yield

    for attr, value in (
        ("log_level", saved_state["log_level"]),
        ("api_key", saved_state["api_key"]),
    ):
        setattr(settings, attr, value)
    object.__setattr__(settings, "_api_key_generated", saved_state["api_key_generated"])
    settings.client_settings = deepcopy(saved_state["client_settings"])
    settings.database_configs = list(saved_state["database_configs"])
    settings.model_configs = list(saved_state["model_configs"])
    settings.oci_configs = list(saved_state["oci_configs"])
    settings.prompt_configs = list(saved_state["prompt_configs"])

    async def _cleanup_provider() -> None:
        tools = await mcp.local_provider.list_tools()
        for tool in tools:
            if tool.name not in original_tools:
                with contextlib.suppress(KeyError):
                    mcp.local_provider.remove_tool(tool.name)
        prompts = await mcp.local_provider.list_prompts()
        for prompt in prompts:
            if prompt.name not in original_prompts:
                with contextlib.suppress(KeyError):
                    mcp.local_provider.remove_prompt(prompt.name)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_cleanup_provider())
    finally:
        loop.close()


@pytest.fixture(name="model_config_factory")
def model_config_factory_fixture() -> Iterator[Callable[..., ModelConfig]]:
    """Factory to append ModelConfig entries to settings.model_configs."""

    created: list[ModelConfig] = []

    def _factory(
        *,
        provider: str,
        model_id: str,
        model_type: str,
        enabled: bool = True,
        api_key: str | None = "sk-test",
    ) -> ModelConfig:
        config = ModelConfig(
            provider=provider,
            id=model_id,
            type=model_type,  # type: ignore[arg-type]
            enabled=enabled,
            api_key=SecretStr(api_key) if api_key is not None else None,
            status="available",
        )
        settings.model_configs.append(config)
        created.append(config)
        return config

    yield _factory

    for config in created:
        with contextlib.suppress(ValueError):
            settings.model_configs.remove(config)


@pytest.fixture(name="prompt_config_factory")
def prompt_config_factory_fixture() -> Iterator[Callable[[str, str], PromptConfig]]:
    """Factory to inject PromptConfig entries."""

    created: list[PromptConfig] = []

    def _factory(name: str, text: str, *, title: str | None = None, tags: list[str] | None = None) -> PromptConfig:
        prompt = PromptConfig(
            name=name,
            title=title or name,
            description="",
            tags=tags or [],
            text=text,
        )
        settings.prompt_configs.append(prompt)
        created.append(prompt)
        return prompt

    yield _factory

    for prompt in created:
        with contextlib.suppress(ValueError):
            settings.prompt_configs.remove(prompt)


@pytest.fixture
def configure_ll_model(model_config_factory) -> Iterator[Callable[[str, str], None]]:
    """Provide helper to configure an enabled LL model."""

    def _configure(provider: str, model_id: str) -> None:
        settings.client_settings.ll_model.provider = provider
        settings.client_settings.ll_model.id = model_id
        model_config_factory(
            provider=provider,
            model_id=model_id,
            model_type="ll",
            enabled=True,
        )

    yield _configure


@pytest.fixture(name="vector_db_config")
async def vector_db_config_fixture(oracle_db_container) -> AsyncIterator[DatabaseConfig]:
    """Provision a CORE database config with an active pool."""
    del oracle_db_container
    cfg = make_core_db_config()
    settings.database_configs = [cfg]
    settings.client_settings.database.alias = cfg.alias
    cfg.pool = await init_core_database(cfg)
    assert cfg.pool is not None
    try:
        yield cfg
    finally:
        await close_pool(cfg.pool)
        cfg.pool = None
        settings.database_configs = []


@pytest.fixture
async def mcp_client():
    """In-process MCP protocol client connected to the real FastMCP server."""
    client = Client(mcp)
    async with client:
        yield client


@pytest.fixture
def _register_tools():
    """Ensure the 4 VS tools are registered on the MCP server."""
    register_mcp_tools()


@pytest.fixture
async def vector_store_table(vector_db_config: DatabaseConfig) -> AsyncIterator[str]:
    """Create a disposable GENAI-commented table for discovery tests."""
    table_name = "PYTEST_GENAI_TABLE"
    payload = {
        "alias": "DOCS",
        "description": "Test documents",
        "model": "openai/text-embed",
        "chunk_size": 512,
        "chunk_overlap": 64,
        "distance_metric": "COSINE",
        "index_type": "HNSW",
    }

    assert vector_db_config.pool is not None
    async with vector_db_config.pool.acquire() as conn:
        await execute_sql(conn, f'DROP TABLE "{table_name}" PURGE')
        await execute_sql(conn, f'CREATE TABLE "{table_name}" (id NUMBER)')
        await execute_sql(conn, f"COMMENT ON TABLE \"{table_name}\" IS 'GENAI: {json.dumps(payload)}'")
        await conn.commit()

    try:
        yield table_name
    finally:
        assert vector_db_config.pool is not None
        async with vector_db_config.pool.acquire() as conn:
            await execute_sql(conn, f'DROP TABLE "{table_name}" PURGE')
            await conn.commit()
