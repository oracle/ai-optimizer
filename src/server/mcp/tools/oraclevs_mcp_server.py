#!/usr/bin/env python3
"""
Standalone MCP Server for Oracle Vector Store Retriever
"""
import json
import os
import sys
from typing import Dict, Any, List
import decimal
import requests

# Add the project root to the path so we can import project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

# Import required modules from the project dependencies
try:
    from langchain_core.prompts import PromptTemplate
    from langchain_core.documents import Document
    from langchain_community.vectorstores.oraclevs import OracleVS
    from langchain_ollama import OllamaEmbeddings
    import oracledb
except ImportError as e:
    # Handle import errors gracefully
    PromptTemplate = None
    Document = None
    OracleVS = None
    OllamaEmbeddings = None
    oracledb = None

from mcp.server.fastmcp import FastMCP
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.mcp.tools.oraclevs_mcp_server")

# Initialize the MCP server
mcp = FastMCP("oraclevs")


class DecimalEncoder(json.JSONEncoder):
    """Used with json.dumps to encode decimals"""

    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        return super().default(o)


def get_database_connection():
    """Get database connection (backward compatibility)"""
    # This function is kept for backward compatibility but should not be used
    # The new implementation uses get_database_connection_from_config directly
    return get_database_connection_from_env()


def get_database_connection_from_env():
    """Get database connection from environment variables (backward compatibility)"""
    try:
        # Get database connection details from environment variables
        user = os.getenv("DB_USER")
        password = os.getenv("DB_PASSWORD")
        dsn = os.getenv("DB_DSN")
        wallet_location = os.getenv("TNS_ADMIN")
        
        if not all([user, password, dsn]):
            logger.warning("Database connection details not found in environment variables")
            return None
            
        # Create connection
        connection_params = {
            "user": user,
            "password": password,
            "dsn": dsn
        }
        
        if wallet_location:
            connection_params["wallet_location"] = wallet_location
            
        conn = oracledb.connect(**connection_params)
        logger.info("Successfully connected to database using environment variables")
        return conn
    except Exception as e:
        logger.error("Failed to connect to database using environment variables: %s", str(e))
        return None


def get_database_connection_from_config(server_url: str = None, api_key: str = None, database_alias: str = None):
    """Get database connection from server configuration API"""
    try:
        if not server_url or not api_key:
            logger.warning("Server URL or API key not provided for configuration API access")
            return None
            
        # Construct the API endpoint
        endpoint = f"{server_url.rstrip('/')}/v1/databases"
        if database_alias:
            endpoint += f"/{database_alias}"
            
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        logger.info("Fetching database configuration from: %s", endpoint)
        response = requests.get(endpoint, headers=headers, timeout=30)
        response.raise_for_status()
        
        database_config = response.json()
        
        # If we're getting all databases, find the connected one or use the first one
        if not database_alias and isinstance(database_config, list):
            # Look for a connected database first
            connected_db = next((db for db in database_config if db.get("connected", False)), None)
            if connected_db:
                database_config = connected_db
            else:
                # Use the first database if no connected one found
                database_config = database_config[0] if database_config else None
                
        if not database_config:
            logger.warning("No database configuration found")
            return None
            
        # Extract connection parameters
        connection_params = {
            "user": database_config.get("user"),
            "password": database_config.get("password"),
            "dsn": database_config.get("dsn"),
            "wallet_location": database_config.get("wallet_location"),
            "config_dir": database_config.get("config_dir", "tns_admin")
        }
        
        # Remove None values
        connection_params = {k: v for k, v in connection_params.items() if v is not None}
        
        if not all([connection_params.get("user"), connection_params.get("password"), connection_params.get("dsn")]):
            logger.warning("Incomplete database connection details in configuration")
            return None
            
        conn = oracledb.connect(**connection_params)
        logger.info("Successfully connected to database using server configuration")
        return conn
    except Exception as e:
        logger.error("Failed to connect to database using server configuration: %s", str(e))
        return None


def resolve_vector_store_name(vector_store_alias: str = None, vector_store: str = None, 
                            server_url: str = None, api_key: str = None, database_alias: str = None):
    """Resolve vector store alias to actual table name using server API"""
    try:
        # If we have the actual table name, use it directly
        if vector_store:
            return vector_store
            
        # If no alias provided, use default
        if not vector_store_alias:
            return "VECTOR_STORE"
            
        # Try to resolve alias using server API
        if not server_url or not api_key:
            logger.warning("Server URL or API key not provided for vector store alias resolution")
            return vector_store_alias
            
        # Construct the API endpoint to get database configuration
        endpoint = f"{server_url.rstrip('/')}/v1/databases"
        if database_alias:
            endpoint += f"/{database_alias}"
            
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        logger.info("Fetching database configuration for vector store resolution from: %s", endpoint)
        response = requests.get(endpoint, headers=headers, timeout=30)
        response.raise_for_status()
        
        database_config = response.json()
        
        # If we're getting all databases, find the connected one or use the first one
        if not database_alias and isinstance(database_config, list):
            # Look for a connected database first
            connected_db = next((db for db in database_config if db.get("connected", False)), None)
            if connected_db:
                database_config = connected_db
            else:
                # Use the first database if no connected one found
                database_config = database_config[0] if database_config else None
                
        if not database_config or "vector_stores" not in database_config:
            logger.warning("No vector stores found in database configuration")
            return vector_store_alias
            
        # Look for the vector store with the matching alias
        vector_stores = database_config.get("vector_stores", [])
        for vs in vector_stores:
            if vs.get("alias") == vector_store_alias:
                actual_name = vs.get("vector_store")
                if actual_name:
                    logger.info("Resolved vector store alias '%s' to table name '%s'", vector_store_alias, actual_name)
                    return actual_name
                    
        logger.warning("Vector store alias '%s' not found, using alias as table name", vector_store_alias)
        return vector_store_alias
    except Exception as e:
        logger.error("Failed to resolve vector store alias: %s", str(e))
        return vector_store_alias if vector_store_alias else (vector_store if vector_store else "VECTOR_STORE")


@mcp.tool()
def oraclevs_retriever(
    question: str,
    search_type: str = "Similarity",
    top_k: int = 4,
    score_threshold: float = 0.5,
    fetch_k: int = 20,
    lambda_mult: float = 0.5,
    distance_metric: str = "COSINE",
    vector_store: str = "",
    vector_store_alias: str = "",
    server_url: str = "",
    api_key: str = "",
    database_alias: str = ""
) -> Dict[str, Any]:
    """
    Search and return information using Vector Search
    
    Args:
        question: The question to search for
        search_type: Type of search (Similarity, Similarity Score Threshold, Maximal Marginal Relevance)
        top_k: Number of results to return
        score_threshold: Minimum score threshold for results (for Similarity Score Threshold)
        fetch_k: Number of documents to fetch for MMR
        lambda_mult: Diversity parameter for MMR
        distance_metric: Distance metric for vector search
        vector_store: Name of the vector store table (direct table name)
        vector_store_alias: Alias of the vector store (will be resolved to table name)
        server_url: Server URL for configuration API access
        api_key: API key for server authentication
        database_alias: Alias of the database to use
        
    Returns:
        Dictionary containing documents and the search question
    """
    logger.info("Initializing OracleVS Tool via MCP")
    logger.info("Question: %s", question)
    logger.info("Search Type: %s", search_type)
    logger.info("Top K: %s", top_k)
    
    # Check if required modules are available
    if not all([PromptTemplate, Document, OracleVS, oracledb]):
        logger.warning("Required modules not available for OracleVS tool")
        return {
            "documents": [],
            "search_question": question,
            "error": "Required modules not available"
        }
    
    try:
        # Get database connection using the new method with parameters
        db_conn = None
        
        # Try to get connection from provided parameters first
        if server_url and api_key:
            db_conn = get_database_connection_from_config(server_url, api_key, database_alias)
        
        # Fallback to environment variables
        if not db_conn:
            db_conn = get_database_connection()
            
        if not db_conn:
            raise Exception("No database connection available")
        
        # For embedding, use Ollama embeddings with nomic-embed-text
        # Get Ollama configuration from environment or use defaults
        ollama_base_url = os.getenv("ON_PREM_OLLAMA_URL", "http://localhost:11434")
        
        # Initialize embeddings with proper error handling
        embeddings = None
        if OllamaEmbeddings is not None:
            try:
                embeddings = OllamaEmbeddings(
                    model="nomic-embed-text",
                    base_url=ollama_base_url
                )
                logger.info("Using Ollama embeddings with nomic-embed-text at %s", ollama_base_url)
            except Exception as ollama_ex:
                logger.warning("Failed to initialize Ollama embeddings: %s", str(ollama_ex))
                embeddings = None
        
        # Fallback chain: Ollama -> HuggingFace -> Mock
        if embeddings is None:
            try:
                from langchain_community.embeddings import HuggingFaceEmbeddings
                embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
                logger.info("Using HuggingFace embeddings as fallback")
            except (ImportError, Exception):
                logger.warning("HuggingFace embeddings not available")
                embeddings = None
        
        if embeddings is None:
            # Final fallback to mock embeddings
            logger.warning("Using mock embeddings as final fallback")
            class MockEmbeddings:
                def embed_query(self, text):
                    return [0.1] * 768  # Mock embedding vector
                def embed_documents(self, texts):
                    return [[0.1] * 768 for _ in texts]
            embeddings = MockEmbeddings()
        
        # Resolve vector store name using the new method
        vector_store_name = resolve_vector_store_name(
            vector_store_alias=vector_store_alias,
            vector_store=vector_store,
            server_url=server_url,
            api_key=api_key,
            database_alias=database_alias
        )
        
        logger.info("Initializing Vector Store: %s", vector_store_name)
        
        # Initialize OracleVS
        try:
            vectorstore = OracleVS(db_conn, embeddings, vector_store_name, distance_metric)
        except Exception as ex:
            logger.exception("Failed to initialize the Vector Store")
            return {
                "documents": [],
                "search_question": question,
                "error": f"Failed to initialize vector store: {str(ex)}"
            }

        # Perform search based on search type
        try:
            search_kwargs = {"k": int(top_k)}

            if search_type == "Similarity":
                retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs=search_kwargs)
            elif search_type == "Similarity Score Threshold":
                search_kwargs["score_threshold"] = float(score_threshold)
                retriever = vectorstore.as_retriever(
                    search_type="similarity_score_threshold", search_kwargs=search_kwargs
                )
            elif search_type == "Maximal Marginal Relevance":
                search_kwargs.update(
                    {
                        "fetch_k": int(fetch_k),
                        "lambda_mult": float(lambda_mult),
                    }
                )
                retriever = vectorstore.as_retriever(search_type="mmr", search_kwargs=search_kwargs)
            else:
                raise ValueError(f"Unsupported search_type: {search_type}")
            
            logger.info("Invoking retriever on: %s", question)
            documents = retriever.invoke(question)
        except Exception as ex:
            logger.exception("Failed to perform Oracle Vector Store retrieval")
            return {
                "documents": [],
                "search_question": question,
                "error": f"Failed to perform search: {str(ex)}"
            }
        
        # Convert documents to dictionary format
        documents_dict = [vars(doc) for doc in documents]
        logger.info("Found Documents: %i", len(documents_dict))
        
        result = {
            "documents": documents_dict,
            "search_question": question
        }
        
        return result
        
    except Exception as ex:
        logger.exception("Error in OracleVS tool")
        return {
            "documents": [],
            "search_question": question,
            "error": str(ex)
        }


if __name__ == "__main__":
    # Run the MCP server
    print("OracleVS MCP Server starting...")
    mcp.run(transport='stdio')
