+++
title = 'Spring AI'
weight = 10
+++

After having downloaded and unzipped the SpringAI file from the [Settings](../client/configuration/settings) screen, you can open and set the latest two things in the code to be executed. For the detailed description, please refer to the **README.md** file included

### Prerequisites
Before using a microservice that exploit OpenAI API, make sure you have a developer token from OpenAI. To do this, create an account at [OpenAI](https://platform.openai.com/signup) and generate the token at [API Keys](https://platform.openai.com/account/api-keys).


The Spring AI project defines a configuration property named: `spring.ai.openai.api-key`, that you should set to the value of the **API Key** got from `openai.com`.

Exporting an environment variable is one way to set that configuration property.

```bash
export SPRING_AI_OPENAI_API_KEY=<INSERT KEY HERE>
```

Setting the API key is all you need to run the application. However, you can find more information on setting started in the [Spring AI reference documentation section on OpenAI Chat](https://docs.spring.io/spring-ai/reference/api/clients/openai-chat.html).

### Run the microservice standalone

You have simply to:

* change the permissions to the `start.sh` file to be executed with: 

```bash
chmod 755 ./start.sh
```

* Edit `start.sh` to change the DB_PASSWORD or any other reference/credentials changed by the dev env, as in this example:
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
export CONTEXT_INSTR=" You are an assistant for question-answering tasks. Use the retrieved Documents and history to answer the question as accurately and comprehensively as possible. Keep your answer grounded in the facts of the Documents, be concise, and reference the Documents where possible. If you don't know the answer, just say that you are sorry as you don't haven't enough information. "
export TOP_K=4
export VECTOR_STORE=TEXT_EMBEDDING_3_SMALL_8191_1639_COSINE
export PROVIDER=openai
mvn spring-boot:run -P openai
```

* The `<VECTOR_STORE>` created in the Oracle AI Optimizer and Toolkit will be automatically converted in a `<VECTOR_STORE>_SPRINGAI` table, and it will store the same data. If already exists it will be used without modification.
If you want to start from scratch, drop the table `<VECTOR_STORE>_SPRINGAI`, running in sql:

```sql
DROP TABLE <VECTOR_STORE>_SPRINGAI CASCADE CONSTRAINTS;
COMMIT;
```

* This microservice will expose the following REST endpoints:

  * `http://localhost:9090/v1/chat/completions`: to use RAG via OpenAI REST API 
  * `http://localhost:9090/v1/models`: return models behind the RAG via OpenAI REST API 
  * `http://localhost:9090/v1/service/llm` : to chat straight with the LLM used
  * `http://localhost:9090/v1/service/search/`: to search for document similar to the message provided
  * `http://localhost:9090/v1/service/store-chunks/`: to embedd and store a list of text chunks in the vectorstore

### Completions endpoint usage examples
A RAG call example with `openai` build profile, with no-stream: 

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

the response with RAG:

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

If you want to ask for a stream output, the request it should be:
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

Or a request without RAG:
```
curl --get --data-urlencode 'message=Can I use any kind of development environment to run the example?' localhost:9090/v1/service/llm | jq .
```

In this case, the response not grounded it could be:

```
{
  "completion": "Yes, you can use various development environments to run examples, depending on the programming language and the specific example you are working with. Here are some common options:\n\n1. **Integrated Development Environments (IDEs)**:\n   - **Visual Studio Code**: A versatile code editor that supports many languages through extensions.\n   - **PyCharm**: Great for Python development.\n   - **Eclipse**: Commonly used for Java development.\n   - **IntelliJ IDEA**: Another popular choice for Java and other languages.\n   - **Xcode**: For macOS and iOS development (Swift, Objective-C).\n\n2. **Text Editors**:\n   - **Sublime Text**: A lightweight text editor with support for many languages.\n   - **Atom**: A hackable text editor for the 21st century.\n   - **Notepad++**: A free source code editor for Windows.\n\n3. **Command Line Interfaces**:\n   - You can run"
}
```

### Add new text chunks in the vector store example
Store additional text chunks in the vector store, along their vector embeddings: 

```
curl -X POST http://localhost:9090/v1/service/store-chunks \
  -H "Content-Type: application/json" \
  -d '["First chunk of text.", "Second chunk.", "Another example."]'
```

response will be a list of vector embeddings created:

```
[
  [
    -0.014500250108540058,
    -0.03604526072740555,
    0.035963304340839386,
    0.010181647725403309,
    -0.01610776223242283,
    -0.021091962233185768,
    0.03924199938774109,
    ..
  ],
  [
    ..
  ]  
]
```

### Get model name
Return the name of model used. It's useful to integrate ChatGUIs that require the model list before proceed.

```
curl http://localhost:9090/v1/models
```

## MCP RagTool
The completion service is also available as an MCP server based on the **SSE** transport protocol.
To test it:

* Start as usual the microservice: 
```shell
./start.sh
```

* Start the **MCP inspector**:
```shell
export DANGEROUSLY_OMIT_AUTH=true
npx @modelcontextprotocol/inspector  
```

* With a web browser open: http://127.0.0.1:6274

* Configure:
  * Transport Type: SSE
  * URL: http://localhost:9090/sse
  * set Request Timeout to: **200000**

* Test a call to `getRag` Tool.


### Run in the Oracle Backend for Microservices and AI

Thanks to the GPU node pool support of the latest release, it is possible to deploy the Spring Boot microservice in it, leveraging private LLMs too. These are the steps to be followed:

* Add in `application-obaas.yml` the **OPENAI_API_KEY**, if the deployment is based on the OpenAI LLM services:

```yaml
openai:
      base-url: 
      api-key: <OPENAI_API_KEY>
```

* Build, depending the provider `<ollama|openai>`:

```bash
mvn clean package -DskipTests -P <ollama|openai> -Dspring-boot.run.profiles=obaas
```

* let’s do the setup, one time only, for the **Ollama** server running in the **Oracle Backend for Microservices and AI**. Prepare an `ollama-values.yaml` to include the LLMs used in your chatbot configuration. Example:

```yaml
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

* execute the helm chart to deploy in the kubernetes cluster:

```bash
kubectl create ns ollama
helm install ollama ollama-helm/ollama --namespace ollama  --values ollama-values.yaml
```

* check if it has been correctly installed in this way:

```bash
kubectl -n ollama exec svc/ollama -- ollama ls
```

it should be:


```bash
NAME                        ID              SIZE      MODIFIED      
nomic-embed-text:latest     0a109f422b47    274 MB    3 minutes ago    
mxbai-embed-large:latest    468836162de7    669 MB    3 minutes ago    
llama3.1:latest             a80c4f17acd5    2.0 GB    3 minutes ago
```

* test a single LLM:

```bash
kubectl -n ollama exec svc/ollama -- ollama run "llama3.1" "what is spring boot?"
```

**NOTICE**: The Microservices will access to the ADB23ai on which the vector store table should be created, as done in the local desktop example shown before. To access the {{< short_app_ref >}} running on **Oracle Backend for Microservices and AI** and create the same configuration, let’s do:

* tunnel:

```bash
kubectl -n ai-optimizer port-forward svc/ai-optimizer 8181:8501
```

* on localhost, connect to : `http://localhost:8181/ai-optimizer`

* Deploy with `oractl` on a new schema `vector`:

* kubernetes tunnel from one side:

```bash
kubectl -n obaas-admin port-forward svc/obaas-admin 8080:8080
```

* and with the oractl command line utility:

```bash
oractl:> create --app-name rag 
oractl:> bind --app-name rag --service-name myspringai --username vector
```

The `bind` will create the new user, if not exists, but to have the `SPRING_AI_VECTORS` table compatible with SpringAI Oracle vector store adapter, the microservices needs to access to the vector store table created by the {{< short_app_ref >}} with user ADMIN on ADB, for example:

```sql
GRANT SELECT ON ADMIN.MXBAI_EMBED_LARGE_512_103_COSINE TO vector;
```

* So, then you can deploy it:

```bash
oractl:> deploy --app-name rag --service-name myspringai --artifact-path <ProjectDir>/target/myspringai-1.0.0-SNAPSHOT.jar --image-version 1.0.0 --java-version ghcr.io/oracle/graalvm-native-image-obaas:21 --service-profile obaas
```

* test opening first a new tunnel:

```bash
kubectl -n rag port-forward svc/myspringai 9090:8080
```

* and finally from shell, if you have built a vector store on this doc "[Oracle® Database
Get Started with Java Development](https://docs.oracle.com/en/database/oracle/oracle-database/23/tdpjd/get-started-java-development.pdf)" :

```bash
curl -X POST "http://localhost:9090/v1/chat/completions" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer your_api_key" \
     -d '{"message": "Can I use any kind of development environment to run the example?"}' | jq .
```

it should return something like:

```bash

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

{{% notice style="code" title="Documentation is Hard!" icon="circle-info" %}}
More information coming soon... 25-June-2025
{{% /notice %}}