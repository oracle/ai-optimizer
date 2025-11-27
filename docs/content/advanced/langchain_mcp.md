+++
title = 'Export as MCP Langchain server'
weight = 1
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

**Version:** *Developer preview*

## Introduction to the MCP Server for a tested AI Optimizer & Toolkit configuration
This document describe how to re-use the configuration tested in the **AI Optimizer & Toolkit** an expose it as an MCP tool to a local **Claude Desktop** and how to setup as a remote MCP server, through **Python/Langchain** framework. This early draft implementation utilizes the `stdio` and `sse` to interact between the agent dashboard, represented by the **Claude Desktop**, and the tool. 

**NOTICE**: Only `Ollama` or `OpenAI` configurations are currently supported. Full support will come.

## Export config
In the **AI Optimizer & Toolkit** web interface, after have tested a configuration, in `Settings/Client Settings`:

![Client Settings](./images/export.png)

and **ONLY** if have been selected `Ollama` or `OpenAI` providers for **both** chat and embeddings models:

* select the checkbox `Include Sensitive Settings` 
* press button `Download LangchainMCP` to download a zip file containing a full project template to run current selected AI Optimizer configuration.
* unzip the file in a <PROJECT_DIR> dir.

To run it, follow the next steps.

**NOTICE**: 
* if you want to run the application in another server, remember to change in the optimizer_settings.json any reference no more local, like hostname for LLM servers, Database, wallet dir and so on.
* if you don't see the `Download LangchainMCP` check again if you have selected Ollama or OpenAI for both chat and the vectorstore embedding model.


## Pre-requisites.
You need:
- Node.js: v20.17.0+
- npx/npm: v11.2.0+
- uv: v0.7.10+
- Claude Desktop free

## Setup
With **[`uv`](https://docs.astral.sh/uv/getting-started/installation/)** installed, run the following commands in your current project directory `<PROJECT_DIR>`:

```bash
uv init --python=3.11 --no-workspace
uv venv --python=3.11
source .venv/bin/activate
uv add mcp langchain-core==0.3.52 oracledb~=3.1 langchain-community==0.3.21 langchain-huggingface==0.1.2 langchain-openai==0.3.13 langchain-ollama==0.3.2
```

## Standalone client

There is a client that let you run the service via command-line, to test it without an MCP client, in your `<PROJECT_DIR>`:

```bash
uv run rag_base_optimizer_config_direct.py "[YOUR_QUESTION]"
```

## Run the RAG Tool by a remote MCP server

In `rag_base_optimizer_config_mcp.py`:

* Check if configuration is like this for the clients (`Remote client`) in the following lines, otherwise change as shown:

```python
# Initialize FastMCP server
mcp = FastMCP("rag",host="0.0.0.0", port=9090) #Remote client
#mcp = FastMCP("rag") #Local
```

* Check, or change, according following lines of code:

```python
    #mcp.run(transport='stdio')
    #mcp.run(transport='sse')
    mcp.run(transport='streamable-http')
```

* Start MCP server in another shell with:

```bash
uv run rag_base_optimizer_config_mcp.py
```

## Quick test via MCP "inspector"

* Run the inspector:

```bash
npx @modelcontextprotocol/inspector@0.15.0
```

* connect to the linke report like this:

```
   http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=1b40988bb02624b74472a9e8634a6d78802ced91c34433bf427cb3533c8fee2c
```

* setup the `Transport Type` to `Streamable HTTP` 
* test the tool developed, setting `URL` to `http://localhost:9090/mcp`.


## Claude Desktop setup

Claude Desktop, in free version, not allows to connect remote server. You can overcome, for testing purpose only, with a proxy library called `mcp-remote`. These are the options.
If you have already installed Node.js v20.17.0+, it should work.

* In **Claude Desktop** application, in `Settings/Developer/Edit Config`, get the `claude_desktop_config.json` to add the reference to the local MCP server for RAG in `streamable-http`:
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


* In **Claude Desktop** application, in `Settings/General/Claude Settings/Configure`, under `Profile` tab, update fields like:

	- `Full Name`
	- `What should we call you`
	
	and so on, putting in `What personal preferences should Claude consider in responses?`
	the following text:

	```
	#INSTRUCTION:
	Always call the rag_tool tool when the user asks a factual or information-seeking question, even if you think you know the answer.
	Show the rag_tool message as-is, without modification.
	```
	This will impose the usage of `rag_tool` in any case. 

* Restart **Claude Desktop**.

* You will see two warnings on rag_tool configuration: they will disappear and will not cause any issue in activating the tool.

* Start a conversation. You should see a pop up that ask to allow the `rag` tool usage to answer the questions:

![Rag Tool](./images/rag_tool.png)

 If the question is related to the knowledge base content stored in the vector store, you will have an answer based on that information. Otherwise, it will try to answer considering information on which has been trained the LLM o other tools configured in the same Claude Desktop.

**NOTICE**: If you have any problem running, check the logs if it's related to an old npx/nodejs version used with mcp-remote library. Check with:
```bash
nvm -list
```
if you have any other versions available than the default. It could happen that Claude Desktop uses the older one. Try to remove any other nvm versions available to force the use the only one avalable, at minimum v20.17.0+.

* restart and test as remote server


{{% notice style="code" title="Documentation is Hard!" icon="circle-info" %}}
More information coming soon... 25-June-2025
{{% /notice %}}