"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore sqlcl fastmcp connmgr noupdates savepwd

import os
import shutil
import subprocess

import server.api.utils.databases as utils_databases

from common import logging_config
from fastmcp import Client

logger = logging_config.logging.getLogger("mcp.proxies.sqlcl")


async def register(mcp):
    """Register the SQLcl MCP Server as Local (via Proxy)"""
    tool_name = "SQLclProxy"

    sqlcl_binary = shutil.which("sql")
    if sqlcl_binary:
        env_vars = os.environ.copy()
        env_vars["TNS_ADMIN"] = os.getenv("TNS_ADMIN", "tns_admin")
        config = {
            "mcpServers": {
                tool_name: {
                    "name": tool_name,
                    "command": f"{sqlcl_binary}",
                    "args": ["-mcp", "-daemon=start", "-thin", "-noupdates"],
                    "env": env_vars,
                }
            }
        }
        databases = utils_databases.get_databases(validate=False)
        for database in databases:
            # Start sql in no-login mode
            try:
                proc = subprocess.Popen(
                    [sqlcl_binary, "/nolog"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env_vars,
                )

                # Prepare commands: connect, then exit
                commands = [
                    f"connmgr delete -conn OPTIMIZER_{database.name}",
                    (
                        f"conn -savepwd -save OPTIMIZER_{database.name} "
                        f"-user {database.user} -password {database.password} "
                        f"-url {database.dsn}"
                    ),
                    "exit",
                ]

                # Send commands joined by newlines
                proc.communicate("\n".join(commands) + "\n")
                logger.info("Established Connection Store for: %s", database.name)
            except subprocess.SubprocessError as ex:
                logger.error("Failed to create connection store: %s", ex)
            except Exception as ex:
                logger.error("Unexpected error creating connection store: %s", ex)

        # Create a client with disabled sampling capabilities for compatibility with older MCP servers
        client = Client(
            transport=config,
            sampling_capabilities=None,
        )

        # Create a proxy to the configured server
        proxy = mcp.as_proxy(client, name=tool_name)
        mcp.mount(proxy, as_proxy=False, prefix="sqlcl")
    else:
        logger.warning("Not enabling SQLcl MCP server, sqlcl not found in PATH.")
