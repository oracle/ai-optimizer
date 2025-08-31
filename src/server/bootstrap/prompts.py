"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore configfile
# pylint: disable=line-too-long

from server.bootstrap.configfile import ConfigStore

from common.schema import Prompt
from common import logging_config

logger = logging_config.logging.getLogger("bootstrap.prompts")


def normalize_prompt_text(p: dict) -> dict:
    """Ensure prompt is a flat string"""
    text = p.get("prompt")
    if isinstance(text, tuple):
        p["prompt"] = "".join(text)
    return p


def main() -> list[Prompt]:
    """Define example Prompts"""
    logger.debug("*** Bootstrapping Prompts - Start")
    prompt_eng_list = [
        {
            "name": "Basic Example",
            "category": "sys",
            "prompt": "You are a friendly, helpful assistant.",
        },
        {
            "name": "Vector Search Example",
            "category": "sys",
            "prompt": (
                "You are an assistant for question-answering tasks, be concise.  "
                "Use the retrieved DOCUMENTS to answer the user input as accurately as possible. "
                "Keep your answer grounded in the facts of the DOCUMENTS and reference the DOCUMENTS where possible. "
                "If there ARE DOCUMENTS, you should be able to answer.  "
                "If there are NO DOCUMENTS, respond only with 'I am sorry, but cannot find relevant sources.'"
            ),
        },
        {
            "name": "Custom",
            "category": "sys",
            "prompt": (
                "You are an assistant for question-answering tasks.  Use the retrieved DOCUMENTS "
                "and history to answer the question.  If there are no DOCUMENTS or the DOCUMENTS "
                "do not contain the specific information, do your best to still answer."
            ),
        },
        {
            "name": "Basic Example",
            "category": "ctx",
            "prompt": (
                "Rephrase the latest user input into a standalone search query optimized for vector retrieval. "
                "Use only the user's prior inputs for context, ignoring system responses. "
                "Remove conversational elements like confirmations or clarifications, focusing solely on the core topic and keywords."
            ),
        },
        {
            "name": "Custom",
            "category": "ctx",
            "prompt": (
                "Ignore chat history and context and do not reformulate the question. "
                "DO NOT answer the question. Simply return the original query AS-IS."
            ),
        },
    ]

    # Normalize built-in prompts
    prompt_eng_list = [normalize_prompt_text(p.copy()) for p in prompt_eng_list]

    # Merge in prompts from ConfigStore
    configuration = ConfigStore.get()
    if configuration and configuration.prompt_configs:
        logger.debug("Merging %d prompt(s) from configuration", len(configuration.prompt_configs))
        existing = {(p["name"], p["category"]): p for p in prompt_eng_list}

        for new_prompt in configuration.prompt_configs:
            profile_dict = new_prompt.model_dump()
            profile_dict = normalize_prompt_text(profile_dict)
            key = (profile_dict["name"], profile_dict["category"])

            if key in existing:
                if existing[key]["prompt"] != profile_dict["prompt"]:
                    logger.info("Overriding prompt: %s / %s", key[0], key[1])
            else:
                logger.info("Adding new prompt: %s / %s", key[0], key[1])

            existing[key] = profile_dict

        prompt_eng_list = list(existing.values())

    # Check for duplicates
    unique_entries = set()
    for prompt in prompt_eng_list:
        key = (prompt["name"], prompt["category"])
        if key in unique_entries:
            raise ValueError(f"Prompt '{prompt['name']}':'{prompt['category']}' already exists.")
        unique_entries.add(key)

    # Convert to Model objects
    prompt_objects = [Prompt(**prompt_dict) for prompt_dict in prompt_eng_list]
    logger.info("Loaded %i Prompts.", len(prompt_objects))
    logger.debug("*** Bootstrapping Prompts - End")
    return prompt_objects


if __name__ == "__main__":
    main()
