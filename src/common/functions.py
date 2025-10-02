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

import oracledb
import pyarrow
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
        table_string = (
            f"{model}_{chunk_size}_{chunk_overlap_ceil}_{distance_metric}_{index_type}"
        )
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


def is_sql_accessible(db_conn: str, query: str) -> tuple[bool, str]:
    """Check if the DB connection and SQL is working one field."""
    try:  # Establish a connection

        username = ""
        password = ""
        dsn = ""

        ok = True
        return_msg=""

        if db_conn and query:
            try:
                user_part, dsn = db_conn.split("@")
                username, password = user_part.split("/")
            except ValueError:
                return_msg=f"Wrong connection string {db_conn}"
                logger.error(return_msg)
                return False,return_msg

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
                        return_msg=f"SQL source returns {len(desc)} columns, expected 1."
                        logger.error(return_msg)
                        ok = False

                    if rows and len(desc) != 1:
                        col_type = desc[0].FetchInfo.type
                        if col_type not in (oracledb.DB_TYPE_VARCHAR, oracledb.DB_TYPE_NVARCHAR):
                        # to be implemented: oracledb.DB_TYPE_BLOB, oracledb.DB_TYPE_CLOB, oracledb.DB_TYPE_NCLOB
                            return_msg=f"SQL source returns column of type %{col_type} , expected VARCHAR or BLOB."
                            logger.error(return_msg)
        else:
            ok = False

        return not(ok),return_msg

    except oracledb.Error as e:
        return_msg=f"SQL source connection error:{e}"
        logger.error(return_msg)
        return False,return_msg


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
        with oracledb.connect(user=username, password=password, dsn=dsn) as connection:
            connection = oracledb.connect(user=username, password=password, dsn=dsn)
            for odf in connection.fetch_df_batches(statement=query, size=batch_size):
                df = pyarrow.table(odf).to_pandas()

            full_file_path = os.path.join(base_path, filename_with_extension)

            df.to_csv(full_file_path, index=False)

        return full_file_path

    except oracledb.Error as e:
        logger.error("SQL source connection error: %s", e)
        return ""
