"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v 1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore giskard testset, ollama, testsets, litellm

import json
import pickle
import pandas as pd
from bs4 import BeautifulSoup

from pypdf import PdfReader
from oracledb import Connection
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

from giskard.llm import set_llm_model, set_embedding_model
from giskard.rag import generate_testset, KnowledgeBase, QATestset
from giskard.rag.question_generators import simple_questions, complex_questions

from server.api.util import databases
import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.util.testbed")


def jsonl_to_json_content(content: str) -> json:
    """Convert JSONL content to JSON,"""
    # If the content is in bytes, decode it to a string
    if isinstance(content, bytes):
        content = content.decode("utf-8")

    try:
        parsed_data = json.loads(content)
        return json.dumps(parsed_data)
    except json.JSONDecodeError:
        lines = content.strip().split("\n")

    try:
        parsed_lines = [json.loads(line) for line in lines]
        # If only one JSON object, return it as a dict
        if len(parsed_lines) == 1:
            return json.dumps(parsed_lines[0])
        return json.dumps(parsed_lines)
    except json.JSONDecodeError as ex:
        raise ValueError("Invalid JSONL content") from ex


def create_testset_objects(db_conn: Connection) -> None:
    """Create table to store Q&A from TestSets"""
    testsets_tbl = """
            CREATE TABLE IF NOT EXISTS oai_testsets (
                tid     RAW(16) DEFAULT SYS_GUID(),
                name    VARCHAR2(255) NOT NULL,
                created TIMESTAMP(9) WITH LOCAL TIME ZONE,
                CONSTRAINT oai_testsets_pk PRIMARY KEY (tid),
                CONSTRAINT oai_testsets_uq UNIQUE (name, created)
            )
        """
    testset_qa_tbl = """
            CREATE TABLE IF NOT EXISTS oai_testset_qa (
                tid      RAW(16) DEFAULT SYS_GUID(),
                qa_data  JSON,
                CONSTRAINT oai_testset_qa_fk FOREIGN KEY (tid)
                    REFERENCES oai_testsets(tid) ON DELETE CASCADE
            )
        """
    evaluation_tbl = """
            CREATE TABLE IF NOT EXISTS oai_evaluations (
                eid                 RAW(16) DEFAULT SYS_GUID(),
                tid                 RAW(16) DEFAULT SYS_GUID(),
                evaluated           TIMESTAMP(9) WITH LOCAL TIME ZONE,
                correctness         NUMBER DEFAULT 0,
                settings            JSON,
                rag_report          BLOB,
                CONSTRAINT oai_evaluations_pk PRIMARY KEY (eid),
                CONSTRAINT oai_evaluations_fk FOREIGN KEY (tid)
                    REFERENCES oai_testsets(tid) ON DELETE CASCADE,
                CONSTRAINT oai_evaluations_uq UNIQUE (eid, evaluated)
            )
        """
    logger.info("Creating testsets Table")
    _ = databases.execute_sql(db_conn, testsets_tbl)
    logger.info("Creating testset_qa Table")
    _ = databases.execute_sql(db_conn, testset_qa_tbl)
    logger.info("Creating evaluations Table")
    _ = databases.execute_sql(db_conn, evaluation_tbl)


def get_testsets(db_conn: Connection) -> list:
    """Get list of TestSets"""
    logger.info("Getting All TestSets")
    testsets = []
    sql = "SELECT tid, name, to_char(created) FROM oai_testsets ORDER BY created"
    results = databases.execute_sql(db_conn, sql)
    try:
        testsets = [schema.TestSets(tid=tid.hex(), name=name, created=created) for tid, name, created in results]
    except TypeError:
        create_testset_objects(db_conn)

    return testsets


def get_testset_qa(db_conn: Connection, tid: schema.TestSetsIdType) -> schema.TestSetQA:
    """Get list of TestSet Q&A"""
    logger.info("Getting TestSet Q&A for TID: %s", tid)
    binds = {"tid": tid}
    sql = "SELECT qa_data FROM oai_testset_qa where tid=:tid"
    results = databases.execute_sql(db_conn, sql, binds)
    qa_data = [qa_data[0] for qa_data in results]

    return schema.TestSetQA(qa_data=qa_data)


def get_evaluations(db_conn: Connection, tid: schema.TestSetsIdType) -> list[schema.Evaluation]:
    """Get list of Evaluations for a TID"""
    logger.info("Getting Evaluations for: %s", tid)
    evaluations = []
    binds = {"tid": tid}
    sql = "SELECT eid, to_char(evaluated), correctness FROM oai_evaluations WHERE tid=:tid ORDER BY evaluated DESC"
    results = databases.execute_sql(db_conn, sql, binds)
    try:
        evaluations = [
            schema.Evaluation(eid=eid.hex(), evaluated=evaluated, correctness=correctness)
            for eid, evaluated, correctness in results
        ]
    except TypeError:
        create_testset_objects(db_conn)

    return evaluations


def delete_qa(
    db_conn: Connection,
    tid: schema.TestSetsIdType,
) -> None:
    """Delete Q&A"""
    binds = {"tid": tid}
    sql = "DELETE FROM oai_testsets WHERE TID = :tid"
    databases.execute_sql(db_conn, sql, binds)
    db_conn.commit()


def upsert_qa(
    db_conn: Connection,
    name: schema.TestSetsNameType,
    created: schema.TestSetDateType,
    json_data: json,
    tid: schema.TestSetsIdType = None,
) -> schema.TestSetsIdType:
    """Upsert Q&A"""
    logger.info("Upsert TestSet: %s - %s", name, created)
    parsed_data = json.loads(json_data)
    # Handle single QA
    if not isinstance(parsed_data, list):
        parsed_data = [parsed_data]
    json_data = json.dumps(parsed_data) if isinstance(parsed_data, list) else json_data
    binds = {"name": name, "created": created, "json_array": json_data, "tid": tid}
    plsql = """
        DECLARE
            l_tid      oai_testsets.tid%TYPE := :tid;
            l_name     oai_testsets.name%TYPE := :name;
            l_created  oai_testsets.created%TYPE := TO_TIMESTAMP(:created ,'YYYY-MM-DD"T"HH24:MI:SS.FF');
            l_qa_array JSON_ARRAY_T := JSON_ARRAY_T(:json_array);
            l_qa_obj   JSON_OBJECT_T;
            l_qa_str   VARCHAR2(32000);
        BEGIN
            BEGIN
                IF l_tid is NULL THEN
                    SELECT tid into l_tid
                    FROM oai_testsets
                    WHERE created = l_created
                    AND name = l_name;
                ELSE
                    UPDATE oai_testsets SET name = l_name WHERE tid = l_tid;
                END IF;
                DELETE FROM oai_testset_qa WHERE tid = l_tid;
            EXCEPTION WHEN NO_DATA_FOUND THEN
                INSERT INTO oai_testsets (name, created) VALUES (l_name, l_created)
                RETURNING tid INTO l_tid;
            END;
            FOR i IN 0 .. l_qa_array.get_size - 1
            LOOP
                l_qa_obj := TREAT(l_qa_array.get(i) AS json_object_t);
                l_qa_str := l_qa_obj.stringify(); -- Using due to DB Bug
                INSERT INTO oai_testset_qa (tid, qa_data) VALUES (l_tid, l_qa_str);
            END LOOP;
            DBMS_OUTPUT.PUT_LINE(l_tid);
        END;
    """
    logger.debug("Upsert PLSQL: %s", plsql)
    return databases.execute_sql(db_conn, plsql, binds)


def insert_evaluation(db_conn, tid, evaluated, correctness, settings, rag_report):
    """Insert Evaluation Data"""
    logger.info("Insert evaluation; TID: %s", tid)
    binds = {
        "tid": tid,
        "evaluated": evaluated,
        "correctness": correctness,
        "settings": settings,
        "rag_report": rag_report,
    }
    plsql = """
        DECLARE
            l_eid       oai_evaluations.eid%TYPE;
            l_evaluated oai_evaluations.evaluated%TYPE := TO_TIMESTAMP(:evaluated ,'YYYY-MM-DD"T"HH24:MI:SS.FF');
        BEGIN
            INSERT INTO oai_evaluations (
                tid, evaluated, correctness, settings, rag_report)
            VALUES (
                :tid, l_evaluated, :correctness, :settings, :rag_report)
            RETURNING eid INTO l_eid;
            DBMS_OUTPUT.PUT_LINE(l_eid);
        END;
    """
    logger.debug("Insert PLSQL: %s", plsql)
    return databases.execute_sql(db_conn, plsql, binds)


def load_and_split(eval_file, chunk_size=2048):
    """Load and Split Document for Testbed"""
    logger.info("Loading %s; Chunk Size: %i", eval_file, chunk_size)
    loader = PdfReader(eval_file)
    documents = []
    for page in loader.pages:
        document = Document(text=page.extract_text())
        documents.append(document)
    splitter = SentenceSplitter(chunk_size=chunk_size)
    text_nodes = splitter(documents)

    return text_nodes


def build_knowledge_base(text_nodes: str, questions: int, ll_model: schema.Model, embed_model: schema.Model) -> QATestset:
    """Establish a temporary Knowledge Base"""

    def configure_and_set_model(client_model):
        """Configure and set Model for TestSet Generation (uses litellm)"""
        model_name, disable_structured_output, params = None, False, None
        if client_model.api in ("CompatOpenAI", "CompatOpenAIEmbeddings"):
            model_name, params = (
                f"openai/{client_model.name}",
                {"api_base": client_model.url, "api_key": client_model.api_key or "api_compat"},
            )
        elif client_model.api in ("ChatOllama", "OllamaEmbeddings"):
            model_name, disable_structured_output, params = (
                f"ollama/{client_model.name}",
                True,
                {"api_base": client_model.url},
            )
        elif client_model.api == "Perplexity":
            model_name, params = f"perplexity/{client_model.name}", {"api_key": client_model.api_key}
        else:
            model_name, params = f"openai/{client_model.name}", {"api_key": client_model.api_key}

        if client_model.type == "ll":
            logger.debug("KnowledgeBase LL: %s (%s)", model_name, params)
            set_llm_model(model_name, disable_structured_output, **params)
        else:
            logger.debug("KnowledgeBase Embed: %s (%s)", model_name, params)
            set_embedding_model(model_name, **params)

    logger.info("KnowledgeBase creation starting...")
    logger.info("LL Model: %s; Embedding: %s", ll_model, embed_model)
    configure_and_set_model(ll_model)
    configure_and_set_model(embed_model)

    knowledge_base_df = pd.DataFrame([node.text for node in text_nodes], columns=["text"])
    knowledge_base = KnowledgeBase(data=knowledge_base_df)
    logger.info("KnowledgeBase Created")

    logger.info("TestSet from Knowledge Base starting...")
    testset = generate_testset(
        knowledge_base,
        question_generators=[
            simple_questions,
            complex_questions,
        ],
        num_questions=questions,
        agent_description="A chatbot answering questions based on the provided knowledge base",
    )
    logger.info("Test Set from Knowledge Base Generated")

    return testset


def process_report(db_conn: Connection, eid: schema.TestSetsIdType) -> schema.EvaluationReport:
    """Process an evaluate report"""

    def clean(orig_html):
        """Remove elements from html output"""
        soup = BeautifulSoup(orig_html, "html.parser")
        titles_to_remove = [
            "GENERATOR",
            "RETRIEVER",
            "REWRITER",
            "ROUTING",
            "KNOWLEDGE_BASE",
            "KNOWLEDGE BASE OVERVIEW",
        ]
        for title in titles_to_remove:
            component_cards = soup.find_all("div", class_="component-card")
            for card in component_cards:
                title_element = card.find("div", class_="component-title")
                if title_element and title in title_element.text.strip().upper():
                    card.decompose()

        return soup.prettify()

    # Main
    binds = {"eid": eid}
    sql = """
        SELECT eid, to_char(evaluated) as evaluated, correctness, settings, rag_report
          FROM oai_evaluations WHERE eid=:eid
         ORDER BY evaluated
        """
    results = databases.execute_sql(db_conn, sql, binds)
    report = pickle.loads(results[0]["RAG_REPORT"])
    full_report = report.to_pandas()
    html_report = report.to_html()
    by_topic = report.correctness_by_topic()
    failures = report.failures

    evaluation_results = {
        "eid": results[0]["EID"].hex(),
        "evaluated": results[0]["EVALUATED"],
        "correctness": results[0]["CORRECTNESS"],
        "settings": results[0]["SETTINGS"],
        "report": full_report.to_dict(),
        "correct_by_topic": by_topic.to_dict(),
        "failures": failures.to_dict(),
        "html_report": clean(html_report),
    }
    logger.debug("Evaluation Results: %s", evaluation_results)
    evaluation = schema.EvaluationReport(**evaluation_results)

    return evaluation
