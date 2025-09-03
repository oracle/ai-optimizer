
# MCP Server for a tested AI Optimizer & Toolkit configuration

**Version:** *Developer preview*

## Introduction
This document describe how to re-use the configuration tested in the **AI Optimizer & Toolkit** an expose it as an MCP tool to a local **Claude Desktop** and how to setup as a remote MCP server. This early draft implementation utilizes the `stdio` and `sse` to interact between the agent dashboard, represented by the **Claude Desktop**, and the tool. 

**NOTICE**: Only `Ollama` or `OpenAI` configurations are currently supported. Full support will come.

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

## Export config
In the **AI Optimizer & Toolkit** web interface, after tested a configuration, in `Configuration/Settings/Client Settings`: 

![Client Settings](./images/export.png)

* select the checkbox `Include Sensitive Settings`.
* press button `Download LangchainMCP` to download an VectorSearch MCP Agent built on current configuration.
* unzip the file in a `<PROJECT_DIR>` dir.


## Standalone client
There is a client that you can run without MCP via command-line to test it:

```bash
uv run rag_base_optimizer_config.py "[YOUR_QUESTION]"
```
In `rag_base_optimizer_config_mcp.py`:

## Claude Desktop setup

Claude Desktop, in free version, not allows to connect remote server. You can overcome, for testing purpose only, with a proxy library called `mcp-remote`. These are the options.
If you have already installed Node.js v20.17.0+, it should work.

* In **Claude Desktop** application, in `Settings/Developer/Edit Config`, get the `claude_desktop_config.json` to

	* Set **remote sse** execution: 

	  add the references to the local MCP server for RAG in the `<PROJECT_DIR>`:
	```json
	{
 	"mcpServers": {
		...
		,
		"rag":{
			"command": "npx",
			"args": [
				"mcp-remote",
				"http://127.0.0.1:9090/sse"
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

* Start MCP server in another shell in <PROJECT_DIR> with:
```bash
uv run rag_base_optimizer_config_mcp.py
```
* Restart **Claude Desktop**.

* You will see two warnings on rag_tool configuration: they will disappear and will not cause any issue in activating the tool.

* Start a conversation. You should see a pop up that ask to allow the `rag` tool usage to answer the questions:

![Rag Tool](./images/rag_tool.png)

 If the question is related to the knowledge base content stored in the vector store, you will have an answer based on that information. Otherwise, it will try to answer considering information on which has been trained the LLM o other tools configured in the same Claude Desktop.

* **Optional**: for a **local stdio** execution, without launching the MCP Server:

	* Add the references to the local MCP server for RAG in the `<PROJECT_DIR>`:
	```json
	{
 	"mcpServers": {
		...
		,
		"rag":{
			"command":"bash",
			"args":[
				"-c",
				"source <PROJECT_DIR>/.venv/bin/activate && uv run <PROJECT_DIR>/rag_base_optimizer_config_mcp.py"
				]
			}
   		}
	}
	```
	* Set `Local` with `Remote client` line in `<PROJECT_DIR>/rag_base_optimizer_config_mcp.py`:

	```python
	#mcp = FastMCP("rag", port=9090) #Remote client
	mcp = FastMCP("rag") #Local
	```

	* Substitute `stdio` with `sse` line of code:
	```python
	mcp.run(transport='stdio')
	#mcp.run(transport='sse')
	```


## Alternative way for a quick test: MCP "inspector"

* Start MCP server in another shell in <PROJECT_DIR> with:
```bash
uv run rag_base_optimizer_config_mcp.py
```

* Run the inspector:

```bash
npx @modelcontextprotocol/inspector 
```

* connect the browser to `http://127.0.0.1:6274` 

* set the Transport Type to `SSE`

* set the `URL` to `http://localhost:9090/sse`

* test the tool developed.



**Optional:** run with local **stdio** protocol
* Set as shown before the protolo to run locally in `<PROJECT_DIR>/rag_base_optimizer_config_mcp.py`:

	```
	* Set `Local` with `Remote client` line:

	```python
	#mcp = FastMCP("rag", port=9090) #Remote client
	mcp = FastMCP("rag") #Local
	```

	* Substitute `stdio` with `sse` line of code:
	```python
	mcp.run(transport='stdio')
	#mcp.run(transport='sse')
	```

* Run the inspector:

```bash
npx @modelcontextprotocol/inspector uv run rag_base_optimizer_config_mcp.py
```

* connect to the port `http://localhost:6274/` with your browser on the link printed, like in the following example:
```bash
..
Open inspector with token pre-filled:
http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=cb2ef7521aaf2050ad9620bfb5e5df42dc958889e6e99ce4e9b18003eb93fffd
..
```

* setup the `Inspector Proxy Address` with `http://127.0.0.1:6277` 
* test the tool developed.



**NOTICE**: If you have any problem running, check the logs if it's related to an old npx/nodejs version used with mcp-remote library. Check with:
```bash
nvm -list
```
if you have any other versions available than the default. It could happen that Claude Desktop uses the older one. Try to remove any other nvm versions available to force the use the only one avalable, at minimum v20.17.0+.

* restart and test as remote server