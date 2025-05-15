"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore rerank, mult, HNSW

help_dict = {
    "context_length": """
        Maximum number of tokens (words, sub-words, or characters) the model can consider
        at once when generating a response.   It defines how much prior conversation or text
        the model "remembers" within a single interaction.
        Value often determined from the model card.
        """,
    "temperature": """
        Controls how creative the responses are.
        A higher temperature results in more creative and varied answers, while a lower
        temperature produces more focused and predictable ones.  It is generally
        recommended altering this or Top P but not both.
        Default value often determined from the model card.
        """,
    "max_completion_tokens": """
        Sets the maximum length of the response.
        The higher the number, the longer the potential response, but it won't exceed this
        limit.  Max value often determined from the model card.
        """,
    "top_p": """
        Limits the choice of words to the most likely ones.
        Setting a lower Top P uses only the most probable words, creating safer and more
        straightforward responses.  Higher Top P allows for more diverse and creative
        word choices in the response.  It is generally recommended altering this or
        Temperature but not both.
        """,
    "frequency_penalty": """
        Discourages repeating the same words or phrases in the response.
        A higher frequency penalty makes repetition less likely, promoting more varied
        language in the response.  Default value often determined from the model card.
        """,
    "presence_penalty": """
        Encourages the introduction of new topics or ideas in the response.
        A higher presence penalty makes bringing up new subjects more likely rather than
        sticking to what has already been mentioned.
        """,
    "selectai": """
        Enable SelectAI Generation.
        """,
    "rag": """
        Enable Retrieval-Augmented Generation.
        """,
    "rerank": """
        Organize the initially fetched documents based on their relevance to the question.
        Re-ranking ensures that the most relevant documents are prioritized for response
        generation, improving the quality and accuracy of the final answer.
        """,
    "top_k": """
        The number of retrieved documents or passages that are used to enhance the generation
        of text.  For example, if set to 3, 3 of the most relevant documents based on the input
        query will be used to augment the response.  Often set based on the desired trade-off
        between computational efficiency and quality of generated responses.
        """,
    "score_threshold": """
        The minimum similarity score required for a result to be considered relevant.
        It ensures that only items with a similarity score above this threshold are included
        in the results, filtering out those with insufficient relevance.
        """,
    "fetch_k": """
        The number of documents initially fetched from the knowledge base before any
        further filtering (e.g., Top K) or re-ranking is done. Fetching more documents
        (higher Fetch K) increases the initial computational load but provides more
        material to ensure the most relevant information is considered in the final step.
        """,
    "lambda_mult": """
        A higher degree of diversity ensures that the documents cover a wider range of
        topics and perspectives, reducing redundancy. This helps in providing a more
        comprehensive and varied set of information for generating the final response.
        """,
    "embed_alias": """
        Provide an alias to help identify the embedding during RAG experimentation.
        It must start with a character and only contain alphanumerics and underscores.
        Max Characters: 20
        """,
    "chunk_overlap": """
        Defines the amount of consecutive chunks' overlap as percentage of chunk size.
        """,
    "chunk_size": """
        Defines the length of each chunk.  Max value often determined from the model card.
        """,
    "index_type": """
        - HNSW: (Hierarchical Navigable Small Worlds) index. A graph-based index.
        - IVF: (Inverted File) Flat index. A partitioned-based index.
        """,
    "distance_metric": """
        Distance metrics quantify how similar or different two vector representations
        are in a high-dimensional space. These metrics help compare and cluster
        embeddings effectively.
        """,
    "model_name": """
        The official name of the model as per the model card.
        Misconfigured names will result in an error.
        """,
    "model_api": """
        API of the model.  If the API of the model is not listed here, try an OpenAI one.
        Open an issue if you'd like to request support for an unlisted model.
        """,
    "model_api_url": """
        API URL for accessing the model.
        """,
    "model_api_key": """
        API Key for accessing the model.
        Often left blank for on-premises models.
        """,
}
