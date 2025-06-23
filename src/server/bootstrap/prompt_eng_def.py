"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# pylint: disable=line-too-long
from common.schema import Prompt
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.bootstrap.prompt_eng_def")


def main() -> list[Prompt]:
    """Define example Prompts"""
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

    # Check for Duplicates
    unique_entries = set()
    for prompt in prompt_eng_list:
        if (prompt["name"], prompt["category"]) in unique_entries:
            raise ValueError(f"Prompt '{prompt['name']}':'{prompt['category']}' already exists.")
        unique_entries.add((prompt["name"], prompt["category"]))

    prompt_objects = [Prompt(**prompt_dict) for prompt_dict in prompt_eng_list]

    return prompt_objects


if __name__ == "__main__":
    main()
