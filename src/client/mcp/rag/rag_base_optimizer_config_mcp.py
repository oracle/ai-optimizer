"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import json  # pylint: disable=unused-import
import logging
import os  # pylint: disable=unused-import
from typing import List  # pylint: disable=unused-import

from dotenv import load_dotenv  # pylint: disable=unused-import
from langchain_core.output_parsers import StrOutputParser  # pylint: disable=unused-import
from langchain_core.prompts import PromptTemplate  # pylint: disable=unused-import
from langchain_core.runnables import RunnablePassthrough  # pylint: disable=unused-import
from mcp.server.fastmcp import FastMCP

from optimizer_utils import rag  # pylint: disable=import-error

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")


logging.info("Successfully imported libraries and modules")

CHUNKS_DIR = "chunks_temp"
data = {}

# Initialize FastMCP server
mcp = FastMCP("rag", port=9090)  # Remote client
# mcp = FastMCP("rag") #Local


@mcp.tool()
def rag_tool(question: str) -> str:
    """
    Use this tool to answer any question that may benefit from up-to-date or domain-specific information.

    Args:
        question: the question for which are you looking for an answer

    Returns:
        JSON string with answer
    """

    answer = rag.rag_tool_base(question)

    return f"{answer}"


if __name__ == "__main__":
    # To dinamically change Tool description: not used but in future maybe
    rag_tool_desc = [
        """
    Use this tool to answer any question that may benefit from up-to-date or domain-specific information.
    
    Args:
        question: the question for which are you looking for an answer
        
    Returns:
        JSON string with answer
    """
    ]

    # Initialize and run the server

    # Set optimizer_settings.json file ABSOLUTE path
    rag.set_optimizer_settings_path("optimizer_settings.json")

    # Change according protocol type

    # mcp.run(transport='stdio')
    # mcp.run(transport='sse')
    mcp.run(transport="streamable-http")
