"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore

from typing import Optional
from server.api.core import bootstrap

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.prompts")


def get_prompts(
    category: Optional[schema.PromptCategoryType] = None,
    name: Optional[schema.PromptNameType] = None
) -> list[schema.Prompt]:
    """
    Return prompts filtered by category and optionally name.
    If neither is provided, return all prompts.
    """
    prompt_objects = bootstrap.PROMPT_OBJECTS

    if category is None and name is None:
        return prompt_objects

    if name is not None and category is None:
        raise ValueError("Cannot filter prompts by name without specifying category.")

    logger.info("Filtering prompts by category: %s", category)
    prompts_filtered = [p for p in prompt_objects if p.category == category]

    if name is not None:
        logger.info("Further filtering prompts by name: %s", name)
        prompts_filtered = [p for p in prompts_filtered if p.name == name]
        if not prompts_filtered:
            raise ValueError(f"Prompt: {name} ({category}) not found.")

    return prompts_filtered
