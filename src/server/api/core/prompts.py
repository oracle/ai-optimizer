"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore

from typing import Optional, Union
from server.api.core import bootstrap

from common.schema import PromptCategoryType, PromptNameType, Prompt
from common import logging_config

logger = logging_config.logging.getLogger("api.core.prompts")


def get_prompts(
    category: Optional[PromptCategoryType] = None,
    name: Optional[PromptNameType] = None
) -> Union[list[Prompt], Prompt, None]:
    """
    Return prompt filtered by category and optionally name.
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
        prompt = next((p for p in prompts_filtered if p.name == name), None)
        if prompt is None:
            raise ValueError(f"{name} ({category}) not found")
        prompts_filtered = prompt

    return prompts_filtered
