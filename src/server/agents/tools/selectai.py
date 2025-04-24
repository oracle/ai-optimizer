
from typing import Annotated

from langchain_core.tools import BaseTool, tool
from langchain_core.runnables import RunnableConfig

from langgraph.prebuilt import InjectedState

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.tools.selectai_executor")

def selectai_tool(
    state: Annotated[dict, InjectedState],
    config: RunnableConfig,
) -> list[dict]:
    """Execute a SelectAI call"""
    logger.info("Starting SelectAI Tool")

    if config["profile"] and config["query"]:
        try:
            # Retrieve the existing Oracle DB connection from config
            logger.info("Connecting to VectorStore")
            db_conn = config["configurable"]["db_conn"] 

            # Get the profile string from config
            profile = config["profile"]
            logger.info(f"Using profile: {profile}")
            # Prepare the SQL statement
            setprofile = f"BEGIN DBMS_CLOUD_AI.SET_PROFILE(profile_name => '{profile}'); END;"

            # Execute the SQL using the connection
            with db_conn.cursor() as cursor:
                cursor.execute(setprofile)
                db_conn.commit()

            # Append config["query"] to the base string
            sql = "select ai " + config["query"]

            logger.info(f"Running query: {sql}")

            # Execute the SQL and fetch results as list[dict]
            with db_conn.cursor() as cursor:
                cursor.execute(sql)
                columns = [col[0] for col in cursor.description]  # Get column names
                results = [
                    dict(zip(columns, row))
                    for row in cursor.fetchall()
                ]

            # Now results is a list of dictionarie
            return results
        except Exception as ex:
            logger.exception("Error in selectai_tool")
            # Return an error in the same format as a result list
            return [{"error": str(ex)}]        


selectai_executor: BaseTool = tool(selectai_tool)
selectai_executor.name = "selectai_executor"