# Spring AI template

## How to run:
Prepare two configurations in the `Oracle ai optimizer and toolkit`, based on vector stores created using this kind of configuration:

* OLLAMA: 
  * Embbeding model: mxbai-embed-large
  * Chunk size: 512
  * overlap: 103
  * distance: COSINE

* OPENAI: 
  * Embdeding model: text-embedding-3-small
  * Chunk size: 8191
  * overlap: 1639
  * distance: COSINE

and loading a document like [Oracle® Database
Get Started with Java Development](https://docs.oracle.com/en/database/oracle/oracle-database/23/tdpjd/get-started-java-development.pdf).

Download one of them through the `Download SpringAI` button. Unzip the content and set the executable permission on the `start.sh`  with `chmod 755 ./start.sh`.

Edit `start.sh` to change the DB_PASSWORD or any other referece/credential changed by the dev env, as in this example:
```
export SPRING_AI_OPENAI_API_KEY=$OPENAI_API_KEY
export DB_DSN="jdbc:oracle:thin:@localhost:1521/FREEPDB1"
export DB_USERNAME=<DB_USER_NAME>
export DB_PASSWORD=<DB_PASSWORD>
export DISTANCE_TYPE=COSINE
export OPENAI_CHAT_MODEL=gpt-4o-mini
export OPENAI_EMBEDDING_MODEL=text-embedding-3-small
export OLLAMA_CHAT_MODEL="llama3.1"
export OLLAMA_EMBEDDING_MODEL=mxbai-embed-large
export OLLAMA_BASE_URL="http://<OLLAMA_SERVER>:11434"
export SYS_INSTR=" You are an assistant for question-answering tasks. Use the retrieved Documents and history to answer the question as accurately and comprehensively as possible. Keep your answer grounded in the facts of the Documents, be concise, and reference the Documents where possible. If you don't know the answer, just say that you are sorry as you don't haven't enough information. "
export TOP_K=4
export VECTOR_STORE=TEXT_EMBEDDING_3_SMALL_8191_1639_COSINE
export PROVIDER=openai
mvn spring-boot:run -P openai
```

Drop the table `<VECTOR_STORE>_SPRINGAI`, if exists, running in sql:

```
DROP TABLE <VECTOR_STORE>_SPRINGAI CASCADE CONSTRAINTS;
COMMIT;
```

Start with:

```
./start.sh
```

This project contains a web service that will accept HTTP requests at

* `http://localhost:9090/v1/chat/completions`: to use RAG via OpenAI REST API [**POST**]
* `http://localhost:9090/v1/models`: returns models behind the RAG via OpenAI REST API [**GET**]
* `http://localhost:9090/v1/service/llm` : to chat straight with the LLM used [**GET**]
* `http://localhost:9090/v1/service/search/`: to search for similar chunk documents to the message provided [**GET**]
* `http://localhost:9090/v1/service/store-chunks/`: from a list of chunks provided, it generates vector embeddings and store them in the vector store. [**POST**]




### Completions
RAG call example with `openai` build profile with no-stream: 

```
curl -N http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "server",
    "messages": [{"role": "user", "content": "Can I use any kind of development environment to run the example?"}],
    "stream": false
  }'
```

the response with Vector Search:

```
{
  "choices": [
    {
      "message": {
        "content": "Yes, you can use any kind of development environment to run the example, but for ease of development, the guide specifically mentions using an integrated development environment (IDE). It uses IntelliJ IDEA Community version as an example for creating and updating the files for the application (see Document 96EECD7484D3B56C). However, you are not limited to this IDE and can choose any development environment that suits your needs."
      }
    }
  ]
}
```
with stream output:
```
curl -N http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "server",
    "messages": [{"role": "user", "content": "Can I use any kind of development environment to run the example?"}],
    "stream": true
  }'
```
or the request without Vector Search:
```
curl --get --data-urlencode 'message=Can I use any kind of development environment to run the example?' localhost:9090/v1/service/llm | jq .
```

response not grounded:

```
{
  "completion": "Yes, you can use various development environments to run examples, depending on the programming language and the specific example you are working with. Here are some common options:\n\n1. **Integrated Development Environments (IDEs)**:\n   - **Visual Studio Code**: A versatile code editor that supports many languages through extensions.\n   - **PyCharm**: Great for Python development.\n   - **Eclipse**: Commonly used for Java development.\n   - **IntelliJ IDEA**: Another popular choice for Java and other languages.\n   - **Xcode**: For macOS and iOS development (Swift, Objective-C).\n\n2. **Text Editors**:\n   - **Sublime Text**: A lightweight text editor with support for many languages.\n   - **Atom**: A hackable text editor for the 21st century.\n   - **Notepad++**: A free source code editor for Windows.\n\n3. **Command Line Interfaces**:\n   - You can run"
}
```

### Add chunks
Store additional text chunks in the vector store: 

```
curl -X POST http://localhost:9090/v1/service/store-chunks \
  -H "Content-Type: application/json" \
  -d '["First chunk of text.", "Second chunk.", "Another example."]'
```

### Get model name
Return the name of model used. It's useful to integrate ChatGUIs that require the model list before proceed.

```
curl http://localhost:9090/v1/models
```

## MCP RagTool
The completion service is also available as an MCP server based on the SSE transport protocol.
To test it:

* Start as usual the microservice: 
```shell
./start.sh
```

* Start the MCP inspector:
```shell
export DANGEROUSLY_OMIT_AUTH=true
npx @modelcontextprotocol/inspector  
```

* With a web browser open: http://127.0.0.1:6274

* Configure:
  * Transport Type: SSE
  * URL: http://127.0.0.1:9090/sse
  * set Request Timeout to: 200000

* Test a call to `getRag` Tool.


## Oracle Backend for Microservices and AI
* Add in `application-obaas.yml` the **OPENAI_API_KEY**, if the deployement is based on the OpenAI LLM services:
```
   openai:
      base-url: 
      api-key: <OPENAI_API_KEY>
```

* Build, depending the provider `<ollama|openai>`:

```
mvn clean package -DskipTests -P <ollama|openai> -Dspring-boot.run.profiles=obaas
```

* Set, one time only, the ollama server running in the **Oracle Backend for Microservices and AI**. Prepare an `ollama-values.yaml`:
```
ollama:
  gpu:
    enabled: true
    type: 'nvidia'
    number: 1
  models:
    - llama3.1
    - llama3.2
    - mxbai-embed-large
    - nomic-embed-text
nodeSelector:
  node.kubernetes.io/instance-type: VM.GPU.A10.1
```

* execute:
```
kubectl create ns ollama
helm install ollama ollama-helm/ollama --namespace ollama  --values ollama-values.yaml
```
* check:
```
kubectl -n ollama exec svc/ollama -- ollama ls
```
it should be:
```
NAME                        ID              SIZE      MODIFIED      
nomic-embed-text:latest     0a109f422b47    274 MB    3 minutes ago    
mxbai-embed-large:latest    468836162de7    669 MB    3 minutes ago    
llama3.1:latest             a80c4f17acd5    2.0 GB    3 minutes ago 
```
* test a single LLM:
```
kubectl -n ollama exec svc/ollama -- ollama run "llama3.1" "what is spring boot?"
```

* **NOTE**: The Microservices will access to the ADB23ai on which the vector store table should be created as done in the local desktop example shown before. To access the ai-explorer running on **Oracle Backend for Microservices and AI** and create the same configuration, let's do:
  * tunnel:
  ```
  kubectl -n ai-explorer port-forward svc/ai-explorer 8181:8501 
  ```
  * on localhost:
  ```
  http://localhost:8181/ai-sandbox
  ```

* Deploy with `oractl` on a new schema `vector`:
  * tunnel:
  ```
    kubectl -n obaas-admin port-forward svc/obaas-admin 8080:8080
  ```
  
  * oractl:
  ```
  create --app-name vector_search
  bind --app-name vector_search --service-name myspringai --username vector
  ```


* the `bind` will create the new user, if not exists, but to have the `<VECTOR_STORE>_SPRINGAI` table compatible with SpringAI Oracle vector store adapter, the microservices need to access to the vector store table created by the ai-explorer with user ADMIN on ADB:

```
GRANT SELECT ON ADMIN.<VECTOR_STORE> TO vector;
```
* then deploy:
```
deploy --app-name vector_search --service-name myspringai --artifact-path <ProjectDir>/target/myspringai-0.0.1-SNAPSHOT.jar --image-version 0.0.1 --java-version ghcr.io/oracle/graalvm-native-image-obaas:21 --service-profile obaas
```
* test:
```
kubectl -n vector_search port-forward svc/myspringai 9090:8080
```
* from shell:
```
curl -N http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "server",
    "messages": [{"role": "user", "content": "Can I use any kind of development environment to run the example?"}],
    "stream": false
  }'
```
it should return:
```
{
  "choices": [
    {
      "message": {
        "content": "Based on the provided documents, it seems that a specific development environment (IDE) is recommended for running the example.\n\nIn document \"67D5C08DF7F7480F\", it states: \"This guide uses IntelliJ Idea community version to create and update the files for this application.\" (page 17)\n\nHowever, there is no information in the provided documents that explicitly prohibits using other development environments. In fact, one of the articles mentions \"Application. Use these instructions as a reference.\" without specifying any particular IDE.\n\nTherefore, while it appears that IntelliJ Idea community version is recommended, I couldn't find any definitive statement ruling out the use of other development environments entirely.\n\nIf you'd like to run the example with a different environment, it might be worth investigating further or consulting additional resources. Sorry if this answer isn't more conclusive!"
      }
    }
  ]
}
```


## Prerequisites

Before using the AI commands, make sure you have a developer token from OpenAI.

Create an account at [OpenAI Signup](https://platform.openai.com/signup) and generate the token at [API Keys](https://platform.openai.com/account/api-keys).

The Spring AI project defines a configuration property named `spring.ai.openai.api-key` that you should set to the value of the `API Key` obtained from `openai.com`.

Exporting an environment variable is one way to set that configuration property.
```shell
export SPRING_AI_OPENAI_API_KEY=<INSERT KEY HERE>
```

Setting the API key is all you need to run the application.
However, you can find more information on setting started in the [Spring AI reference documentation section on OpenAI Chat](https://docs.spring.io/spring-ai/reference/api/clients/openai-chat.html).





