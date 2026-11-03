"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP catalog ordering and cache hints.
"""

from collections.abc import Sequence

import pytest
from fastmcp import Client
from fastmcp.prompts import Prompt
from fastmcp.resources import ResourceTemplate, TextResource
from fastmcp.server.providers import Provider
from fastmcp.server.transforms import Transform
from fastmcp.tools import Tool
from mcp.client.caching import CacheConfig
from pydantic import AnyUrl

from server.app.core.mcp import _create_mcp_server
from server.app.mcp.transforms import DeterministicCatalogTransform

pytestmark = [pytest.mark.unit]


def _value() -> str:
    return "value"


def _templated_value(item: str) -> str:
    return item


class _StaticToolProvider(Provider):
    def __init__(self, tools: Sequence[Tool]) -> None:
        super().__init__()
        self.tools = tools

    async def _list_tools(self) -> Sequence[Tool]:
        return self.tools


class _CountingTransform(Transform):
    def __init__(self) -> None:
        self.tool_lists = 0

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        self.tool_lists += 1
        return tools


async def test_transform_sorts_every_catalog_by_protocol_identity():
    transform = DeterministicCatalogTransform()
    tools = [
        Tool.from_function(_value, name="zeta"),
        Tool.from_function(_value, name="alpha", version="2"),
        Tool.from_function(_value, name="alpha", version="1"),
    ]
    prompts = [
        Prompt.from_function(_value, name="zeta"),
        Prompt.from_function(_value, name="alpha", version="2"),
        Prompt.from_function(_value, name="alpha", version="1"),
    ]
    resources = [
        TextResource(uri=AnyUrl("test://zeta"), name="zeta", text="zeta"),
        TextResource(uri=AnyUrl("test://alpha"), name="alpha-2", text="alpha", version="2"),
        TextResource(uri=AnyUrl("test://alpha"), name="alpha-1", text="alpha", version="1"),
    ]
    templates = [
        ResourceTemplate.from_function(_templated_value, "test://zeta/{item}", name="zeta"),
        ResourceTemplate.from_function(_templated_value, "test://alpha/{item}", name="alpha-2", version="2"),
        ResourceTemplate.from_function(_templated_value, "test://alpha/{item}", name="alpha-1", version="1"),
    ]

    sorted_tools = await transform.list_tools(tools)
    sorted_prompts = await transform.list_prompts(prompts)
    sorted_resources = await transform.list_resources(resources)
    sorted_templates = await transform.list_resource_templates(templates)

    assert [(tool.name, tool.version) for tool in sorted_tools] == [
        ("alpha", "1"),
        ("alpha", "2"),
        ("zeta", None),
    ]
    assert [(prompt.name, prompt.version) for prompt in sorted_prompts] == [
        ("alpha", "1"),
        ("alpha", "2"),
        ("zeta", None),
    ]
    assert [(str(resource.uri), resource.version) for resource in sorted_resources] == [
        ("test://alpha", "1"),
        ("test://alpha", "2"),
        ("test://zeta", None),
    ]
    assert [(template.uri_template, template.version) for template in sorted_templates] == [
        ("test://alpha/{item}", "1"),
        ("test://alpha/{item}", "2"),
        ("test://zeta/{item}", None),
    ]


async def test_server_sorts_local_and_namespaced_provider_tools():
    server = _create_mcp_server(5)
    server.tool(name="zulu")(_value)
    provider = _StaticToolProvider([Tool.from_function(_value, name="alpha")])
    server.add_provider(provider, namespace="sqlcl")

    first = [tool.name for tool in await server.list_tools()]
    second = [tool.name for tool in await server.list_tools()]

    assert first == second == ["sqlcl_alpha", "zulu"]


async def test_modern_client_caches_catalog_until_private_ttl_expires():
    now = [100.0]
    counter = _CountingTransform()
    server = _create_mcp_server(5)
    server.add_transform(counter)
    server.tool(name="cached_tool")(_value)

    async with Client(
        server,
        mode="2026-07-28",
        cache=CacheConfig(clock=lambda: now[0]),
    ) as client:
        discovery_lists = counter.tool_lists
        first = await client.list_tools_mcp()
        second = await client.list_tools_mcp()
        server.tool(name="new_tool")(_value)
        now[0] += 6
        third = await client.list_tools_mcp()

    assert [tool.name for tool in first.tools] == ["cached_tool"]
    assert second == first
    assert [tool.name for tool in third.tools] == ["cached_tool", "new_tool"]
    assert first.ttl_ms == 5000
    assert first.cache_scope == "private"
    assert counter.tool_lists - discovery_lists == 2


async def test_zero_ttl_disables_catalog_reuse():
    counter = _CountingTransform()
    server = _create_mcp_server(0)
    server.add_transform(counter)
    server.tool(name="uncached_tool")(_value)

    async with Client(server, mode="2026-07-28", cache=True) as client:
        discovery_lists = counter.tool_lists
        first = await client.list_tools_mcp()
        second = await client.list_tools_mcp()

    assert first.ttl_ms == 0
    assert second.ttl_ms == 0
    assert counter.tool_lists - discovery_lists == 2
