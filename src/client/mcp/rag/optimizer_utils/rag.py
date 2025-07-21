"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from typing import List
from mcp.server.fastmcp import FastMCP
import os
from dotenv import load_dotenv

# from sentence_transformers import CrossEncoder
# from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
import json
import logging

logging.basicConfig(level=logging.DEBUG)

from optimizer_utils import config

_optimizer_settings_path = ""


def set_optimizer_settings_path(path: str):
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
    with open(_optimizer_settings_path, "r") as file:
        data = json.load(file)
        try:
            embeddings = config.get_embeddings(data)

            print("Embedding successful!")
            knowledge_base = config.get_vectorstore(data, embeddings)
            print("DB Connection successful!")

            print("knowledge_base successful!")
            user_question = question
            # result_chunks=knowledge_base.similarity_search(user_question, 5)

            for d in data["prompt_configs"]:
                if d["name"] == data["client_settings"]["prompts"]["sys"]:
                    rag_prompt = d["prompt"]

            template = """DOCUMENTS: {context} \n""" + rag_prompt + """\nQuestion: {question} """
            # template = """Answer the question based only on the following context:{context} Question: {question} """
            print(template)
            prompt = PromptTemplate.from_template(template)
            print("before retriever")
            print(data["client_settings"]["rag"]["top_k"])
            retriever = knowledge_base.as_retriever(search_kwargs={"k": data["client_settings"]["rag"]["top_k"]})
            print("after retriever")

            # Initialize the LLM
            llm = config.get_llm(data)

            chain = {"context": retriever, "question": RunnablePassthrough()} | prompt | llm | StrOutputParser()
            print("pre-chain successful!")
            answer = chain.invoke(user_question)

            # print(f"Results provided for question: {question}")
            # print(f"{answer}")
        except Exception as e:
            print(e)
            print("Connection failed!")
            answer = ""

    return f"{answer}"
