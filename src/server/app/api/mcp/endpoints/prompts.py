"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for managing MCP prompt configurations.
"""

from fastapi import APIRouter, HTTPException

from server.app.api.mcp.schemas.prompts import PromptResponse, PromptUpdate
from server.app.core.settings import settings
from server.app.database.settings import persist_settings
from server.app.mcp.prompts.registry import register_mcp_prompt
from server.app.mcp.prompts.schemas import PromptConfig

auth = APIRouter(prefix='/prompts')


def _find_prompt(name: str) -> PromptConfig | None:
    """Case-insensitive lookup by prompt name."""
    for pc in settings.prompt_configs:
        if pc.name.lower() == name.lower():
            return pc
    return None


@auth.get('', response_model=list[PromptResponse])
async def list_prompts():
    """Return all prompt configurations."""
    return [pc.model_dump() for pc in settings.prompt_configs]


@auth.get('/{name}', response_model=PromptResponse)
async def get_prompt(name: str):
    """Return a single prompt configuration by name (case-insensitive)."""
    pc = _find_prompt(name)
    if pc is None:
        raise HTTPException(status_code=404, detail=f'Prompt not found: {name}')
    return pc.model_dump()


@auth.put('/{name}', response_model=PromptResponse)
async def update_prompt(name: str, body: PromptUpdate):
    """Update the text of a prompt (sets customized=True)."""
    pc = _find_prompt(name)
    if pc is None:
        raise HTTPException(status_code=404, detail=f'Prompt not found: {name}')
    pc.text = body.text
    pc.customized = True
    register_mcp_prompt(pc)
    await persist_settings()
    return pc.model_dump()


@auth.post('/{name}/reset', response_model=PromptResponse)
async def reset_prompt(name: str):
    """Reset a prompt to its default text (sets customized=False)."""
    pc = _find_prompt(name)
    if pc is None:
        raise HTTPException(status_code=404, detail=f'Prompt not found: {name}')
    pc.text = pc.default_text
    pc.customized = False
    register_mcp_prompt(pc)
    await persist_settings()
    return pc.model_dump()
