"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP catalog transforms.
"""

from collections.abc import Sequence

from fastmcp.prompts import Prompt
from fastmcp.resources import Resource, ResourceTemplate
from fastmcp.server.transforms import Transform
from fastmcp.tools import Tool


def _catalog_key(identifier: object, version: str | None) -> tuple[str, str]:
    return str(identifier), version or ""


class DeterministicCatalogTransform(Transform):
    """Order MCP catalogs by protocol identity and component version."""

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return sorted(tools, key=lambda tool: _catalog_key(tool.name, tool.version))

    async def list_prompts(self, prompts: Sequence[Prompt]) -> Sequence[Prompt]:
        return sorted(prompts, key=lambda prompt: _catalog_key(prompt.name, prompt.version))

    async def list_resources(self, resources: Sequence[Resource]) -> Sequence[Resource]:
        return sorted(resources, key=lambda resource: _catalog_key(resource.uri, resource.version))

    async def list_resource_templates(self, templates: Sequence[ResourceTemplate]) -> Sequence[ResourceTemplate]:
        return sorted(
            templates,
            key=lambda template: _catalog_key(template.uri_template, template.version),
        )
