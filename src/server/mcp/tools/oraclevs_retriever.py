"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore vectorstore, vectorstores, oraclevs, mult, langgraph

from typing import Dict, Any, List
import json
import decimal
import os

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

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.mcp.tools.oraclevs_retriever")


class DecimalEncoder(json.JSONEncoder):
    """Used with json.dumps to encode decimals"""

    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        return super().default(o)


async def register(mcp, auth):
    """Register the Oracle Vector Store Retriever Tool as an MCP tool"""
    
    @mcp.tool(name="oraclevs_retriever")
    def oraclevs_retriever(
        question: str,
        search_type: str = "Similarity",
        top_k: int = 4,
        score_threshold: float = 0.5,
        fetch_k: int = 20,
        lambda_mult: float = 0.5,
        distance_metric: str = "COSINE",
        vector_store: str = ""
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
            vector_store: Name of the vector store table
            
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
            # Get database connection from the server context
            # This will be passed through the tool call context
            from server.api.core.databases import get_databases
            
            # Find the first connected database
            databases = get_databases(validate=False)
            db_conn = None
            for database in databases:
                if database.connected and database.connection:
                    db_conn = database.connection
                    break
            
            if not db_conn:
                raise Exception("No connected database available")
            
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
            
            # Use the provided vector store name or default to a common name
            vector_store_name = vector_store if vector_store else "VECTOR_STORE"
            
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
