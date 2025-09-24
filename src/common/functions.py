"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai, hnsw

from typing import Tuple, Dict
import math
import re

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


def parse_vs_table(table_name: str) -> Dict[str, str]:
    """
    Parse structured vector table name format (inverse of get_vs_table).
    Format: [alias_]<embedding_model>_<chunk_size>_<overlap>_<distance_metric>_<index_type>
    """
    try:
        parts = table_name.split('_')

        if len(parts) < 5:
            return {
                "alias": None,
                "embedding_model": table_name,
                "chunk_size": "UNKNOWN",
                "overlap": "UNKNOWN",
                "distance_metric": "UNKNOWN",
                "index_type": "UNKNOWN",
                "parse_status": "insufficient_parts"
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
            embedding_model = '_'.join(model_parts[1:])

        return {
            "alias": alias,
            "embedding_model": embedding_model,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "distance_metric": distance_metric,
            "index_type": index_type,
            "parse_status": "success"
        }

    except Exception as ex:
        logger.warning("Failed to parse table name '%s': %s", table_name, ex)
        return {
            "alias": None,
            "embedding_model": table_name,
            "chunk_size": "UNKNOWN",
            "overlap": "UNKNOWN",
            "distance_metric": "UNKNOWN",
            "index_type": "UNKNOWN",
            "parse_status": f"parse_error: {str(ex)}"
        }
