"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore sqlcl fastmcp


def register(mcp):
    """Register the SQLcl MCP Server as Local (via Proxy)"""
    config = {
        "mcpServers": {
            "sqlcl": {
                "command": "sql",
                "args": ["-mcp", "-daemon", "-thin", "-noupdates"],
            }
        }
    }

    # Create a proxy to the configured server (auto-creates ProxyClient)
    mcp_proxy = mcp.as_proxy(config, name="SQLclProxy")
    mcp.mount(mcp_proxy)
