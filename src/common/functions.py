"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai hnsw

from typing import Optional, Tuple
import math
import re
import uuid
import os
import csv
import json

import oracledb
import requests


from common import logging_config

logger = logging_config.logging.getLogger("common.functions")


#############################################################################
# CPU OPTIMIZATION
#############################################################################
# Pattern to extract parameter count from model names (e.g., "llama3.2:1b" -> 1.0)
PARAM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)[bB](?![a-zA-Z])")
SMALL_MODEL_THRESHOLD_B = 7


def extract_parameter_count(model_id: str) -> Optional[float]:
    """Extract parameter count from model name.

    Parses model identifiers to find parameter counts indicated by patterns
    like '1b', '3B', '7b', etc.

    Args:
        model_id: Model identifier string (e.g., 'llama3.2:1b', 'gemma3:1b')

    Returns:
        Parameter count in billions as a float, or None if not found.

    Examples:
        >>> extract_parameter_count("llama3.2:1b")
        1.0
        >>> extract_parameter_count("phi4-mini:3.8b")
        3.8
        >>> extract_parameter_count("gpt-4o")
        None
    """
    if not model_id:
        return None

    match = PARAM_PATTERN.search(model_id)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def is_small_model(model_id: str) -> bool:
    """Check if model is a small model based on parameter count.

    A model is considered "small" if its parameter count can be extracted
    from the model name and is less than SMALL_MODEL_THRESHOLD_B (7B).

    Small models benefit from CPU optimization settings like disabling
    grade and rephrase operations.

    Args:
        model_id: Model identifier string (e.g., 'llama3.2:1b', 'gemma3:1b')

    Returns:
        True if model is <7B parameters, False otherwise.

    Examples:
        >>> is_small_model("llama3.2:1b")
        True
        >>> is_small_model("llama3.1:8b")
        False
        >>> is_small_model("gpt-4o")
        False
    """
    param_count = extract_parameter_count(model_id)
    if param_count is None:
        return False
    return param_count < SMALL_MODEL_THRESHOLD_B


#############################################################################
# CLIENT
#############################################################################
def is_url_accessible(url: str) -> Tuple[bool, str]:
    """Check if the URL is accessible."""
    if not url:
        return False, "No URL Provided"
    logger.debug("Checking if %s is accessible", url)

    is_accessible = False
    err_msg = None

    try:
        response = requests.get(url, timeout=2)
        logger.info("Response for %s: %s", url, response.status_code)

        if response.status_code in {200, 403, 404, 421}:
            is_accessible = True
        else:
            err_msg = f"{url} is not accessible. (Status: {response.status_code})"
            logger.warning(err_msg)
    except requests.exceptions.RequestException as ex:
        err_msg = f"{url} is not accessible. ({type(ex).__name__})"
        logger.warning(err_msg)
        logger.exception(ex, exc_info=False)

    return is_accessible, err_msg


def get_vs_table(
    model: str,
    chunk_size: int,
    chunk_overlap: int,
    distance_metric: str,
    index_type: str = "HNSW",
    alias: str = None,
    description: str = None,
) -> Tuple[str, str]:
    """Return the concatenated VS Table name and comment"""
    store_table = None
    store_comment = None
    try:
        chunk_overlap_ceil = math.ceil(chunk_overlap)
        table_string = f"{model}_{chunk_size}_{chunk_overlap_ceil}_{distance_metric}_{index_type}"
        if alias:
            table_string = f"{alias}_{table_string}"
        store_table = re.sub(r"\W", "_", table_string.upper())

        # Build comment JSON with optional description
        comment_parts = [
            f'"alias": "{alias}"',
            f'"description": "{description}"' if description else '"description": null',
            f'"model": "{model}"',
            f'"chunk_size": {chunk_size}',
            f'"chunk_overlap": {chunk_overlap_ceil}',
            f'"distance_metric": "{distance_metric}"',
            f'"index_type": "{index_type}"',
        ]
        store_comment = "{" + ", ".join(comment_parts) + "}"

        logger.debug("Vector Store Table: %s; Comment: %s", store_table, store_comment)
    except TypeError:
        logger.fatal("Not all required values provided to get Vector Store Table name.")
    return store_table, store_comment


def parse_vs_comment(comment: str) -> dict:
    """
    Parse table comment JSON to extract vector store metadata.
    Returns dict with keys: alias, description, model, chunk_size, chunk_overlap,
    distance_metric, index_type.
    Handles backward compatibility for comments without description field.
    """

    default_result = {
        "alias": None,
        "description": None,
        "model": None,
        "chunk_size": None,
        "chunk_overlap": None,
        "distance_metric": None,
        "index_type": None,
        "parse_status": "no_comment",
    }

    if not comment:
        return default_result

    try:
        # Strip "GENAI: " prefix if present
        json_str = comment
        if comment.startswith("GENAI: "):
            json_str = comment[7:]  # len("GENAI: ") = 7

        parsed = json.loads(json_str)
        return {
            "alias": parsed.get("alias"),
            "description": parsed.get("description"),  # May be None for backward compat
            "model": parsed.get("model"),
            "chunk_size": parsed.get("chunk_size"),
            "chunk_overlap": parsed.get("chunk_overlap"),
            "distance_metric": parsed.get("distance_metric"),
            "index_type": parsed.get("index_type"),
            "parse_status": "success",
        }
    except (json.JSONDecodeError, AttributeError, TypeError) as ex:
        logger.warning("Failed to parse table comment '%s': %s", comment, ex)
        default_result["parse_status"] = f"parse_error: {str(ex)}"
        return default_result


def is_sql_accessible(db_conn: str, query: str) -> tuple[bool, str]:
    """Check if the DB connection and SQL is working one field."""

    ok = True
    return_msg = ""

    try:  # Establish a connection
        username = ""
        password = ""
        dsn = ""
        if db_conn and query:
            try:
                user_part, dsn = db_conn.split("@")
                username, password = user_part.split("/")
            except ValueError:
                return_msg = f"Wrong connection string {db_conn}"
                logger.error(return_msg)
                ok = False
            with oracledb.connect(user=username, password=password, dsn=dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query)
                    rows = cursor.fetchmany(3)
                    desc = cursor.description
                    if not rows:
                        return_msg = "SQL source return an empty table!"
                        logger.error(return_msg)
                        ok = False
                    if len(desc) != 1:
                        return_msg = f"SQL source returns {len(desc)} columns, expected 1."
                        logger.error(return_msg)
                        ok = False

                    if rows and len(desc) == 1:
                        col_type = desc[0].type

                        if col_type not in (
                            oracledb.DB_TYPE_VARCHAR,
                            oracledb.DB_TYPE_NVARCHAR,
                        ):
                            # to be implemented: oracledb.DB_TYPE_CLOB,oracledb.DB_TYPE_JSON
                            return_msg = f"SQL source returns column of type %{col_type}, expected VARCHAR."
                            logger.error(return_msg)
                            ok = False

        else:
            ok = False
            return_msg = ""

        return ok, return_msg

    except oracledb.Error as e:
        return_msg = f"SQL source connection error:{e}"
        logger.error(return_msg)
        return False, return_msg


def run_sql_query(db_conn: str, query: str, base_path: str) -> str:
    """Save the query result as a CSV file to be embedded"""
    try:  # Establish a connection
        username = ""
        password = ""
        dsn = ""
        batch_size = 100

        if not db_conn:
            return False
        try:
            user_part, dsn = db_conn.split("@")
            username, password = user_part.split("/")
        except ValueError:
            logger.error("Wrong connection string %s", db_conn)
            return False
        random_filename = str(uuid.uuid4())

        filename_with_extension = f"{random_filename}.csv"
        full_file_path = os.path.join(base_path, filename_with_extension)

        with oracledb.connect(user=username, password=password, dsn=dsn) as connection:
            with connection.cursor() as cursor:
                cursor.arraysize = batch_size
                cursor.execute(query)

                # Write header
                desc = cursor.description
                column_names = [d[0] for d in desc]

                with open(full_file_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(column_names)

                    # Fetch and append in batches
                    while True:
                        rows = cursor.fetchmany(batch_size)
                        if not rows:
                            break
                        writer.writerows(rows)

        return full_file_path

    except oracledb.Error as e:
        logger.error("SQL source connection error: %s", e)
        return ""
