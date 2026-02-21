"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP prompt registry and startup lifecycle.
"""

import logging

from fastmcp.prompts import Prompt

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from .defaults import DEFAULT_PROMPTS
from .schemas import PromptConfig

LOGGER = logging.getLogger(__name__)


def apply_prompt_defaults() -> None:
    """Apply code-provided defaults to prompt_configs.

    - Prompts no longer in DEFAULT_PROMPTS are removed (customized or not).
    - Existing prompts: always refresh ``default_text`` with the code
      version.  If not customized, also update ``text``.
    - New prompts: appended with ``customized=False``.
    """
    default_names = {d["name"] for d in DEFAULT_PROMPTS}
    existing_by_name = {pc.name: pc for pc in settings.prompt_configs}

    # Remove prompts no longer defined in code
    removed = [name for name in existing_by_name if name not in default_names]
    if removed:
        settings.prompt_configs = [pc for pc in settings.prompt_configs if pc.name in default_names]
        LOGGER.info("Removed %d deprecated prompt(s): %s", len(removed), ", ".join(removed))

    # Update existing / add new
    existing_by_name = {pc.name: pc for pc in settings.prompt_configs}
    for default in DEFAULT_PROMPTS:
        name = default["name"]

        if name in existing_by_name:
            pc = existing_by_name[name]
            pc.default_text = default["text"]
            if not pc.customized:
                pc.text = default["text"]
        else:
            settings.prompt_configs.append(
                PromptConfig(
                    name=name,
                    title=default["title"],
                    description=default.get("description", ""),
                    tags=default.get("tags", []),
                    text=default["text"],
                    default_text=default["text"],
                    customized=False,
                )
            )

    LOGGER.info("Applied prompt defaults (%d total)", len(settings.prompt_configs))


def register_mcp_prompt(pc: PromptConfig) -> None:
    """Register (or re-register) a single PromptConfig with FastMCP.

    Removes any existing prompt with the same name before adding.
    """
    try:
        mcp.local_provider.remove_prompt(pc.name)
    except KeyError:
        pass

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
