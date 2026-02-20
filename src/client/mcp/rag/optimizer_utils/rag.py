"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import json
import logging
import os  # pylint: disable=unused-import
from typing import List  # pylint: disable=unused-import

from dotenv import load_dotenv  # pylint: disable=unused-import
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from mcp.server.fastmcp import FastMCP  # pylint: disable=unused-import

from optimizer_utils import config  # pylint: disable=import-error

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.DEBUG, format="%(name)s - %(levelname)s - %(message)s")

_optimizer_settings_path = ""


def set_optimizer_settings_path(path: str):
    """
    Set the path to the optimizer settings JSON file.

    Args:
        path: Path to the optimizer_settings.json file
    """
    global _optimizer_settings_path
    _optimizer_settings_path = path


def rag_tool_base(question: str) -> str:
    """
    Use this tool to answer any question that may benefit from up-to-date or domain-specific information.

    Args:
        question: the question for which are you looking for an answer

    Returns:
        JSON string with answer
    """
    with open(_optimizer_settings_path, "r", encoding="utf-8") as file:
        data = json.load(file)
        LOGGER.info("Json loaded!")
        try:
            embeddings = config.get_embeddings(data)
            LOGGER.info("got embeddings!")
            knowledge_base = config.get_vectorstore(data, embeddings)
            LOGGER.info("knowledge_base connection successful!")
            user_question = question
            LOGGER.info("start looking for prompts")
            prompt_by_name = {m["name"]: m for m in data["prompt_configs"]}
            ctx_prompt = prompt_by_name.get("optimizer_context-default", {}).get("text", "")
            sys_prompt = prompt_by_name.get("optimizer_vs-no-tools-default", {}).get("text", "")

            LOGGER.info("sys_prompt:")
            LOGGER.info(sys_prompt)
            template = sys_prompt + """\n# DOCUMENTS :\n {context} \n""" + """\n # Question: {question} """
            LOGGER.info(template)
            LOGGER.info("user_question: %s", user_question)
            prompt = PromptTemplate.from_template(template)
            LOGGER.info(data["client_settings"]["vector_search"]["top_k"])
            retriever = knowledge_base.as_retriever(
                search_kwargs={"k": data["client_settings"]["vector_search"]["top_k"]}
            )

            docs = knowledge_base.similarity_search(user_question, k=data["client_settings"]["vector_search"]["top_k"])

            for i, d in enumerate(docs, 1):
                LOGGER.info("----------------------------------------------------------")
                LOGGER.info("DOC index: %s", i)
                LOGGER.info("METADATA=%s", d.metadata)
                LOGGER.info("CONTENT:\n%s", d.page_content)
            LOGGER.info("END CHUNKS FOUND")

            llm = config.get_llm(data)

            chain = {"context": retriever, "question": RunnablePassthrough()} | prompt | llm | StrOutputParser()

            answer = chain.invoke(user_question)

        except Exception as e:
            LOGGER.info(e)
            LOGGER.info("Connection failed!")
            answer = ""

    return f"{answer}"
