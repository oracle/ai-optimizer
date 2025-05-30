"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

DISABLED!! Due to some models not being able to handle tool calls, this code is not called.  It is
maintained here for future capabilities.  DO NOT DELETE (gotsysdba - 11-Feb-2025)
"""
# spell-checker:ignore selectai

from langchain_core.tools import BaseTool, tool
from langchain_core.runnables import RunnableConfig

import common.logging_config as logging_config
from server.utils.databases import execute_sql

logger = logging_config.logging.getLogger("server.tools.selectai_executor")

# ------------------------------------------------------------------------------
# selectai_tool
# ------------------------------------------------------------------------------
# Executes an Oracle "SelectAI" query using the provided configuration.
#
# - Expects a RunnableConfig object with the following keys:
#     - "profile": the Oracle AI profile to activate for the session.
#     - "query": the AI SQL query to execute (appended to "select ai ").
#     - "configurable": a dictionary containing runtime objects, including:
#         - "db_conn": an open Oracle database connection.
#
# Steps:
# 1. Sets the Oracle AI profile for the session using DBMS_CLOUD_AI.SET_PROFILE.
# 2. Constructs and executes the AI SQL query.
# 3. Fetches all results, returning them as a list of dictionaries (column name to value).
# 4. On error, logs the exception and returns a list with a single error dictionary.
#
# This function is intended to be used as a LangChain tool for AI-driven SQL execution.
# ------------------------------------------------------------------------------


def selectai_tool(
    config: RunnableConfig,
) -> list[dict]:
    """Execute a SelectAI call"""
    logger.info("Starting SelectAI Tool")

    if config["profile"] and config["query"] and config["action"]:
        try:
            # Prepare the SQL statement
            sql = """
                SELECT DBMS_CLOUD_AI.GENERATE(
                    prompt       => :query,
                    profile_name => :profile,
                    action       => :action)
                FROM dual
            """
            binds = {"query": config["query"], "profile": config["profile"], "action": config["action"]}
            # Execute the SQL using the connection
            db_conn = config["configurable"]["db_conn"]
            response = execute_sql(db_conn, sql, binds)
            # Response will be [{sql:, completion}]; return the completion
            logger.debug("SelectAI Responded: %s", response)
            return list(response[0].values())[0]
        except Exception as ex:
            logger.exception("Error in selectai_tool")
            # Return an error in the same format as a result list
            return [{"error": str(ex)}]


selectai_executor: BaseTool = tool(selectai_tool)
selectai_executor.name = "selectai_executor"
