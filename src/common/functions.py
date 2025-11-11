"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker:ignore genai hnsw

from typing import Tuple
import math
import re
import uuid
import os
import csv

import oracledb
import requests


from common import logging_config

logger = logging_config.logging.getLogger("common.functions")


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
        store_comment = (
            f'{{"alias": "{alias}",'
            f'"model": "{model}",'
            f'"chunk_size": {chunk_size},'
            f'"chunk_overlap": {chunk_overlap_ceil},'
            f'"distance_metric": "{distance_metric}",'
            f'"index_type": "{index_type}"}}'
        )
        logger.debug("Vector Store Table: %s; Comment: %s", store_table, store_comment)
    except TypeError:
        logger.fatal("Not all required values provided to get Vector Store Table name.")
    return store_table, store_comment


def parse_vs_table(table_name: str) -> dict[str, str]:
    """
    Parse structured vector table name format (inverse of get_vs_table).
    Format: [alias_]<embedding_model>_<chunk_size>_<overlap>_<distance_metric>_<index_type>
    """
    try:
        parts = table_name.split("_")

        if len(parts) < 5:
            return {
                "alias": None,
                "embedding_model": table_name,
                "chunk_size": "UNKNOWN",
                "overlap": "UNKNOWN",
                "distance_metric": "UNKNOWN",
                "index_type": "UNKNOWN",
                "parse_status": "insufficient_parts",
            }

        # Last 4 parts are always: chunk_size, overlap, distance_metric, index_type
        index_type = parts[-1]
        distance_metric = parts[-2]
        overlap = parts[-3]
        chunk_size = parts[-4]

        # Everything else is model (and possibly alias)
        model_parts = parts[:-4]

        if len(model_parts) == 1:
            alias = None
            embedding_model = model_parts[0]
        else:
            alias = model_parts[0]
            embedding_model = "_".join(model_parts[1:])

        return {
            "alias": alias,
            "embedding_model": embedding_model,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "distance_metric": distance_metric,
            "index_type": index_type,
            "parse_status": "success",
        }

    except (ValueError, IndexError, AttributeError, TypeError) as ex:
        logger.warning("Failed to parse table name '%s': %s", table_name, ex)
        return {
            "alias": None,
            "embedding_model": table_name,
            "chunk_size": "UNKNOWN",
            "overlap": "UNKNOWN",
            "distance_metric": "UNKNOWN",
            "index_type": "UNKNOWN",
            "parse_status": f"parse_error: {str(ex)}",
        }


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
