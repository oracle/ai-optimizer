+++
title = '📚 Split/Embed'
weight = 20
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

The first phase of building a RAG Chatbot using Vector Search starts with the document chunking based on vector embeddings generation.  Embeddings will be stored into a vector store to be retrieved by vectors distance search and added to the LLM context in order to answer the question grounded to the information provided.

You have the freedom to choose different Embedding Models for vector embeddings provided by public services like Cohere, OpenAI, and Perplexity, or local models running on top of a self-managed GPU compute node.  Running a local model, such as Ollama or HuggingFace, avoids sharing data with external services that are beyond your control.

From the _Tools_ menu, select the _Split/Embed_ tab to perform the splitting and embedding process:

![Split](../images/split.png)

## Create New Vector Store

You might have notice a *Create New Vector Store* option. Toggling this option will allow you to create a brand new vector store table in which you can embed your data source. The Load and Split Documents, parts of Split/Embed form, will allow users to choose documents (txt,pdf,html,etc.) stored in the Object Storage service available on the Oracle Cloud Infrastructure, on the client’s desktop or from URLs, like shown in following snapshot:

![Embed](../images/embed.png)

"Populating the Vector Store" will create a table in the Oracle Database with the embeddings.  You can create multiple vector stores, on the same set of documents, to experiment with chunking size, distance metrics, etc, and then test them independently.

### Embedding Configuration

Choose one of the **Embedding models available** from the listbox that will depend by the **Configuration/Models** page.
The **Embedding Server** URL associated to the model chosen will be shown. The **Chunk Size (tokens)** will change according the kind of embeddings model selected, as well as the **Chunk Overlap (% of Chunk Size)**.

Then you have to choose one of the **Distance Metric** available in the Oracle DB23ai:
* COSINE
* EUCLIDEAN_DISTANCE
* DOT_PRODUCT

To understand the meaning of these metrics, please refer to the doc [Vector Distance Metrics](https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/vector-distance-metrics.html) in the Oracle AI Database 26ai "*AI Vector Search User's Guide*".

The **Embedding Alias** field lets you add a more meaningful info to the vectorstore table that allows you to have more than one vector table with the same: *model + chunksize + chunk_overlap + distance_strategy* combination.

The **Description** field lets you add additional text to describe the content of what will be stored in the Vector Store table. This will be very helpful when using AutoRAG, as it will help the LLM to match the user's query to the most relevant vector table stored in the Database.


### Load and Split Documents

The process that starts clicking the **Populate Vector Store** button needs:
- **File Source**: you can include txt,pdf,html documents from one of these sources:
    - **OCI**: you can browse and add more than one document into the same vectostore table at a time;
    - **Local**: uploading more than one document into the same vectostore table at a time;
    - **Web**: upload one txt,pdf,html from the URL provided.
    - **SQL**: define a query on an Oracle DB to extract a field of VARCHAR2 type to embed the contents, row-by-row. Set the following parameters:
        - **DB Connection**: put in input a string like
        ```CO/Welcome_12345@localhost:1521/FREEPDB1```
        - **SQL**: set a query like
        ```select PRODUCT_NAME from PRODUCTS``` to get just one field. The content it will be embedded from a string starting with the field name, to provide a better context in the chunk similarity search.


- **Rate Limit (RPM)**: to avoid that a public LLM embedding service bans you for too much requests per second, out of your subscription limits.

The **Vector Store** will show the name of the table will be populated into the DB, according the naming convention that reflects the parameters used.

## Edit existing Vector Store

If you untoggle the *Create New Vector Store* button, you will be able to edit an existing Vector Store alias:

![Edit Store](../images/edit_vector_store.png)