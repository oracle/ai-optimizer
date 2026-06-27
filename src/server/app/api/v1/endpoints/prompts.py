"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

CRUD endpoints for prompt management.
"""

from fastapi import APIRouter, HTTPException

from server.app.api.v1.endpoints.chat import get_orchestrator
from server.app.api.v1.schemas.prompts import PromptResponse, PromptUpdate
from server.app.core.constants import PERSIST_FAIL_DETAIL as _PERSIST_FAIL
from server.app.core.settings import _settings_lock, settings
from server.app.database.settings import persist_settings
from server.app.mcp.prompts.registry import (
    find_prompt,
    get_factory_text,
    prompt_to_response,
    register_mcp_prompt,
    register_mcp_prompts,
)

auth = APIRouter(prefix="/prompts")


@auth.put("/{name}", response_model=PromptResponse)
async def update_prompt(name: str, body: PromptUpdate):
    """Update the text of a prompt."""
    async with _settings_lock:
        pc = find_prompt(name)
        if pc is None:
            raise HTTPException(status_code=404, detail=f"Prompt not found: {name}")
        old_text = pc.text
        pc.text = body.text
        register_mcp_prompt(pc)
        if not await persist_settings():
            pc.text = old_text
            register_mcp_prompt(pc)
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
    await get_orchestrator().refresh_prompts()
    return prompt_to_response(pc)


@auth.post("/reset", response_model=list[PromptResponse])
async def reset_all_prompts():
    """Reset all prompts to their factory text."""
    async with _settings_lock:
        saved = {pc.name: pc.text for pc in settings.prompt_configs}
        for pc in settings.prompt_configs:
            factory_text = get_factory_text(pc.name)
            if factory_text is not None:
                pc.text = factory_text
        register_mcp_prompts()
        if not await persist_settings():
            for pc in settings.prompt_configs:
                if pc.name in saved:
                    pc.text = saved[pc.name]
            register_mcp_prompts()
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
    await get_orchestrator().refresh_prompts()
    return [prompt_to_response(pc) for pc in settings.prompt_configs]


@auth.post("/{name}/reset", response_model=PromptResponse)
async def reset_prompt(name: str):
    """Reset a prompt to its factory text."""
    async with _settings_lock:
        pc = find_prompt(name)
        if pc is None:
            raise HTTPException(status_code=404, detail=f"Prompt not found: {name}")
        factory_text = get_factory_text(pc.name)
        if factory_text is None:
            raise HTTPException(status_code=404, detail=f"No factory text for prompt: {name}")
        old_text = pc.text
        pc.text = factory_text
        register_mcp_prompt(pc)
        if not await persist_settings():
            pc.text = old_text
            register_mcp_prompt(pc)
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
    await get_orchestrator().refresh_prompts()
    return prompt_to_response(pc)
