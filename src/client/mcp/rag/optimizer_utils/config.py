from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_ollama import OllamaLLM

from langchain_community.vectorstores.utils import DistanceStrategy

from langchain_community.vectorstores import oraclevs
from langchain_community.vectorstores.oraclevs import OracleVS
import oracledb

import logging
logging.basicConfig(level=logging.INFO)

def get_llm(data):
    logging.info("llm data:")
    logging.info(data["user_settings"]["ll_model"]["model"])
    llm={}
    llm_config = data["ll_model_config"][data["user_settings"]["ll_model"]["model"]]
    api=llm_config["api"]
    url=llm_config["url"]
    api_key=llm_config["api_key"]
    model=data["user_settings"]["ll_model"]["model"]
    logging.info(f"CHAT_MODEL: {model} {api} {url} {api_key}")
    if api == "ChatOllama":
        # Initialize the LLM
        llm = OllamaLLM(
            model=model,
            base_url=url
        )
    elif api == "OpenAI":
        
        llm=llm = ChatOpenAI(
            model=model,
            api_key=api_key
        )
    return llm

def get_embeddings(data):
    embeddings={}
    model=data["user_settings"]["vector_search"]["model"]
    api=data["embed_model_config"][model]["api"]
    url=data["embed_model_config"][model]["url"]
    api_key=data["embed_model_config"][model]["api_key"]
    logging.info(f"EMBEDDINGS: {model} {api} {url} {api_key}")
    embeddings = {}
    if  api=="OllamaEmbeddings":
         embeddings=OllamaEmbeddings(
            model=model,
            base_url=url)
    elif api == "OpenAIEmbeddings":
         logging.info("BEFORE create embbedding")
         embeddings = OpenAIEmbeddings(
            model=model,
            api_key=api_key
         )   
         logging.info("AFTER create emebdding")
    return embeddings

def get_vectorstore(data,embeddings):
    
    config=data["database_config"][data["user_settings"]["database"]["alias"]]
    logging.info(config)

    conn23c = oracledb.connect(user=config["user"], 
                               password=config["password"], dsn=config["dsn"])
 
    logging.info("DB Connection successful!")
    metric=data["user_settings"]["vector_search"]["distance_metric"]
    
    dist_strategy=DistanceStrategy.COSINE
    if metric=="COSINE":
        dist_strategy=DistanceStrategy.COSINE
    elif metric == "EUCLIDEAN":
        dist_strategy=DistanceStrategy.EUCLIDEAN
   
    a=data["user_settings"]["vector_search"]["vector_store"]
    logging.info(f"{a}")
    logging.info(f"BEFORE KNOWLEDGE BASE")
    logging.info(embeddings)
    knowledge_base = OracleVS(conn23c, embeddings, data["user_settings"]["vector_search"]["vector_store"], dist_strategy)
    return knowledge_base