"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP prompt registry and startup lifecycle.
"""
# spell-checker:ignore fastmcp

import contextlib
import logging

from fastmcp.prompts import Prompt

from server.app.core.mcp import mcp
from server.app.core.settings import settings

from .defaults import FACTORY_PROMPTS
from .schemas import PromptConfig

LOGGER = logging.getLogger(__name__)


def find_prompt(name: str) -> PromptConfig | None:
    """Case-insensitive lookup by prompt name."""
    for pc in settings.prompt_configs:
        if pc.name.lower() == name.lower():
            return pc
    return None


def prompt_to_response(pc: PromptConfig) -> dict:
    """Build a response dict with name, description, text."""
    return pc.model_dump(include={"name", "description", "text"})


def load_factory_prompts() -> None:
    """Seed ``settings.prompt_configs`` entirely from FACTORY_PROMPTS.

    Called once during Phase 3 to establish the authoritative baseline.
    Any previous contents of ``prompt_configs`` are replaced.
    """
    settings.prompt_configs = [
        PromptConfig(
            name=d["name"],
            title=d["title"],
            description=d.get("description", ""),
            tags=d.get("tags", []),
            text=d["text"],
        )
        for d in FACTORY_PROMPTS
    ]
    LOGGER.info("Loaded %d factory prompt(s)", len(settings.prompt_configs))


def reconcile_prompt_customizations(customizations: list[PromptConfig]) -> None:
    """Overlay customized text onto the FACTORY baseline.

    For each prompt in ``settings.prompt_configs``, if a matching
    customization exists (by name), its ``text`` is applied.
    customizations for prompts not present in the factory set are
    silently ignored (they are deprecated).
    """
    factory_by_name = {pc.name: pc for pc in settings.prompt_configs}
    applied = 0
    for custom in customizations:
        if custom.name in factory_by_name:
            factory_by_name[custom.name].text = custom.text
            applied += 1
        else:
            LOGGER.debug("Ignoring customization for deprecated prompt: %s", custom.name)
    LOGGER.info("Reconciled %d prompt customization(s)", applied)


def get_factory_text(name: str) -> str | None:
    """Return the FACTORY text for *name*, or ``None`` if not found."""
    for d in FACTORY_PROMPTS:
        if d["name"] == name:
            return d["text"]
    return None


def register_mcp_prompt(pc: PromptConfig) -> None:
    """Register (or re-register) a single PromptConfig with FastMCP.

    Removes any existing prompt with the same name before adding.
    """
    with contextlib.suppress(KeyError):
        mcp.local_provider.remove_prompt(pc.name)

    def _prompt_fn() -> str:
        return pc.text

    prompt = Prompt.from_function(
        fn=_prompt_fn,
        name=pc.name,
        title=pc.title,
        description=pc.description,
        tags=set(pc.tags) if pc.tags else None,
    )
    mcp.add_prompt(prompt)


def register_mcp_prompts() -> None:
    """Register all prompt_configs with FastMCP."""
    for pc in settings.prompt_configs:
        register_mcp_prompt(pc)
    LOGGER.info("Registered %d MCP prompt(s)", len(settings.prompt_configs))
