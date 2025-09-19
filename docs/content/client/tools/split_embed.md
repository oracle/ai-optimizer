+++
title = '📚 Split/Embed'
weight = 20
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

The first phase building of building a RAG Chatbot using Vector Search starts with the document chunking based on vector embeddings generation.  Embeddings will be stored into a vector store to be retrieved by vectors distance search and added to the LLM context in order to answer the question grounded to the information provided.

You have the freedom to choose different Embedding Models for vector embeddings provided by public services like Cohere, OpenAI, and Perplexity, or local models running on top a GPU compute node managed by the yourself.  Running a local model, such as Ollama or HuggingFace, avoids sharing data with external services that are beyond your control.

From the _Tools_ menu, select the _Split/Embed_ tab to perform the splitting and embedding process:

![Split](../images/split.png)

The Load and Split Documents, parts of Split/Embed form, will allow to choose documents (txt,pdf,html,etc.) stored on the Object Storage service available on the Oracle Cloud Infrastructure, on the client’s desktop or from URLs, like shown in following snapshot:

![Embed](../images/embed.png)

"Populating the Vector Store" will create a table in the Oracle Database with the embeddings.  You can create multiple vector stores, on the same set of documents, to experiment with chunking size, distance metrics, etc, and then test them independently.

## Embedding Configuration

Choose one of the **Embedding models available** from the listbox that will depend by the **Configuration/Models** page.
The **Embedding Server** URL associated to the model chosen will be shown. The **Chunk Size (tokens)** will change according the kind of embeddings model selected, as well as the **Chunk Overlap (% of Chunk Size)**.

Then you have to choose one of the **Distance Metric** available in the Oracle DB23ai:
- COSINE
- EUCLIDEAN_DISTANCE
- DOT_PRODUCT
- MAX_INNER_PRODUCT

To understand the meaning of these metrics, please refer to the doc [Vector Distance Metrics](https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/vector-distance-metrics.html) in the Oracle DB23ai "*AI Vector Search User's Guide*".

The **Embedding Alias** field let you to add a more meaningful info to the vectorstore table that allows you to have more than one vector table with the same: *model + chunksize + chunk_overlap + distance_strategy* combination.


## Load and Split Documents

The process that starts clicking the **Populate Vector Store** button needs:
- **File Source**: you can include txt,pdf,html documents from one of these sources:
    - **OCI**: you can browse and add more than one document into the same vectostore table at a time;
    - **Local**: uploading more than one document into the same vectostore table at a time;
    - **Web**: upload one txt,pdf,html from the URL provided.

- **Rate Limit (RPM)**: to avoid that a public LLM embedding service bans you for too much requests per second, out of your subscription limits.

The **Vector Store** will show the name of the table will be populated into the DB, according the naming convention that reflects the parameters used.
