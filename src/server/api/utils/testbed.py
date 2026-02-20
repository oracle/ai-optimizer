"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v 1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore giskard testset ollama testsets litellm

import logging
import json
import pickle
import pandas as pd

from pypdf import PdfReader
from oracledb import Connection
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

from giskard.llm import set_llm_model, set_embedding_model
from giskard.rag import generate_testset, KnowledgeBase, QATestset
from giskard.rag.question_generators import simple_questions, complex_questions

import server.api.utils.databases as utils_databases

from common import schema


LOGGER = logging.getLogger("api.utils.testbed")


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
    LOGGER.info("Creating testsets Table")
    _ = utils_databases.execute_sql(db_conn, testsets_tbl)
    LOGGER.info("Creating testset_qa Table")
    _ = utils_databases.execute_sql(db_conn, testset_qa_tbl)
    LOGGER.info("Creating evaluations Table")
    _ = utils_databases.execute_sql(db_conn, evaluation_tbl)


def get_testsets(db_conn: Connection) -> list:
    """Get list of TestSets"""
    LOGGER.info("Getting All TestSets")
    testsets = []
    sql = "SELECT tid, name, to_char(created) FROM oai_testsets ORDER BY created"
    results = utils_databases.execute_sql(db_conn, sql)
    try:
        testsets = [schema.QASets(tid=tid.hex(), name=name, created=created) for tid, name, created in results]
    except TypeError:
        create_testset_objects(db_conn)

    return testsets


def get_testset_qa(db_conn: Connection, tid: schema.QASetsIdType) -> schema.QASetData:
    """Get list of TestSet Q&A"""
    LOGGER.info("Getting TestSet Q&A for TID: %s", tid)
    binds = {"tid": tid}
    sql = "SELECT qa_data FROM oai_testset_qa where tid=:tid"
    results = utils_databases.execute_sql(db_conn, sql, binds)
    qa_data = [qa_data[0] for qa_data in results]

    return schema.QASetData(qa_data=qa_data)


def get_evaluations(db_conn: Connection, tid: schema.QASetsIdType) -> list[schema.Evaluation]:
    """Get list of Evaluations for a TID"""
    LOGGER.info("Getting Evaluations for: %s", tid)
    evaluations = []
    binds = {"tid": tid}
    sql = "SELECT eid, to_char(evaluated), correctness FROM oai_evaluations WHERE tid=:tid ORDER BY evaluated DESC"
    results = utils_databases.execute_sql(db_conn, sql, binds)
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
    tid: schema.QASetsIdType,
) -> None:
    """Delete Q&A"""
    binds = {"tid": tid}
    sql = "DELETE FROM oai_testsets WHERE TID = :tid"
    utils_databases.execute_sql(db_conn, sql, binds)
    db_conn.commit()


def upsert_qa(
    db_conn: Connection,
    name: schema.QASetsNameType,
    created: schema.QASetsDateType,
    json_data: json,
    tid: schema.QASetsIdType = None,
) -> schema.QASetsIdType:
    """Upsert Q&A"""
    LOGGER.info("Upsert TestSet: %s - %s", name, created)
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
    LOGGER.debug("Upsert PLSQL: %s", plsql)
    return utils_databases.execute_sql(db_conn, plsql, binds)


def insert_evaluation(db_conn, tid, evaluated, correctness, settings, rag_report):
    """Insert Evaluation Data"""
    LOGGER.info("Insert evaluation; TID: %s", tid)
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
    LOGGER.debug("Insert PLSQL: %s", plsql)
    return utils_databases.execute_sql(db_conn, plsql, binds)


def load_and_split(eval_file, chunk_size=512):
    """Load and Split Document for Testbed"""
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


def build_knowledge_base(
    text_nodes: str, questions: int, ll_model_config: dict, embed_model_config: dict
) -> QATestset:
    """Establish a temporary Knowledge Base"""
    LOGGER.info("KnowledgeBase creation starting...")

    # Setup models, uses LiteLLM
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


def process_report(db_conn: Connection, eid: schema.QASetsIdType) -> schema.EvaluationReport:
    """Process an evaluate report"""

    # Main
    binds = {"eid": eid}
    sql = """
        SELECT eid, to_char(evaluated) as evaluated, correctness, settings, rag_report
          FROM oai_evaluations WHERE eid=:eid
         ORDER BY evaluated
        """
    results = utils_databases.execute_sql(db_conn, sql, binds)
    report = pickle.loads(results[0]["RAG_REPORT"])
    full_report = report.to_pandas()
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
        # "html_report": clean(html_report), #CDB
        "html_report": "<html><body></body></html>",
    }
    LOGGER.debug("Evaluation Results: %s", evaluation_results)
    evaluation = schema.EvaluationReport(**evaluation_results)

    return evaluation
