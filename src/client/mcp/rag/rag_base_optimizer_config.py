"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
from typing import List
#from mcp.server.fastmcp import FastMCP
import os
from dotenv import load_dotenv
#from sentence_transformers import CrossEncoder
#from langchain_community.embeddings import HuggingFaceEmbeddings
import logging
logging.basicConfig(level=logging.INFO)



print("Successfully imported libraries and modules")

from optimizer_utils import config

from optimizer_utils import rag

CHUNKS_DIR = "chunks_temp"
data = {}

def similarity_search(question: str, max_results: int = 5) -> List[str]:
    """
    Use this tool to get the top similar information to any question that may benefit from up-to-date or domain-specific information.
    
    Args:
        question: The topic to search for
        max_results: Maximum number of results to retrieve (default: 5)
        
    Returns:
        List of information related to the question
    """
    
    print(f"Results provided for question: {question} with top {max_results}")
    chunks=["first chunk", "second chunk"]
    
    return chunks

if __name__ == "__main__":
    # Initialize and run the server
    # Load JSON file
    file_path = os.path.join(os.getcwd(), "optimizer_settings.json")
    print(file_path)
    rag.set_optimizer_settings_path(file_path)
    
    #Set your question to check if configuration is working
    question="Which kind of IDE should be used in this demo?"
    print(f"Question: {question}")
    print(f"Answer: {rag.rag_tool_base(question)}")