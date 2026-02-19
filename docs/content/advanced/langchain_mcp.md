+++
title = 'Export as MCP Langchain server'
weight = 1
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

## Introduction to the MCP Server for a tested AI Optimizer & Toolkit configuration
This document describes how to re-use the configuration tested in the **{{< short_app_ref >}}** and expose it as an MCP tool. The MCP tool can be consumed locally by **Claude Desktop** or deployed as a remote MCP server using the **Python/LangChain** framework. 

This early-stage implementation supports communication via the `stdio` and `sse` transports, enabling interaction between the agent dashboard (for example, Claude Desktop) and the exported RAG tool.

{{% notice style="code" title="NOTICE" icon="circle-info" %}} 
At present, only configurations using `Ollama` or `OpenAI` for both chat and embedding models are supported. Broader provider support will be added in future releases.
{{% /notice %}}

## Export config
After testing a configuration in the **{{< short_app_ref >}}**  web interface, navigate to: `Settings/Client Settings`:

![Client Settings](../images/export.png)

If—and **ONLY** if—`Ollama` or `OpenAI` are selected as providers for **both** chat and embedding models:

* select `Include Sensitive Settings` checkbox 
* Click `Download LangchainMCP` to download a zip file containing a complete project template based on the currently selected configuration.
* Extract the archive into a directory referred to in this document as <PROJECT_DIR>.

To run the exported project, follow the steps in the sections below.

{{% notice style="code" title="NOTICE" icon="circle-info" %}} 
* if you plan to run the application on a different hos, update `optimizer_settings.json` to reflect non-local resources such as LLM endpoints, database hosts, wallet directories, and similar settings.
* if the `Download LangchainMCP` button is not visible, verify that Ollama or OpenAI is selected for both the chat model and the embedding model.
{{% /notice %}}

## Pre-requisites.
The following software is required:
- Node.js: v20.17.0+
- npx/npm: v11.2.0+
- uv: v0.7.10+
- Claude Desktop free

## Setup
With **[`uv`](https://docs.astral.sh/uv/getting-started/installation/)** installed, run the following commands FROM `<PROJECT_DIR>`:

```bash
uv init --python=3.11 --no-workspace
uv venv --python=3.11
source .venv/bin/activate
uv add mcp langchain-core==0.3.52 oracledb~=3.1 langchain-community==0.3.21 langchain-huggingface==0.1.2 langchain-openai==0.3.13 langchain-ollama==0.3.2
```

## Standalone client

A standalone client is included to allow command-line testing without an MCP client.

From `<PROJECT_DIR>`, run:

```bash
uv run rag_base_optimizer_config_direct.py "[YOUR_QUESTION]"
```
This is useful for validating the configuration before deploying the MCP server.

## Run the RAG Tool by a remote MCP server

Open `rag_base_optimizer_config_mcp.py` and verify the MCP server initialization.

* For a `Remote client`, ensure the configuration matches the following:

```python
# Initialize FastMCP server
mcp = FastMCP("rag",host="0.0.0.0", port=9090) #Remote client
#mcp = FastMCP("rag") #Local
```

* Next, verify or update the transport configuration:

```python
    #mcp.run(transport='stdio')
    #mcp.run(transport='sse')
    mcp.run(transport='streamable-http')
```

* Start the MCP server in a separate shell:

```bash
uv run rag_base_optimizer_config_mcp.py
```

## Quick test via MCP "inspector"

* Start the MCP inspector:

```bash
npx @modelcontextprotocol/inspector@0.15.0
```

* Open the generated URL, for example:

```
http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=1b40988bb02624b74472a9e8634a6d78802ced91c34433bf427cb3533c8fee2c
```

* Configure the inspector as follows:
	* **Transport Type**: `Streamable HTTP`
	*  **URL**: `http://localhost:9090/mcp`

* Test the exported RAG tool.

## Claude Desktop setup

The free version of **Claude Desktop** does not natively support remote MCP servers. For testing purposes, this limitation can be addressed using the `mcp-remote` proxy.

* In **Claude Desktop**, navigate to `Settings → Developer → Edit Config`. Edit the `claude_desktop_config.json` to add a reference to the remote MCP server in `streamable-http`:
	```json
	{
 	"mcpServers": {
		...
		,
		"rag":{
			"command": "npx",
			"args": [
				"mcp-remote",
				"http://127.0.0.1:9090/mcp"
				]
			}
   		}
	}
	```


* Next, go to `Settings → General → Claude Settings → Configure → Profile`, and update the fields such as:

	- `Full Name`
	- `What should we call you`
	
	and so on, putting in `What personal preferences should Claude consider in responses?`
	the following text:

	```
	#INSTRUCTION:
	Always call the rag_tool tool when the user asks a factual or information-seeking question, even if you think you know the answer.
	Show the rag_tool message as-is, without modification.
	```
	This forces the use of `rag_tool` for all relevant queries.

* Restart **Claude Desktop**.

* You may initially see warnings related to the `rag_tool` configuration. These warnings are expected and do not prevent tool activation.

* When starting a conversation, Claude Desktop will prompt you to authorize the use of the `rag` tool: 

![Rag Tool](../images/rag_tool.png)

 If the question matches content stored in the vector store, the response will be grounded in that knowledge base. Otherwise, the LLM will fall back to its general training or other configured tools.
 
{{% notice style="code" title="Notice" icon="circle-info" %}}
IIf you encounter issues during startup, inspect the logs for compatibility problems related to older Node.js or npx versions used by the mcp-remote library.

Check installed Node.js versions with:
```bash
nvm -list
```
If multiple versions are present, Claude Desktop may default to an older one. Removing outdated versions and keeping only Node.js v20.17.0 or later can resolve these issues. Restart the MCP server and Claude Desktop, then test again.
{{% /notice %}}