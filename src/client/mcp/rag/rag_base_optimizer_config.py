from typing import List
#from mcp.server.fastmcp import FastMCP
import os
from dotenv import load_dotenv
#from sentence_transformers import CrossEncoder
#from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_community.vectorstores import oraclevs
from langchain_community.vectorstores.oraclevs import OracleVS
from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_community.chat_models.oci_generative_ai import ChatOCIGenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import oracledb
import json

from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_ollama import OllamaLLM

from tqdm import tqdm, trange

print("Successfully imported libraries and modules")

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

def rag_tool(question: str) -> str:
    """
    Use this tool to answer any question that may benefit from up-to-date or domain-specific information.
    
    Args:
        question: the question for which are you looking for an answer
        
    Returns:
        JSON string with answer
    """

    try: 
        
        embeddings = get_embeddings(data)
        
        print("Embedding successful!")
        knowledge_base = get_vectorstore(data,embeddings)
        print("DB Connection successful!")
    
        print("knowledge_base successful!")
        user_question = question
        #result_chunks=knowledge_base.similarity_search(user_question, 5)
        
        for d in data["prompts_config"]:
            if d["name"]==data["user_settings"]["prompts"]["sys"]:
             
                rag_prompt=d["prompt"]
       
        template = """DOCUMENTS: {context} \n"""+rag_prompt+"""\nQuestion: {question} """
        #template = """Answer the question based only on the following context:{context} Question: {question} """
        print(template)
        prompt = PromptTemplate.from_template(template)
        print("before retriever")
        print(data["user_settings"]["rag"]["top_k"])
        retriever = knowledge_base.as_retriever(search_kwargs={"k": data["user_settings"]["rag"]["top_k"]})
        print("after retriever")
        

        # Initialize the LLM
        llm = get_llm(data)

        chain = (
            {"context": retriever, "question": RunnablePassthrough()}
                | prompt
                | llm
                | StrOutputParser()
        )
        print("pre-chain successful!")
        answer = chain.invoke(user_question)

        #print(f"Results provided for question: {question}")
        #print(f"{answer}")
    except Exception as e:
        print(e)
        print("Connection failed!")
        answer=""

    return f"{answer}"

def get_llm(data):
    llm={}
    llm_config = data["ll_model_config"][data["user_settings"]["ll_model"]["model"]]
    api=llm_config["api"]
    url=llm_config["url"]
    api_key=llm_config["api_key"]
    model=data["user_settings"]["ll_model"]["model"]
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
    model=data["user_settings"]["rag"]["model"]
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
    
    config=data["database_config"][data["user_settings"]["rag"]["database"]]
   
    conn23c = oracledb.connect(user=config["user"], 
                               password=config["password"], dsn=config["dsn"])
 
    print("DB Connection successful!")
    metric=data["user_settings"]["rag"]["distance_metric"]
    
    dist_strategy=DistanceStrategy.COSINE
    if metric=="COSINE":
        dist_strategy=DistanceStrategy.COSINE
    elif metric == "EUCLIDEAN":
        dist_strategy=DistanceStrategy.EUCLIDEAN
   
    print("1")
    a=data["user_settings"]["rag"]["vector_store"]
    print(f"{a}")
    print(f"BEFORE KNOWLEDGE BASE")
    print(embeddings)
    knowledge_base = OracleVS(conn23c, embeddings, data["user_settings"]["rag"]["vector_store"], dist_strategy)
    return knowledge_base


def get_conf(data):

    # Explore top-level keys
    print("Top-level keys:", list(data.keys()))

    # Example: Access user_settings
    user_settings = data.get("user_settings", {})
    print("\nUser Settings Keys:", list(user_settings.keys()))

    # Drill down to ll_model
    ll_model = user_settings.get("ll_model", {})
    print("\nLL Model Settings:")
    for key, value in ll_model.items():
        print(f"  {key}: {value}")

    llm_config = data["ll_model_config"][user_settings["ll_model"]["model"]]
    for key, value in llm_config.items():
        print(f"  {key}: {value}")
  
    #llmodel type to import the right dir:
    llm_config = data["ll_model_config"][user_settings["ll_model"]["model"]]
    api=llm_config["api"]
    url=llm_config["url"]
    api_key=llm_config["api_key"]
    


if __name__ == "__main__":
    # Initialize and run the server
    # Load JSON file
    file_path = os.path.join(os.getcwd(), "optimizer_settings.json")
    #file="/Users/cdebari/Documents/GitHub/mcp/rag/optimizer_settings_openai.json"
    print(file_path)
    with open(file_path, "r") as file:
        data = json.load(file)
        print(get_embeddings(data))
        question="Which kind of IDE should be used in this demo?"
        print(f"Question: {question}")
        print(f"Answer: {rag_tool(question)}")