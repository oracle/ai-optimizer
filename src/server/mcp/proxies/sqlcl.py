"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker:ignore sqlcl fastmcp
import os
import shutil
import subprocess

import server.api.core.databases as core_databases
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("mcp.proxies.sqlcl")


def register(mcp):
    """Register the SQLcl MCP Server as Local (via Proxy)"""
    sqlcl_binary = shutil.which("sql")
    if sqlcl_binary:
        config = {
            "mcpServers": {
                "sqlcl": {
                    "command": f"{sqlcl_binary}",
                    "args": ["-mcp", "-daemon", "-thin", "-noupdates"],
                }
            }
        }
        databases = core_databases.get_databases()
        for database in databases:
            env_vars = os.environ.copy()
            if database.config_dir:
                env_vars["TNS_ADMIN"] = database.config_dir
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
                    f"connmgr delete -conn optimizer_{database.name}",
                    f"conn -savepwd -save optimizer_{database.name} -user {database.user} -password {database.password} -url {database.dsn}",
                    "exit",
                ]

                # Send commands joined by newlines
                proc.communicate("\n".join(commands) + "\n")
                logger.info("Established Connection Store for: %s", database.name)
            except subprocess.SubprocessError as ex:
                logger.error("Failed to create connection store: %s", ex)
            except Exception as ex:
                logger.error("Unexpected error creating connection store: %s", ex)
        # Create a proxy to the configured server (auto-creates ProxyClient)
        mcp_proxy = mcp.as_proxy(config, name="SQLclProxy")
        mcp.mount(mcp_proxy)
    else:
        logger.warning("Not enabling SQLcl MCP server, sqlcl not found in PATH.")
