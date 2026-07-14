+++
title = "🔗 MCP Server"
weight = 50
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore tablespace mycomplexsecret mycomplexwalletsecret sqlcl streamable
-->

The {{% full_app_ref %}} exposes a built-in [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server using [FastMCP](https://github.com/PrefectHQ/fastmcp). At startup, the server automatically registers tools, prompts, and any configured proxy servers (such as SQLcl for NL2SQL).

## MCP Configuration Page

The MCP Configuration page displays:

- **Server Health**: Connection status, server name, and version
- **Client Configuration**: JSON configuration block for connecting external MCP clients
- **Registered Servers**: Dropdown to select between registered MCP server namespaces
- **Tools, Prompts, and Resources**: Details for each registered item, including input schemas and descriptions

## Connecting External MCP Clients

The {{% short_app_ref %}} MCP server can be consumed by external MCP clients such as Claude Desktop, Claude Code, VS Code Copilot, or Cursor.

![MCP Client Config](../images/mcp_client_config.png)

Use the client configuration from the MCP Configuration page to configure your client. The configuration provides the Streamable-HTTP URL and the required API key header.

For developing custom MCP tools, see [Custom MCP Tools](/advanced/mcp/).

---

## SQLcl MCP Server (NL2SQL)

The {{% short_app_ref %}} natively supports the [Oracle SQLcl MCP Server](https://docs.oracle.com/en/database/oracle/sql-developer-command-line/25.2/sqcug/using-oracle-sqlcl-mcp-server.html) for Natural Language to SQL (NL2SQL) capabilities. When SQLcl is available and databases are configured, the SQLcl MCP server is **automatically registered** at startup as a proxy under the `sqlcl` namespace.

### Requirements

1. **SQLcl must be installed** and the `sql` binary must be on the system `PATH`
2. At least one [database](databases/) must be configured with valid credentials (username, password, and DSN)

### SQLcl Installation

{{< tabs "sqlcl-installation" >}}
{{% tab title="Containers" %}}
The project's all-in-one image (`src/Dockerfile`) and server image (`src/server/Dockerfile`) already include SQLcl and Java. No additional SQLcl installation is required in the container or on the container host.
{{% /tab %}}
{{% tab title="macOS" %}}
When running the {{% short_app_ref %}} directly on macOS, install a supported Java runtime and the [SQLcl Homebrew cask](https://formulae.brew.sh/cask/sqlcl):

```bash
brew install --cask temurin@21
brew install --cask sqlcl
```

Add the following lines to `~/.zshrc` so SQLcl can find Java and the {{% short_app_ref %}} can find the `sql` binary when started from an interactive shell. The SQLcl path is resolved from the currently installed cask version:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export PATH="$(brew --prefix)/Caskroom/sqlcl/$(brew list --versions --cask sqlcl | awk '{print $2}')/sqlcl/bin:$PATH"
```

Open a new terminal, activate the project environment, and verify the installation:

```bash
source .venv/bin/activate
java -version
sql -version
```

Start or restart the {{% short_app_ref %}} from an environment that inherits this `PATH`.
{{% /tab %}}
{{< /tabs >}}

### How It Works

At startup, the {{% short_app_ref %}}:

1. Discovers the `sql` binary on the system path
2. Creates connection store entries for each configured database
3. Launches SQLcl as a child process using stdio transport
4. Mounts the SQLcl MCP server as a proxy, making NL2SQL tools available alongside the built-in tools

### SQLcl Home Directory

By default, the SQLcl connection store is created in a temporary directory. To override this location, set [`AIO_SQLCL_HOME`]({{% relref "/configuration#nl2sql" %}}):

```bash
export AIO_SQLCL_HOME=/path/to/sqlcl/home
```

{{% notice style="code" title="SQLcl Not Found?" icon="circle-info" %}}
If SQLcl is not installed or the `sql` binary is not on the system path, the NL2SQL functionality will be unavailable. The {{% short_app_ref %}} will log a warning and continue without it.
{{% /notice %}}
