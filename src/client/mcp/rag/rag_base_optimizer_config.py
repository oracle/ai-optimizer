"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
import sys
from typing import List
import os
from dotenv import load_dotenv
import logging
logging.basicConfig(level=logging.INFO)



logging.info("Successfully imported libraries and modules")

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
    
    logging.info(f"Results provided for question: {question} with top {max_results}")
    chunks=["first chunk", "second chunk"]
    
    return chunks

if __name__ == "__main__":
    # Initialize and run the server
    # Load JSON file
    file_path = os.path.join(os.getcwd(), "optimizer_settings.json")
    logging.info(file_path)
    rag.set_optimizer_settings_path(file_path)

    if len(sys.argv) > 1:
        question = sys.argv[1]
        print(question)
        logging.info(f"Question: {sys.argv[1]}")
        logging.info(f"\n\nAnswer: {rag.rag_tool_base(question)}")
    else:
        logging.info("No question provided.")