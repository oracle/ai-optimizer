"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging

import oracledb
from langchain_community.vectorstores import oraclevs  # pylint: disable=unused-import
from langchain_community.vectorstores.oraclevs import OracleVS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_huggingface import HuggingFaceEmbeddings  # pylint: disable=import-error,unused-import
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")


def get_llm(data):
    """
    Get LLM instance based on configuration data.

    Args:
        data: Configuration dictionary containing model settings

    Returns:
        Configured LLM instance
    """
    logger.info("llm data:")
    logger.info(data["client_settings"]["ll_model"]["model"])
    model_full = data["client_settings"]["ll_model"]["model"]
    _, prefix, model = model_full.partition("/")
    llm = {}
    models_by_id = {m["id"]: m for m in data.get("model_configs", [])}
    llm_config = models_by_id.get(model)
    logger.info(llm_config)
    provider = llm_config["provider"]
    url = llm_config["api_base"]
    api_key = llm_config["api_key"]

    logger.info("CHAT_MODEL: %s %s %s %s", model, provider, url, api_key)
    if provider == "ollama":
        # Initialize the LLM
        llm = OllamaLLM(model=model, base_url=url)
        logger.info("Ollama LLM created")
    elif provider == "openai":
        llm = ChatOpenAI(model=model, api_key=api_key)
        logger.info("OpenAI LLM created")
    elif provider == "hosted_vllm":
        llm = ChatOpenAI(model=model, api_key=api_key, base_url=url)
        logger.info("hosted_vllm compatible LLM created")
    return llm


def get_embeddings(data):
    """
    Get embeddings instance based on configuration data.

    Args:
        data: Configuration dictionary containing embedding model settings

    Returns:
        Configured embeddings instance
    """
    embeddings = {}
    logger.info("getting embeddings..")
    model_full = data["client_settings"]["vector_search"]["model"]
    _, prefix, model = model_full.partition("/")
    logger.info("embedding model: %s", model)
    models_by_id = {m["id"]: m for m in data.get("model_configs", [])}
    model_params = models_by_id.get(model)
    provider = model_params["provider"]
    url = model_params["api_base"]
    api_key = model_params["api_key"]

    logger.info("Embeddings Model: %s %s %s %s", model, provider, url, api_key)
    embeddings = {}
    if provider == "ollama":
        embeddings = OllamaEmbeddings(model=model, base_url=url)
        logger.info("Ollama Embeddings connection successful")
    elif provider == "openai":
        embeddings = OpenAIEmbeddings(model=model, api_key=api_key)
        logger.info("OpenAI embeddings connection successful")
    elif provider == "hosted_vllm":
        embeddings = OpenAIEmbeddings(model=model, api_key=api_key, base_url=url, check_embedding_ctx_length=False)
        logger.info("hosted_vllm compatible embeddings connection successful")

    return embeddings


def get_vectorstore(data, embeddings):
    """
    Get vector store instance based on configuration data.

    Args:
        data: Configuration dictionary containing database and vector search settings
        embeddings: Embeddings instance to use for the vector store

    Returns:
        Configured OracleVS vector store instance
    """
    db_alias = data["client_settings"]["database"]["alias"]

    db_by_name = {m["name"]: m for m in data.get("database_configs", [])}
    db_config = db_by_name.get(db_alias)

    table_alias = data["client_settings"]["vector_search"]["alias"]
    model = data["client_settings"]["vector_search"]["model"]
    chunk_size = str(data["client_settings"]["vector_search"]["chunk_size"])
    chunk_overlap = str(data["client_settings"]["vector_search"]["chunk_overlap"])
    distance_metric = data["client_settings"]["vector_search"]["distance_metric"]
    index_type = data["client_settings"]["vector_search"]["index_type"]

    db_table = (
        (table_alias + "_" + model + "_" + chunk_size + "_" + chunk_overlap + "_" + distance_metric + "_" + index_type)
        .upper()
        .replace("-", "_")
        .replace("/", "_")
    )
    logger.info("db_table:%s", db_table)

    user = db_config["user"]
    password = db_config["password"]
    dsn = db_config["dsn"]

    user = db_config["user"]
    password = db_config["password"]
    dsn = db_config["dsn"]

    # ADB connection with wallet

    wallet_pwd = db_config["wallet_password"]
    wallet_location = db_config["wallet_location"]

    logger.info("%s: %s - %s", db_table, user, dsn)

    if wallet_pwd and wallet_location:
        logger.info("ADB connection starting..")
        conn23c = oracledb.connect(
            user=user, password=password, dsn=dsn, wallet_location=wallet_location, wallet_password=wallet_pwd
        )
    else:
        conn23c = oracledb.connect(user=user, password=password, dsn=dsn)

    logger.info("DB Connection successful!")
    metric = data["client_settings"]["vector_search"]["distance_metric"]

    dist_strategy = DistanceStrategy.COSINE
    if metric == "COSINE":
        dist_strategy = DistanceStrategy.COSINE
    elif metric == "EUCLIDEAN":
        dist_strategy = DistanceStrategy.EUCLIDEAN

    logger.info(embeddings)
    knowledge_base = OracleVS(
        client=conn23c, table_name=db_table, embedding_function=embeddings, distance_strategy=dist_strategy
    )

    return knowledge_base
