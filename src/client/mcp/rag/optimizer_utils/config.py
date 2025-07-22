from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_ollama import OllamaLLM

from langchain_community.vectorstores.utils import DistanceStrategy

from langchain_community.vectorstores import oraclevs
from langchain_community.vectorstores.oraclevs import OracleVS
import oracledb


def get_llm(data):
    llm={}
    llm_config = data["ll_model_config"][data["client_settings"]["ll_model"]["model"]]
    api=llm_config["api"]
    url=llm_config["url"]
    api_key=llm_config["api_key"]
    model=data["client_settings"]["ll_model"]["model"]
    print(f"CHAT_MODEL: {model} {api} {url} {api_key}")
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
    model=data["client_settings"]["rag"]["model"]
    api=data["embed_model_config"][model]["api"]
    url=data["embed_model_config"][model]["url"]
    api_key=data["embed_model_config"][model]["api_key"]
    print(f"EMBEDDINGS: {model} {api} {url} {api_key}")
    embeddings = {}
    if  api=="OllamaEmbeddings":
         embeddings=OllamaEmbeddings(
            model=model,
            base_url=url)
    elif api == "OpenAIEmbeddings":
         print("BEFORE create embbedding")
         embeddings = OpenAIEmbeddings(
            model=model,
            api_key=api_key
         )   
         print("AFTER create emebdding")
    return embeddings

def get_vectorstore(data,embeddings):
    
    config=data["database_config"][data["client_settings"]["rag"]["database"]]
   
    conn23c = oracledb.connect(user=config["user"], 
                               password=config["password"], dsn=config["dsn"])
 
    print("DB Connection successful!")
    metric=data["client_settings"]["rag"]["distance_metric"]
    
    dist_strategy=DistanceStrategy.COSINE
    if metric=="COSINE":
        dist_strategy=DistanceStrategy.COSINE
    elif metric == "EUCLIDEAN":
        dist_strategy=DistanceStrategy.EUCLIDEAN
   
    print("1")
    a=data["client_settings"]["rag"]["vector_store"]
    print(f"{a}")
    print(f"BEFORE KNOWLEDGE BASE")
    print(embeddings)
    knowledge_base = OracleVS(conn23c, embeddings, data["client_settings"]["rag"]["vector_store"], dist_strategy)
    return knowledge_base