"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
from typing import List
from mcp.server.fastmcp import FastMCP
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

# Initialize FastMCP server
#mcp = FastMCP("research", port=8001) #Remote client
mcp = FastMCP("rag") #Local


@mcp.tool()
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


if __name__ == "__main__":
    rag_tool_desc=[
    f"""
    Use this tool to answer any question that may benefit from up-to-date or domain-specific information.
    
    Args:
        question: the question for which are you looking for an answer
        
    Returns:
        JSON string with answer
    """
    ]


    # Initialize and run the server
    # Load JSON file: set your absolute path
    file_path = "/Users/cdebari/Documents/GitHub/ai-optimizer-mcp-export/src/client/mcp/rag/optimizer_settings.json"
    with open(file_path, "r") as file:
        #rag_tool.__doc__=rag_tool_desc[0]
        data = json.load(file)
        #mcp.run(transport='stdio')
        mcp.run(transport='sse')