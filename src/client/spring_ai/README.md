# Spring AI template

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


## Oracle Backend for Microservices and AI (rel. 1.4.0)

To simplify as much as possible the process, configure the Oracle Backend for Microservices and AI Autonomous DB to run the AI Optimizer and toolkit. In this way, you can get smoothly the vectorstore created to be copied as a dedicated version for the microservice running. If you prefer to run the microservice in another user schema, before the step **5.** execute the steps described at  **Other deployment options** chapter.

* Create a user/schema via oractl. First open a tunnel:
```bash
kubectl -n obaas-admin port-forward svc/obaas-admin 8080:8080
```

* run `oractl` and connect with the provided credentials

* create a namespace to host the AI Optimizer and Toolkit :

```bash
namespace create --namespace <OPTIMIZER_NAMESPACE>
```

* create the datastore, saving the password provided:
```bash
datastore create --namespace <OPTIMIZER_NAMESPACE> --username <OPTIMIZER_USER> --id <DATASTORE_ID>
```

* For the AI Optimizer and Toolkit local startup,  setting this env variables in startup:

```bash
DB_USERNAME=<OPTIMIZER_USER>
DB_PASSWORD=<OPTIMIZER_USER_PASSWORD>
DB_DSN="<Connection_String_to_Instance>"
DB_WALLET_PASSWORD=<Wallet_Password>
TNS_ADMIN=<Wallet_Zip_Full_Path>
```

NOTE: if you need to access to the Autonomus Database backing the platform as admin, execute:
```bash
kubectl -n application get secret <DB_NAME>-db-secrets -o jsonpath='{.data.db\.password}' | base64 -d; echo
```
to do, for example:
```bash
DROP USER vectorusr CASCADE;
```

Then proceed as described in following steps:

1. Create an `ollama-values.yaml` to be used with **helm** to provision an Ollama server. This step requires you have a GPU node pool provisioned with the Oracle Backend for Microservices and AI. Include in the models list to pull the model used in your Spring Boot microservice. Example:

```yaml
ollama:
  gpu:
    enabled: true
    type: 'nvidia'
    number: 1
  models:
    pull:
      - llama3.1
      - llama3.2
      - mxbai-embed-large
      - nomic-embed-text
nodeSelector:
  node.kubernetes.io/instance-type: VM.GPU.A10.1
```

2. Execute the helm chart provisioning:

```bash
helm upgrade --install ollama ollama-helm/ollama \
  --namespace ollama \
  --create-namespace \
  --values ollama-values.yaml
```

Check if the deployment is working at the end of process.
You should get this kind of output:

```bash
1. Get the application URL by running these commands:
  export POD_NAME=$(kubectl get pods --namespace ollama -l "app.kubernetes.io/name=ollama,app.kubernetes.io/instance=ollama" -o jsonpath="{.items[0].metadata.name}")
  export CONTAINER_PORT=$(kubectl get pod --namespace ollama $POD_NAME -o jsonpath="{.spec.containers[0].ports[0].containerPort}")
  echo "Visit http://127.0.0.1:8080 to use your application"
  kubectl --namespace ollama port-forward $POD_NAME 8080:$CONTAINER_PORT
```

3. check all:
* run: 
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

NOTICE: for network issue related to huge model download, the process could stuck. Repeat it, or choose to pull manually just for test, removing from the helm chart the `models` part in `ollama-values.yaml`. 

To remove it and repeat:
* get the ollama [POD_ID] stuck:

```bash
kubectl get pods -n ollama
```

* the uninstall:
```bash
helm uninstall ollama --namespace ollama

kubectl delete pod <POD_ID> -n ollama --grace-period=0 --force
kubectl delete pod -n ollama --all --grace-period=0 --force
kubectl delete namespace ollama
```

* install helm chart without models

* connect to the pod to pull manually:
```bash
kubectl exec -it <POD_ID> -n ollama -- bash
```

* run: 
```bash
ollama pull llama3.2
ollama pull mxbai-embed-large
```

* Build, depending the provider `<ollama|openai>`:

```bash
mvn clean package -DskipTests -P <ollama|openai> -Dspring-boot.run.profiles=obaas
```

4. Connect via oractl to deploy the microservice, if not yet done:

* First open a tunnel:
```bash
kubectl -n obaas-admin port-forward svc/obaas-admin 8080:8080
```
* run `oractl` and connect with the provided credentials

5. Execute the deployment:

```bash
artifact create --namespace <OPTIMIZER_NAMESPACE>  --workload <WORKLOAD_NAME> --imageVersion 0.0.1 --file <FULL_PATH_TO_JAR_FILE>

image create --namespace <OPTIMIZER_NAMESPACE>  --workload <WORKLOAD_NAME>--imageVersion 0.0.1

workload create --namespace <OPTIMIZER_NAMESPACE>  --imageVersion 0.0.1 --id <WORKLOAD_NAME> --cpuRequest 100m --framework SPRING_BOOT

binding create --namespace <OPTIMIZER_NAMESPACE>  --datastore <DATASTORE_ID> --workload <WORKLOAD_NAME> --framework SPRING_BOOT
```

6. Let's test:
* open a tunnel:

```bash
kubectl -n <OPTIMIZER_NAMESPACE> port-forward svc/<WORKLOAD_NAME> 9090:8080
```

* test via curl. Example:

```bash
curl -N http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "server",
    "messages": [{"role": "user", "content": "Can I use any kind of development environment to run the example?"}],
    "stream": false
  }'
```

7. Open to external access via APISIX Gateway:

* get the Kubernetes [EXTERNAL-IP] address:

```bash
kubectl -n ingress-nginx get svc ingress-nginx-controller
```

* get the APISIX password:

```bash
kubectl get secret -n apisix apisix-dashboard -o jsonpath='{.data.conf\.yaml}' | base64 -d | grep 'password:'; echo
```

* connect to APISIX console:

```bash
kubectl port-forward -n apisix svc/apisix-dashboard 8090:80
```
and provide the credentials at local url http://localhost:8090/,  [admin]/[Password]

* Create a route to access the microservice:

```bash
Name: <WORKLOAD_NAME>
Path: /v1/chat/completions*
Algorithm: Round Robin
Upstream Type: Node
Targets: 
  Host:<WORKLOAD_NAME>.<OPTIMIZER_NAMESPACE>.svc.cluster.local
  Port: 8080
```

8. Test the access to the public IP. Example:
```bash
curl -N http://<EXTERNAL-IP>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "server",
    "messages": [{"role": "user", "content": "Can I use any kind of development environment to run the example?"}],
    "stream": false
  }'
```



### Other deployment options

If you want to run on another schema instead the [OPTIMIZER_USER], you should add a few steps.

1. Connect to the backend via oractl:

* First open a tunnel:
```bash
kubectl -n obaas-admin port-forward svc/obaas-admin 8080:8080
```
* Run `oractl` and connect with the provided credentials

* Create a dedicated namespace for the microservice:

```bash
namespace create --namespace <MS_NAMESPACE>
```

* Create a dedicated user/schema for the microservice, providing a [MS_USER_PWD] to execute the command:

```bash
datastore create --namespace <MS_NAMESPACE> --username <MS_USER> --id <MS_DATASTORE_ID>
```


2. Connect to the Autonomous DB instance via the [OPTIMIZER_USER]/[OPTIMIZER_USER_PASSWORD]

* Grant access to the microservice user to copy the vectorstore used:

```bash
GRANT SELECT ON "<OPTIMIZER_USER>"."<VECTOR_STORE_TABLE>" TO <MS_USER>;
```

3. Then proceed from the step 5. as usual, changing:

* **<OPTIMIZER_USER>** -> **<MS_USER>**
* **<OPTIMIZER_NAMESPACE>** -> **<MS_NAMESPACE>**
* **<DATASTORE_ID>** -> **<MS_DATASTORE_ID>**


### Cleanup env

* First open a tunnel:
```bash
kubectl -n obaas-admin port-forward svc/obaas-admin 8080:8080
```

* Run `oractl` and connect with the provided credentials:

```bash
workload list --namespace <MS_NAMESPACE>
workload delete --namespace <MS_NAMESPACE> --id myspringai
image list
image delete --imageId <ID_GOT_WITH_IMAGE_LIST>
artifact list
artifact delete --artifactId <ID_GOT_WITH_ARTIFACT_LIST>
```
* disconnect [OPTIMIZER_USER] from  DB (the Optimizer server) and finally with **oractl**:

```bash
datastore delete --namespace <OPTIMIZER_NAMESPACE> --id optimizerds
namespace delete optimizerns
```