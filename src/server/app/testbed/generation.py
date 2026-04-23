"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Testset generation from PDF files using Giskard knowledge base.
"""
# spell-checker:ignore giskard testset litellm

import asyncio
import json
import logging

import pandas as pd
from giskard.llm import set_embedding_model, set_llm_model
from giskard.rag import KnowledgeBase, generate_testset
from giskard.rag.question_generators import complex_questions, simple_questions
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from pypdf import PdfReader

LOGGER = logging.getLogger(__name__)

# Serialize Giskard operations that set global LLM state
_GISKARD_LOCK = asyncio.Lock()

# Minimum chunks per PDF required for Giskard's KnowledgeBase. Below this, UMAP's
# spectral init calls scipy eigsh with k >= N and raises. 10 gives margin over
# the hard scipy floor while still admitting modestly sized documents.
MIN_CHUNKS_PER_FILE = 10


def jsonl_to_json_content(content: str | bytes) -> str:
    """Convert JSONL or JSON content to a valid JSON string."""
    if isinstance(content, bytes):
        content = content.decode("utf-8")

    try:
        parsed_data = json.loads(content)
        return json.dumps(parsed_data)
    except json.JSONDecodeError:
        lines = content.strip().split("\n")

    try:
        parsed_lines = [json.loads(line) for line in lines]
        if len(parsed_lines) == 1:
            return json.dumps(parsed_lines[0])
        return json.dumps(parsed_lines)
    except json.JSONDecodeError as ex:
        raise ValueError("Invalid JSONL content") from ex


def get_giskard_config(litellm_config: dict, model_type: str) -> dict:
    """Adapt a LiteLlmModelSpec.to_litellm_kwargs() result for Giskard's set_llm_model/set_embedding_model.

    Giskard expects ``llm_model`` instead of ``model`` for LL models, and does not
    accept ``temperature``/``max_tokens`` kwargs.
    """
    config = dict(litellm_config)
    if model_type == "ll":
        config["llm_model"] = config.pop("model", None)
    config.pop("temperature", None)
    config.pop("max_tokens", None)
    return config


def load_and_split(eval_file, chunk_size=512):
    """Load a PDF and split into text nodes."""
    chunk_overlap = int(chunk_size * 0.10)
    effective_chunk_size = chunk_size - chunk_overlap
    LOGGER.info("Loading %s; Chunk Size: %i; Overlap: %i", eval_file, effective_chunk_size, chunk_overlap)
    loader = PdfReader(eval_file)
    documents = []
    for page in loader.pages:
        document = Document(text=page.extract_text())
        documents.append(document)
    splitter = SentenceSplitter(chunk_size=effective_chunk_size, chunk_overlap=chunk_overlap)
    text_nodes = splitter(documents)

    return text_nodes


def build_knowledge_base(text_nodes, questions: int, ll_model_config: dict, embed_model_config: dict):
    """Generate a QA testset from text nodes using Giskard.

    This function sets global Giskard LLM/embedding state and must be called
    under ``_GISKARD_LOCK`` when used from async code.
    """
    LOGGER.info("KnowledgeBase creation starting...")

    set_llm_model(**ll_model_config)
    set_embedding_model(**embed_model_config)

    knowledge_base_df = pd.DataFrame([node.text for node in text_nodes], columns=["text"])
    knowledge_base = KnowledgeBase(data=knowledge_base_df)
    LOGGER.info("KnowledgeBase Created")

    LOGGER.info("TestSet from Knowledge Base starting...")
    testset = generate_testset(
        knowledge_base,
        question_generators=[
            simple_questions,
            complex_questions,
        ],
        num_questions=questions,
        agent_description="A chatbot answering questions based on the provided knowledge base",
    )
    LOGGER.info("Test Set from Knowledge Base Generated")

    return testset
