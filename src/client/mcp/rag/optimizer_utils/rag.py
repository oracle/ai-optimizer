"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
from typing import List
from mcp.server.fastmcp import FastMCP
import os
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
import json
import logging
logging.basicConfig(level=logging.DEBUG)

from optimizer_utils import config

_optimizer_settings_path= ""

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
        logging.info("Json loaded!")
        try: 
        
            embeddings = config.get_embeddings(data)
        
            logging.info("Embedding successful!")
            knowledge_base = config.get_vectorstore(data,embeddings)
            logging.info("DB Connection successful!")
    
            logging.info("knowledge_base successful!")
            user_question = question
            logging.info("start looking for prompts")
            for d in data["prompts_config"]:
                if d["name"]==data["user_settings"]["prompts"]["sys"]:
             
                    rag_prompt=d["prompt"]
            
            logging.info("rag_prompt:")
            logging.info(rag_prompt)
            template = """DOCUMENTS: {context} \n"""+rag_prompt+"""\nQuestion: {question} """
            logging.info(template)
            prompt = PromptTemplate.from_template(template)
            logging.info("before retriever")
            logging.info(data["user_settings"]["vector_search"]["top_k"])
            retriever = knowledge_base.as_retriever(search_kwargs={"k": data["user_settings"]["vector_search"]["top_k"]})
            logging.info("after retriever")
        

            # Initialize the LLM
            llm =  config.get_llm(data)

            chain = (
                {"context": retriever, "question": RunnablePassthrough()}
                    | prompt
                    | llm
                    | StrOutputParser()
            )
            logging.info("pre-chain successful!")
            answer = chain.invoke(user_question)


        except Exception as e:
            logging.info(e)
            logging.info("Connection failed!")
            answer=""

    return f"{answer}"
