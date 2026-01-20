+++
title = '📚 Split/Embed'
weight = 20
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

The first phase in building a RAG chatbot based on vector search is document splitting and embedding. During this phase, source documents are divided into chunks, vector embeddings are generated for each chunk, and the resulting embeddings are stored in a vector store. At query time, relevant chunks are retrieved using vector distance search and injected into the Large Language Model (LLM) context to produce grounded answers based on the provided information.

You can choose from multiple embedding models provided by external services such as Cohere, OpenAI, and Perplexity, or use local models running on a self-managed GPU compute node. Running local models, for example via Ollama or Hugging Face, avoids sharing data with external services that are outside your administrative control.

To perform document splitting and embedding, open the Tools menu and select the **Split/Embed tab**:

![Split](../images/split.png)

## Create New Vector Store

The **Create New Vector Store** option allows you to create a new vector store table and populate it with embeddings generated from one or more data sources. When this option is enabled, the Load and Split Documents section of the Split/Embed form lets you select documents in formats such as TXT, PDF, or HTML.

Documents can be sourced from:

* **Oracle Cloud Infrastructure (OCI) Object Storage**, allowing you to browse and select multiple documents;
* **Local files**, enabling the upload of multiple documents from the client machine;
* **Web URLs**, for loading a single TXT, PDF, or HTML document from a specified address.

![Embed](../images/embed.png)

Populating the vector store creates a table in the Oracle Database that contains the generated embeddings. You can create multiple vector stores from the same set of documents to experiment with different chunk sizes, distance metrics, or embedding models, and evaluate them independently.

### Embedding Configuration

Select one of the available **Embedding Models** from the list. The available options depend on the models configured in the **Configuration / Models** section. Once a model is selected, the associated **Embedding Server URL** is displayed.

The **Chunk Size (tokens)** and the **Chunk Overlap (% of chunk size)** are automatically adjusted based on the selected embedding model.

Next, select one of the supported **Distance Metrics** provided by Oracle AI Database 26ai:

* COSINE
* EUCLIDEAN_DISTANCE
* DOT_PRODUCT

To understand the meaning of these metrics, please refer to the doc [Vector Distance Metrics](https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/vector-distance-metrics.html) in the Oracle AI Database 26ai "*AI Vector Search User's Guide*".

The **Embedding Alias** field allows you to assign a meaningful identifier to the vector store table. This is particularly useful when multiple vector stores share the same combination of embedding model, chunk size, chunk overlap, and distance metric.

The **Description** field allows you to provide additional information about the content stored in the vector store. This description is especially useful when using AutoRAG, as it helps the LLM select the most relevant vector store for a given user query.

### Load and Split Documents

The embedding process is initiated by clicking **Populate Vector Store**. The following input parameters are required:
- **File Source**: specifies the origin of the documents to be embedded. Supported sources include:
    - **OCI**: browse and select multiple documents from Oracle Cloud Infrastructure Object Storage;
    - **Local**: upload multiple documents from the client machine;
    - **Web**: load a single TXT, PDF, or HTML document from a specified URL;
    - **SQL**: define a query against an Oracle Database to extract text from a VARCHAR2 column and embed it row by row. When using this option, the following parameters must be provided:
        - **DB Connection**: a connection string, for example:
        ```CO/Welcome_12345@localhost:1521/FREEPDB1```
        - **SQL**: a query that returns a single text column, for example:
        ```select PRODUCT_NAME from PRODUCTS``` The embedded content is prefixed with the column name to provide additional context during similarity search.


- **Rate Limit (RPM)**: limits the number of embedding requests per minute to prevent exceeding the usage limits of external embedding services.

The **Vector Store** field displays the name of the database table that will be populated, following a naming convention derived from the selected configuration parameters.

## Edit existing Vector Store

If the **Create New Vector Store** option is disabled, you can update an existing vector store instead of creating a new one:

![Edit Store](../images/edit_vector_store.png)

After selecting an existing vector store alias from the **Select Alias** dropdown, the available data source options are the same as those used when creating a new vector store.

The lower section of the interface allows you to:

* Inspect the current contents of the vector store in the **Existing Embeddings** section;
* Update the vector store description;
* Append new content from additional data sources by clicking **Populate Vector Store**.

![Populate Existing Embedding](../images/populate_existing_embedding.png)

This approach allows you to incrementally enrich an existing vector store while preserving previously generated embeddings.