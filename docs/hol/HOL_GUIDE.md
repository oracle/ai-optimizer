# Hands-on-lab Guide

## 1. Installation

### 1.1 Database 

The AI Vector Search in Oracle Database 23ai provides the ability to store and query private business data using a natural language interface. This framework uses these capabilities to provide more accurate and relevant LLM responses via Retrieval-Augmented Generation (**RAG**). [Oracle Database 23ai Free](https://www.oracle.com/database/free/get-started/) provides an ideal, no-cost vector store for this walkthrough.

#### Requirements

To complete this hands-on lab, you need the following:

- macOS or Windows (with Windows Subsystem for Linux),
- 32 GB RAM minimum recommended,
- 10 GB free disk space recommended,
- a Container runtime like Docker or Podman.

> Note: If you have sufficient resources, you may run the LLMs locally using Ollama (or similar).  If you do not have an adequate GPU and storage, you can use a hosted Ollama instance.  The lab instructor will give you details to connect to this instance.

---
#### 1.1.1 Set up for macOS option

> Note: If you are using Windows, please skip to the next section.

This lab works with a Container Runtime as mentioned before. If you want to use a lighter VM, you have the option to use Colima too. In this case you need as a pre-requisite to install **docker**.
Start the container runtime engine with a new profile. If you already have one that you want to use, please double-check that it uses 4 CPUs and 8GB of memory at minimum. Otherwise:

```bash
brew install colima
brew install qemu
colima start x86 --arch x86_64 --mount-type virtiofs --cpu 4 --memory 8
```

To simulate podman using colima and start colima with profile x86:

```bash
alias podman=docker 
colima start x86
```

---

#### 1.1.2 Setup for Windows option

This lab requires you to run one or more containers on your local machine.  Windows Subsystem for Linux is required, with a Linux distribution like Ubuntu.

The instructions below use `podman`.  If you are using a different container runtime, you may wish to create an alias so you can copy and paste commands from the instructions:

```
alias podman=docker
```


#### 1.1.3 Run Oracle Database 23ai Free container:

1. Start the container and wait for state `(healthy)`:

```bash
podman run -d --name db23ai -p 1521:1521 container-registry.oracle.com/database/free:latest
```

2. Connect to the database instance as the SYS user using SQL*Plus:

```bash
podman exec -it db23ai sqlplus '/ as sysdba'
```

3. Alter the vector_memory_size parameter and create a new database user:
```bash
alter system set vector_memory_size=512M scope=spfile;

alter session set container=FREEPDB1;

CREATE USER "VECTOR" IDENTIFIED BY vector
    DEFAULT TABLESPACE "USERS"
    TEMPORARY TABLESPACE "TEMP";
GRANT "DB_DEVELOPER_ROLE" TO "VECTOR";
ALTER USER "VECTOR" DEFAULT ROLE ALL;
ALTER USER "VECTOR" QUOTA UNLIMITED ON USERS;
EXIT;
```

4. Bounce the database for the vector_memory_size to take effect:

```bash
podman container restart db23ai
```

##### 1.1.3.1 Optional: Install VS Code SQL Developer Plug-in and connect to the DB
In the next steps of this lab, you will need to check the items inside your database 23ai. 

1. In order to do so, install the VS Code **SQL Developer** plugin by opening the Extensions page (Ctrl-Shift-X or equivalent) and search for "sql developer":

![sql-developer-plugin](images/sql-developer-plugin.png)

2. Once you have installed the VS Code plugin, navigate to it and click on the "+" button to setup a new connection:

![add-connection](images/add-connection.png)

3. A prompt will appear. You will have to add the details for your connection by editing these fields:

* **Connection Name**: *db23ai*, or whatever name you would like to use
* **Username**: *vector* (the username we set up with the SQL commands from above)
* **Password**: *vector* (the password we set up with the SQL commands from above)
* **Save Password**: (optionally) tick the box to save the connection credentials
* **Hostname**: *localhost*
* **Service Name**: *FREEPDB1*

> Note: Depending on your configuration, you may need to use the IP address of the container in the hostname field, instead of `localhost`.  To find the IP address, use the command `podman inspect db23ai | grep IPA`.

![test-connection](images/test-connection.png)

4. Once all the details have been submitted you can click on the *Test* button below. If all the credentials are correct, a prompt message stating: `Test passed for connection: db23ai` will appear. You can then click on the *Connect* button to finally set up the connection

### 1.2 LLM runtime
We'll to interact with different LLMs and we are going to use **Ollama** for running them.  

> Note: The lab instructor will provide you with details to connect to a shared, hosted Ollama instance.  If you are using the hosted instance, you can skip ahead to the next section **1.5**.

If you prefer to run Ollama on your own local machine, and you have the necessary resources, including a suitable GPU and adequate disk space for the models, follow the instructions **[here](https://ollama.com/download)** according your operating system.

We need to install some LLMs in Ollama (llama3.1 and mxbai for the embeddings). To do this step, open a new shell and run:

```bash
ollama pull llama3.1
ollama pull mxbai-embed-large
```

For **OpenAI** you need an **OPENAI_API_KEY** to authenticate and use their services. To get it go to the **[OpenAI developer platform](https://platform.openai.com/settings/organization/api-keys)**.

### 1.3 Clone the right branch
* Make sure to clone the branch `cdb`. Proceed in this way:

```bash
git clone --branch cdb --single-branch https://github.com/oracle-samples/ai-explorer.git
```

  It will be created a new dir named `ai-explorer`.

### 1.4 Install requirements:

> Note: You can run AI Explorer locally on your machine, or in a container.  This section describes the local **bare metal** installation.  If you want to use a container, skip ahead to the next section.

#### 1.4.1 Python version

The framework requires exactly **Python 3.11**, neither older nor newer.  Download and follow the instruction for **[Python 3.11 Download](https://www.python.org/downloads/release/python-3110/)** to install it on your system.

##### 1.4.1.1 Install Python 3.11 on macOS
If you are using a recent version of macOS, you will need to install that version side by side with the builtin one. In a shell run:

  ```bash
  brew install python@3.11
  python3.11 --version
  ```

##### 1.4.1.2 Install Python 3.11 on Windows
Open a Windows Subsystem for Linux terminal (this guide assumes you are using Ubuntu as your Linux distribution).

```bash
sudo apt install python3.11 python3.11-venv
python3.11 --version
```

#### 1.4.2 Create environment

In a shell, run in the directory `ai-explorer`:

  ```bash
   cd src
   python3.11 -m venv .venv --copies
   source .venv/bin/activate
   pip3.11 install --upgrade pip wheel setuptools
  ```

#### 1.4.3 Install the Python modules:

Always in the directory `ai-explorer` run:

   ```bash
   cd src
   pip3.11 install -e ".[all]"
   source .venv/bin/activate
   ```

#### 1.4.4 Startup 

* Create a `launch_server.sh` file in the directory `ai-explorer` to set your environment variables (see below for details):
 
  ```bash
  export API_SERVER_KEY=<API_SERVER_KEY>
  export API_SERVER_URL="http://localhost"
  export API_SERVER_PORT=8000
  export OPENAI_API_KEY=<OPENAI_API_KEY>
  export DB_USERNAME=vector
  export DB_PASSWORD=vector
  export DB_DSN="localhost:1521/FREEPDB1"

  export ON_PREM_OLLAMA_URL="http://localhost:11434"

  cd src  
  source .venv/bin/activate
  python launch_server.py
  ```

  Make sure the script is executable:

  ```bash
  chmod +x launch_server.sh
  ```

  The script `launch_server.sh` holds environment variables needed to connect the database and OpenAI, and the `API_SERVER_KEY` to authenticate the client. Set one, for example, `abc12345` and use the same in the following `launch_client.sh`. 

  > Note: You can choose any value for the `API_SERVER_KEY`, but it must match in the server and client scripts.

  Set the `OPENAI_API_KEY` in the server script.  We recommend that you create an API Key for this hands-on lab that you can easily remove when you are finished the lab.

  If, for any reason, you need to adapt the DBMS to a different instance and setup, change the variables accordingly.

  > Note: If you want to use the hosted Ollama server, use the connection details that the lab instructor gave you.  Only use localhost if you are running Ollama locally on your own machine.

* Create a `launch_client.sh` file in the directory `ai-explorer`:

  ```bash
  export API_SERVER_KEY=<API_SERVER_KEY>
  cd src
  source .venv/bin/activate
  streamlit run launch_client.py --server.port 8502
  ```

  Set the same `<API_SERVER_KEY>` as you used in the server script, so that the client can authenticate to the server.


  Make sure the script is executable:

  ```bash
  chmod +x launch_client.sh
  ```

##### 1.4.4.1 Start the server

* In a separate shell, in the directory `ai-explorer` run:

    ```bash
    ./launch_server.sh
    ```

  ⚠️ **Warning**

    On Windows, you may see an exception starting the server. Please run this command and retry:

    ```bash
    pip3.11 install platformdirs
    ```
##### 1.4.4.2  Start the client
    
* in another shell, in dir `ai-explorer` run:
  ```bash
  ./launch_client.sh
  ```

### 1.5 Container Installation

To run the application in a container; download the [source](https://github.com/oracle-samples/ai-explorer/tree/cdb):

1. Build the all-in-one image.

   From the `src/` directory, build image:

   ```bash
   cd src/
   podman build -t ai-explorer-aio .
   ```

1. Start the Container:

   ```bash
   podman run -p 8501:8501 -it --rm ai-explorer-aio
   ```

1. Navigate to `http://localhost:8501`.

1. [Configure](https://oracle-samples.github.io/ai-explorer/client/configuration/index.html) the **Explorer**.


## 2. Explore the env
In a browser, open the link: `http://localhost:8502/`

### 2.1 DB connection

Let's check if the DB is correctly connected:

![DB](images/db.jpg)

You should see the message: `Current Status: Connected`

### 2.2 Optional: OCI Credentials

In this lab you will not use **Oracle Cloud Infrastructure**. Anyway, if you have an active OCI tenant, these are the instructions to use it.
In the OCI configuration tab, you can add your Oracle Cloud Infrastructure (OCI) credentials to authenticate with your OCI tenancy. This will enable access to objects and documents stored in your cloud compartments.

![OCI](images/oci.jpg)

Detailed information on obtaining the required credentials is available in the [Oracle Cloud Infrastructure Documentation](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm#Required_Keys_and_OCIDs).

If you have previously created a `.oci/config` file, the framework will automatically read this file at startup and load the credentials from the Default profile for authentication. To create one, follow the instructions [here](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm#Quickstart).

After entering your credentials, click the Save button. If the credentials are correct, a green confirmation pop-up will appear, indicating successful authentication to your tenancy.

![OCI-CREDENTIALS](images/oci-credentials-success.png)

### 2.3 LLM config

Let's check models available:

![models menu](images/models.jpg)

  * The default LLMs for chat completions are:

  ![llms](images/llms.png)

  * The default LLMs for embeddings are:

  ![embeddings](images/emb.png)

  * **OPTIONAL**: We can configure the Ollama models so that they can reach a url endpoint where the models are already configured. For example, click on the *edit* button for llama3.1 LLM and fill the *API URL* field with this endpoint 

 ```plaintext
  http://<IP_OLLAMA>:11434 
  ```

  ![llama3.1-endpoint](images/llama3.1-endpoint.png)

  Now repeat this step also for the *mxbai-embed-large* embedding model.

* **OPTIONAL**: Let's add another LLM to Ollama (for local deployments only) and enable it in the model list.

  * Let's add the model LLama3.2:

  ```bash
    ollama pull llama3.2
  ```
  * Now, we will enable in the model list. Under left menu **Models** / **Language Models**, press button **Add**, and complete the form with the values shown in the following snapshot:

  ![new_llama32](images/addllama32.png)


### 2.4 Chat
The two LLMs available could be tested straightful to understand their behaviour with generic questions. Before to access the chat GUI

![chat](images/chat.jpg)

scroll down the left side menu to find the **Chat model** menu:

![chat models](images/chatmodel.png)

and, with the **Enable RAG?** check-box not selected, choose the **gpt-4o-mini** and ask generic questions like these:

```
Which kind of database you can use to run the Java Web example application?
```

```
Can I use any kind of development environment to run the example?
```

NOTICE: *if you see a message on top **Database has no Vector Stores. Disabling RAG.** don't worry since you haven't yet create a vector store and you can't use the RAG*.

As you can see, even if the question means to refer a specific example, the LLM answers in a generic way. 

* Click the button **Clear** under **History and Context**, and choose the other LLM available, **llama3.1**,
to start a conversation with the same questions, and compare the answers. Note that the **History** is enabled by default. The **Clear** button resets the “context window” and starts a fresh conversation with a model.

* Play with the **Temperature** parameter, and the others to compare the quality of the answers, for each LLM available. Clear the history pressing button **Clear** after each cycle.


### 2.5 Prepare vector store

#### 2.5.1 Split/Embed Documents

In the **Split/Embed** tab, the framework allows you to upload various types of documents and transform their content into vector embeddings in a format that is interpretable by LLMs.

![split-embed-interface](./images/split-embed.jpg)

You will find the models enabled during the initial configuration and you can choose one of them using the drop-down menu and adjust their parameters accordingly.
For the first one choose **mxbai-embed-large**. The chunk size defines the length of each segment into which the document will be splitted, while the chunk overlap represents the percentage of overlap between consecutive chunks relative to the chunk size.

Additionally, you can select different distance metrics and index types to experiment with various vector representations of the same document, allowing you to identify the configuration that best fits your needs.

Once configured, scroll down to the **Load and Split Documents** section to upload the document you wish to store in your **Oracle Database 23ai**. You can upload more than one at a time, but in this lab we will use just one.

![populate-vector-store](images/populate-vector-store.png)

You can choose from three different file sources:

* **OCI**: Navigate through your tenancy to select documents from the Object Storage. Ensure that your OCI credentials are properly configured in advance. If not, you will not see the option.
* **Local**: Upload documents directly from your local environment.
* **Web**: Import a document from publicly accessible web URL.

In this example, we will embed a document availble on the web: **[Get started with java development](https://docs.oracle.com/en/database/oracle/oracle-database/23/tdpjd/get-started-java-development.pdf)**. We will give the alias ***TEST1*** to this vector store.

You can then click on the **Populate Vector Store** button and start the embedding process.

Once the process is complete, a green confirmation prompt will appear, indicating the number of chunks that have been generated and successfully stored in the database.

![vector-store-populated](images/vector-store-populated.png)

This means that 224 vectors representations of the information from the input document have been chunked, created relative vector embeddings and stored.

#### 2.5.2 Inspect the Vector DB

As an example, you can query the vector store by connecting to your Oracle Database 23ai instance using the SQL Developer plugin we mentioned earlier:

![query-vector-db](images/query-vector-db.png)

If you haven't install it, you can run a query with **sqlplus** or any other Oracle DB client, to retrieve the rows from the newly created table with this command:

```sql 
select * from VECTOR.TEST1_MXBAI_EMBED_LARGE_512_103_COSINE_HNSW;
```

What you see in the image above are chunks of text from the input document, which have been transformed into vector format and stored in the Oracle database. Essentially, you’ve replicated the knowledge contained in the document within your database!

By following the sames steps, we can create another vector store using the same document, but with a different embedding model: **text-embedding-3-small** from the OpenAI catalog models. We will give the alias ***TEST2*** to this vector store. 
In this case, we will get a smaller number of chunks, since the model supports a chunk size of 8191 instead of the 512 given by *mxbai-embed-large*:

![text-embedding-3-small](images/text-embedding-3-small.png)

You can now navigate to the Database tab in the framework to see the list of all the vector stores that have been created. If needed, you can easily delete them with a single click.

![database-vector-store-list](images/database-vector-store-list.png)

Note that you can upload on the same vector store alias additional documents that will increase the knowledge base available to you chatbot.

### 2.6 RAG test
Now that we have two vector stores, let's start to test the second knowledge base created with the OpenAI service:`TEST2` to use classical public resources.

* Clear history pressing button **Clear** and choose **gpt-4o-mini** model for initial test.

* Scrolling down the left side pane, **Enable RAG?**. 

* In **Select Alias** dropdown box, select the `TEST2` vector store table. You will see the rest of the fields of **Vector Store** menu automatically populated, since each of them represent a search parameter that could be used to select the vector store created. In this case, the alias is enough to determine what you are looking for but, from the other side, you have the evidence of the parameteres used to create the chunk and related embeddings vector.

* Let's ask again the same previous questions to which the LLM has provided generic answers since it's likely that the LLM didn't use during its training. Now, with the document loaded in the datastore selected, let's see the difference:

```
Which kind of database you can use to run the Java Web example application?
```

```
Which Java environment should be used to run this example?
```

On `TEST2` vector store you will try with the main params set in the following way, how will change the quality of the answers. 
**IMPORTANT**: Clear history, pressing button **Clear** after each question, also if you change the parameters and repeat the same question.

  * LLM:gpt-4o-mini
  * TopK: 4
  * Search Type: Similarity
  * Temperature: 0

*Question to submit:*
```
Which Java environment should be used to run this example?
```
*Answer likely:*
```
The example should be run in an integrated development environment (IDE), specifically using IntelliJ IDEA community version as recommended in the documentation. Additionally, it will require a Web server with a servlet and JSP container, with Apache Tomcat being the server suggested for deploying the JSP pages (as per the guide).
```

  * LLM: gpt-4o-mini
  * TopK: 10
  * Search Type: Similarity
  * Temperature: 0

*Question to submit:*
```
Which Java environment should be used to run this example?
```
*Answer likely:*
```
The example is recommended to be developed in an integrated development environment (IDE) like IntelliJ IDEA, specifically the community version, for ease of development. Additionally, the application uses Apache Tomcat as the web server for deploying the JavaServer Pages (JSP) technology in the HR Web application. For database connectivity, the Java code should be run on the Oracle Database, leveraging the capabilities of the Oracle JDBC Thin driver with a Java Virtual Machine (JVM) (Chapter 4 and Chapter 1).
```

**COMMENT**: as you can see with more chunks provided, the bot mentions also other technologies like Oracle JDBC, JVM and the Oracle Database.


  * LLM: gpt-4o-mini
  * TopK: 4
  * Search Type: Similarity
  * Temperature: 0

*Question to submit:*
```
Which kind of database you can use to run the Java Web example application?
```

*Answer likely:*
```
You can use the Oracle Database, specifically the Autonomous Transaction Processing database, to run the Java Web example application. This is part of the requirements for developing the HR web application, which operates within the Oracle Database environment (see Chapter 4, "What You Need to Install").
```

  * LLM: gpt-4o-mini
  * TopK: 10
  * Search Type: Similarity
  * Temperature: 0

*Question to submit:*
```
Which kind of database you can use to run the Java Web example application?
```
*Answer likely:*
```
You can use the Oracle Database to run the Java Web example application, specifically the HR schema within the Oracle Database. The application can be developed using either an on-premises installation of Oracle Database or Oracle Autonomous Database in the cloud (as part of Oracle Cloud Free Tier) which is recommended for its ease of access and automation (see Chapter 4).
```

**COMMENT**: In the second answer it mentions the Oracle Cloud Free Tier.

* NOTICE: *since the LLMs are probabilistic models, you would have slightly different answers*.

* Conclusion: we can suppose that 10 chunks, as TopK similar vector, represents a better parameter than the deafult 4.

* Play with Temperature to discover how much become reacher in terms of expression the answers provided.

* Follow a question by another like "more info" to have the evidence that the history is considered providing the answer in the conversation.

* Clear history, pressing button **Clear**.

### 2.6.1 OLLAMA test.
Repeat the tests with local LLMs based on the OLLAMA server and the vector store: `TEST1`. Click on **Reset** button to choose the new vector store table. Then choose **llama3.1** in **Chat model** dropdown menu to have the same LLM provider.
 

### 2.7 Testbed
We are confident that changing some parameters the quality and accuracy of the answers improve. But are you sure that on a large scale deployment your setup it's reliable on hundreds or thousands of different questions?
Testbed helps you to massively test your chatbot, generating for you a Q&A test dataset and automatically try on your current chat configuration. Let's access to the Testbed from left pane menu:

![testbed](./images/tesbed.png)

#### 2.7.1 Generate a Q&A Test dataset
The platform allows to generate as many questions and answer you desire, based on a single document, that it's part of the knowledge base you have store as vector store with their own embeddings. 

1. Selecting the proper radio button **Generate Q&A Test Set** you will access to the framework test dataset generation capabilities:

![generate](./images/generatenew.png)

2. Upload the document used to create the vector store, getting from this [this link](https://docs.oracle.com/en/database/oracle/oracle-database/23/tdpjd/get-started-java-development.pdf).

3. Increase the number to be generated to 10 or more. Take in consideration that the process it's quite long, especially if you will use local LLM for Q&A generation without enough hardware capacity. In case of OpenAI remote model, the process it's less affected by increasing the number of Q&As than the private LLM approach.

4. Leave the default option for:
  * Q&A Language Model: **gpt-4o-mini**
  * Q&A Embedding Model: **text-embedding-3-small**

5. Click on **Generate Q&A** button and wait up to the process is over:

  ![patience](./images/patience.png)

6. Update the **Test Set Name**, changing the default one automatically generated, in order to identify more easily later the test dataset for repeated tests on different chatbot configurations. For example, from:

  ![default_test_set](./images/default_test_set.png)

change in :

  ![test_rename](./images/test_rename.png)

7. Browse the questions and answers generated:

  ![qa_browse](./images/qa_browse.png)

  Note that the **Question** and the **Answer** fields are editable, since you can correct at your convenience the proposed Q&A pairs based on the **Context** that has been extracted randomly and not editable, as well as the **Metadata** that are set by the Testbed engine. In Metadata field you'll find a **topic** tag that classify the Q&A. The topic list is generated automatically analyzing the text and added to each Q&A. It will be used in the final report to drilldown the **Overall Correctness Score** and identify the area in which the chatbot lacks of precision.
  The **Download** allows to export and modify the Q&A dataset generated in every part. Open it in Visual Studio Code to see the content:

  ![qa_json](./images/qa_json.png)

8. On the left pane menu:

  * Under **Language Model Parameters**, select in the **Chat model** dropdown list **gpt-4o-mini**
  * **Enable RAG?** if for any reason hasn't been selected
  * Choose in the **Select Alias** dropdown list the **TEST2** value.
  * Leave unchanged the default parameters on the left pane.

9. Leaving the default one model to judge, **gpt-4o-mini**, click on **Start Evaluation** button and wait a few seconds. All the questions will be submitted to the chatbot as configured in the left pane:

  ![start_eval](./images/start_eval.png)

10. Let's examine the result report, starting from the first part:

  ![result](./images/result_topic.png)

It shows:
  * The chatbot's **Evaluation Settings** as it has been configured in the left side playground, before start the massive test.
  * The **RAG Settings** for the Database and the relative Vector Store selected, with the name of the embedding **model** used and all the parameters set, from **chunk_size** to the **top_k**.
  * The **Overall Correctness Score** represents the percentage between the total number of questions submitted, and the answers considered correct by the LLM used to judge the response compared to the reference answer.

  ![result](./images/topics.png)
  
  * The **Correctness By Topic**: each question in the test dataset comes with a tag that represents the topic it belongs to. The list of topics it's extracted automatically at the creation step of the Q&A synthetic dataset. The number of topics could change depending on the document provided.

The second part of the report provides details about each single questions submitted, with a focus on the collection by **Failures** and the **Full Report** list. To show all the fields, scrool from the right to left to see all info. In the following picture the second frame has been scrolled:

  ![result](./images/result_question.png)

  * **question**: questions submitted
  * **reference_asnwer**: represents the anwers that is considered correct an we aspect quite similar to the answer will be provided by the agent
  * **reference_context**: the section of document extracted and used to create the Q&A
  * **agent_answer**: the answer provided by the chatbot with the current configuration and knowledge base as vectorstore
  * **correctness_reason**: it reports eventually why has been judged not correct. If the answer 
  has been considered right you'll see **None** as value.

* You can get a copy of the results as an HTML page reporting the *Overall Correctness Score* and *Correctness By Topic* only, cliccking on the **Download Report** button. Click it to view how is the report. 

* You can also download the **Full Report** and **Failures** list as a *.csv* file selecting each frame as shown in the following snapshot:

  ![csv](./images/download_csv.png)

11. Now let's test through an external saved test datset, that you can download [here](https://raw.githubusercontent.com/oracle-samples/ai-explorer/refs/heads/cdb/docs/hol/artifacts/getting_started-30_testset.json) with 30 questions already generated. If you want to drop some Q&A that are not meaningful in your opinion, update it, save and reload as local file, following the steps shown in this snapshot:

  ![load_tests](./images/load_tests.png)

12. Now redo the test to get the **Overall Correctness Score** with much more Q&A pairs.

* Let's change the Chat model parameters, setting to **0** the Model **Temperature** in the left pane, section **Language Model Parameters**. Why? Because the Q&As generated are usually done with a low level of creativity to be less random in the content provided and express the core concepts avoiding "frills". So, repeat the test to check if there are any improvements in the **Overall Correctness Score**. 

13. To compare with previous results, click on dropdown list under **Previous Evaluations for...** and click on **View** button to show the overall report.

  ![previous](./images/previous.png)

14. Repeat the tests as many time you desire changing: **Vector Store**, **Search Type** and **Top K** to execute the same kind of tuning you have done at the previous steps with just a few interactive questions, now on a massive test on curated and comparable assets. *Remember to click on **Reset** button to choose again the vector store to be used during the test*.


## 3. Export and run the chatbot as a Spring AI microservice

The framework allows to export the chatbot defined as a ready-to-run microservice built in Java, Spring Boot and Spring AI framework, that will run independently by the framework, leveraging only the vector store table created, and the LLM servers used. In the current release are supported only fully Ollama configuration (embeddings + chat model) or OpenAI.

### 3.1 Pre-requisites
To run the microservice exported you need:
  * JDK 21.x 
  * Apache Maven 3.8.x
  * curl command

### 3.2 Execute the Ollama version

* **Select Alias:** as **TEST1** vector store, and **LLama3.1** as **Chat model**. In this way the configuration will be based on the Ollama LLM server provider for both LLMs, embeddings and chat, and go to the **Settings** menu in the left pane side. You'll find the **Download SpringAI** button available.
  
If you'll find a message like this:

  ![notollama](./images/diff_llm_springai.png)

don't worry: choose for the **Chat model:** the **llama3.1** and the button will appear.

* Download one of them through the `Download SpringAI` button. 

* Unzip the file in a subdir.

* Open a terminal and set the executable permission on the `env.sh` with `chmod 755 ./start.sh`.

* Start the microservice with:

```
./start.sh
```

* This microservice exposes a web service that will accept HTTP GET requests at:

  * `http://localhost:8080/v1/chat/completions`: to use RAG via OpenAI REST API;
  * `http://localhost:8080/v1/service/llm` : to chat straight with the LLM used;
  * `http://localhost:8080/v1/service/search/`: to search for documents similar to the message provided.

* To test it, run a curl command like this in a new terminal:

  ```
  curl -X POST "localhost:8080/v1/chat/completions" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer your_api_key" \
     -d '{"message": "Can I use any kind of development environment to run the example?"}'  
  ```

* The response with RAG, on the **TEST1** Vector store, it will be like this:

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

  * A request without leverage RAG:
  ```
  curl --get --data-urlencode 'message=Can I use any kind of development environment to run the example?' localhost:8080/v1/service/llm 
  ```

     it will produce a response not grounded like this:

  ```
  {
    "completion": "Yes, you can use various development environments to run examples, depending on the programming language and the specific example you are working with. Here are some common options:\n\n1. **Integrated Development Environments (IDEs)**:\n   - **Visual Studio Code**: A versatile code editor that supports many languages through extensions.\n   - **PyCharm**: Great for Python development.\n   - **Eclipse**: Commonly used for Java development.\n   - **IntelliJ IDEA**: Another popular choice for Java and other languages.\n   - **Xcode**: For macOS and iOS development (Swift, Objective-C).\n\n2. **Text Editors**:\n   - **Sublime Text**: A lightweight text editor with support for many languages.\n   - **Atom**: A hackable text editor for the 21st century.\n   - **Notepad++**: A free source code editor for Windows.\n\n3. **Command Line Interfaces**:\n   - You can run"
  }
  ```

### 3.3 Execute the OpenAI version
Proceed as in the previous step, choosing in **Select Alias:** the **TEST2** vector store, and **gpt-4o-mini** as **Chat model**. In the terminal where you'll run the Spring Boot microservice, be sure that the **OPENAI_API_KEY** is correctly set.


## 4. Backup Env
All the config related to the server can be exported to save the configuration as backup or imported in another server.

* Go to the left pane menu **Settings**:

![Settings](images/settings.png)

* Drilling down the tree, you can access to all the parameters related, for example, to one of the LLMs configured:

![Settings_llama](images/settings_llama.png)

* From this page you can:
  * **Upload** an existing configuration file
  * **Download Settings** of the current configuration
  * Exclude by the download the credential parameters, unchecking the **Include Sensitive Settings**


## 5. Challenge
Let's test on a large scale your competencies gain so far with a challenge that, providing a doc, ask you to determine the best framework configuration to obtain the highest **Overall Correctness Score** on a knowledge base.
The proposed doc to create the knowledge base is the: 

**[Oracle Government PaaS and IaaS Cloud Services - Service Descriptions](https://www.oracle.com/contracts/docs/us_gov_tech_cloud_3902270.pdf)**

an Oracle's document related to the services available on the Oracle Cloud Infrastructure.
To test the configuration setup, we provide a 50 Q&A pairs test dataset, you can download: [here](https://raw.githubusercontent.com/oracle-samples/ai-explorer/refs/heads/cdb/docs/hol/artifacts/OCIGOV50_testset.json), to be used as a benchmark to evaluate your chatbot quality.

Enjoy!

