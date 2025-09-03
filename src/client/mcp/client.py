import json
import os
import time
import asyncio
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from typing import List, Dict, Optional, Tuple, Type, Any
from contextlib import AsyncExitStack

# Import Streamlit session state
try:
    from streamlit import session_state as state
except ImportError:
    state = None

# --- MODIFICATION: Import LangChain components ---
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, BaseMessage
from langchain_core.language_models.base import BaseLanguageModel
from pydantic import create_model, BaseModel, Field
# Import the specific chat models you want to support
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_cohere import ChatCohere
from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from langchain_mistralai import ChatMistralAI

load_dotenv()

if os.getenv("IS_STREAMLIT_CONTEXT"):
    import nest_asyncio
    nest_asyncio.apply()

class MCPClient:
    # MODIFICATION: Changed the constructor to accept client_settings
    def __init__(self, client_settings: Dict):
        """
        Initialize MCP Client using a settings dictionary from the Streamlit client.
        
        Args:
            client_settings: The state.client_settings object.
        """
        # 1. Validate the incoming settings dictionary
        if not client_settings or 'll_model' not in client_settings:
            raise ValueError("Client settings are incomplete. 'll_model' is required.")

        # 2. Store the settings and extract the model ID
        self.model_settings = client_settings['ll_model']

        # This is our new "Service Factory" using LangChain classes
        # If no model is specified, we'll initialize with a default one
        if 'model' not in self.model_settings or not self.model_settings['model']:
            # Set a default model if none is specified
            self.model_settings['model'] = 'llama3.1'
            # Remove any OpenAI-specific parameters that might cause issues
            self.model_settings.pop('openai_api_key', None)
        
        self.langchain_model = self._create_langchain_model(**self.model_settings)

        self.exit_stack = AsyncExitStack()
        self.sessions: Dict[str, ClientSession] = {}
        self.tool_to_session: Dict[str, Tuple[ClientSession, types.Tool]] = {}
        self.available_prompts: Dict[str, types.Prompt] = {}
        self.static_resources: Dict[str, str] = {}
        self.dynamic_resources: List[str] = []
        self.resource_to_session: Dict[str, str] = {}
        self.prompt_to_session: Dict[str, str] = {}
        self.available_tools: List[Dict] = []
        self._stdio_generators: Dict[str, Any] = {}  # To store stdio generators for cleanup
        print(f"Initialized MCPClient with LangChain model: {self.langchain_model.__class__.__name__}")

    # --- FIX: Add __aenter__ and __aexit__ to make this a context manager ---
    async def __aenter__(self):
        """Enter the async context, connecting to all servers."""
        await self.connect_to_servers()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context, ensuring all connections are cleaned up."""
        await self.cleanup()

    def _create_langchain_model(self, model: str, **kwargs) -> BaseLanguageModel:
        """Factory to create and return a LangChain ChatModel instance."""
        # If no model is specified, default to llama3.1 which works with Ollama
        if not model:
            model = "llama3.1"
            # Remove any OpenAI-specific parameters that might cause issues
            kwargs.pop('openai_api_key', None)
        
        model_lower = model.lower()

        # Handle OpenAI models
        if model_lower.startswith('gpt-') and not model_lower.startswith('gpt-oss:'):
            # Check if api_key is in kwargs and rename it to openai_api_key for ChatOpenAI
            if 'api_key' in kwargs:
                kwargs['openai_api_key'] = kwargs.pop('api_key')
            # Remove parameters that shouldn't be passed to ChatOpenAI
            kwargs.pop('context_length', None)
            kwargs.pop('chat_history', None)
            return ChatOpenAI(model=model, **kwargs)
        
        # Handle Ollama models (including gpt-oss:20b)
        elif model_lower.startswith('gpt-oss:') or model_lower in ['llama3.1', 'llama3', 'mistral', 'nomic-embed-text']:
            return ChatOllama(model=model, **kwargs)
        
        # Handle Anthropic models
        elif model_lower.startswith('claude-'):
            kwargs.pop('openai_api_key', None)
            return ChatAnthropic(model=model, **kwargs)
        
        # Handle Google models
        elif model_lower.startswith('gemini-'):
            kwargs.pop('openai_api_key', None)
            return ChatGoogleGenerativeAI(model=model, **kwargs)
        
        # Handle Mistral models
        elif model_lower.startswith('mistral-'):
            kwargs.pop('openai_api_key', None)
            return ChatMistralAI(model=model, **kwargs)
        
        # Handle Cohere models
        elif model_lower.startswith('cohere-'):
            kwargs.pop('openai_api_key', None)
            return ChatCohere(model=model, **kwargs)
        
        # Handle Groq models
        elif model_lower.startswith('groq-'):
            kwargs.pop('openai_api_key', None)
            return ChatGroq(model=model, **kwargs)
        
        # Default to Ollama for any other model name
        else:
            return ChatOllama(model=model, **kwargs)

    def _convert_dict_to_langchain_messages(self, message_history: List[Dict]) -> List[BaseMessage]:
        """Converts a list of message dictionaries to a list of LangChain message objects."""
        messages: List[BaseMessage] = []
        for msg in message_history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))  # type: ignore
            elif role == "assistant":
                # AIMessage can handle tool calls directly from the dictionary format
                tool_calls = msg.get("tool_calls")
                messages.append(AIMessage(content=content, tool_calls=tool_calls or []))  # type: ignore
            elif role == "system":
                messages.append(SystemMessage(content=content))  # type: ignore
            elif role == "tool":
                messages.append(ToolMessage(content=content, tool_call_id=msg.get("tool_call_id", "")))  # type: ignore
        return messages  # type: ignore

    def _convert_langchain_messages_to_dict(self, langchain_messages: List[BaseMessage]) -> List[Dict]:
        """Converts a list of LangChain message objects back to a list of dictionaries for session state."""
        dict_messages = []
        for msg in langchain_messages:
            if isinstance(msg, HumanMessage):
                dict_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                # Preserve tool calls in the dictionary format
                dict_messages.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})
            elif isinstance(msg, SystemMessage):
                dict_messages.append({"role": "system", "content": msg.content})
            elif isinstance(msg, ToolMessage):
                dict_messages.append({"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id})
        return dict_messages

    def _prepare_messages_for_service(self, message_history: List[Dict]) -> List[Dict]:
        """
        FIX: Translates the rich message history from the GUI into a simple,
        text-only format that AI services can understand.
        """
        prepared_messages = []
        for msg in message_history:
            content = msg.get("content")
            # If content is a list (multimodal), extract only the text.
            if isinstance(content, list):
                text_content = " ".join(
                    part["text"] for part in content if part.get("type") == "text"
                )
                prepared_messages.append({"role": msg["role"], "content": text_content})
            # Otherwise, use the content as is (assuming it's a string).
            else:
                prepared_messages.append(msg)
        return prepared_messages

    async def connect_to_servers(self):
        try:
            config_paths = ["server/mcp/server_config.json", os.path.join(os.path.dirname(__file__), "..", "..", "server", "mcp", "server_config.json")]
            servers = {}
            for config_path in config_paths:
                try:
                    with open(config_path, "r") as file: 
                        servers = json.load(file).get("mcpServers", {})
                        print(f"Loaded MCP server configuration from: {config_path}")
                        print(f"Found servers: {list(servers.keys())}")
                        break
                except FileNotFoundError: 
                    print(f"MCP server config not found at: {config_path}")
                    continue
                except Exception as e:
                    print(f"Error reading MCP server config from {config_path}: {e}")
                    continue
            if not servers:
                print("No MCP server configuration found!")
            for name, config in servers.items(): 
                print(f"Connecting to MCP server: {name}")
                await self.connect_to_server(name, config)
        except Exception as e: print(f"Error loading server configuration: {e}")
    
    async def connect_to_server(self, server_name: str, server_config: dict):
        try:
            print(f"Connecting to server '{server_name}' with config: {server_config}")
            server_params = StdioServerParameters(**server_config)
            
            # Create the stdio client connection using the exit stack for proper cleanup
            try:
                read, write = await self.exit_stack.enter_async_context(stdio_client(server_params))
                
                # Create the client session using the exit stack for proper cleanup
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                
                await session.initialize()
                self.sessions[server_name] = session
                
                # Load tools, resources, and prompts from this server
                await self._load_server_capabilities(session, server_name)
            except RuntimeError as e:
                # Handle runtime errors related to task context
                if "cancel scope" not in str(e).lower():
                    raise
                print(f"Warning: Connection to '{server_name}' had context issues: {e}")
            except Exception as e:
                raise
        except Exception as e: 
            print(f"Failed to connect to '{server_name}': {e}")
            import traceback
            traceback.print_exc()
    
    async def _run_async_generator(self, generator):
        """Helper method to run an async generator in the current task context."""
        return await generator.__anext__()
    
    async def _load_server_capabilities(self, session: ClientSession, server_name: str):
        """Load tools, resources, and prompts from a connected server."""
        try:
            # List tools
            tools_list = await session.list_tools()
            print(f"Found {len(tools_list.tools)} tools from server '{server_name}'")
            for tool in tools_list.tools:
                self.tool_to_session[tool.name] = (session, tool)
                print(f"Loaded tool '{tool.name}' from server '{server_name}'")
            
            # List resources
            try:
                resp = await session.list_resources()
                if resp.resources: print(f"  - Found Static Resources: {[r.name for r in resp.resources]}")
                for resource in resp.resources:
                    uri = resource.uri.encoded_string()
                    self.resource_to_session[uri] = server_name
                    user_shortcut = uri.split('//')[-1]
                    self.static_resources[user_shortcut] = uri
                    if resource.name and resource.name != user_shortcut:
                        self.static_resources[resource.name] = uri
            except Exception as e:
                print(f"Failed to load resources from server '{server_name}': {e}")
            
            # Discover DYNAMIC resource templates
            try:
                # The response object for templates has a `.templates` attribute
                resp = await session.list_resource_templates()
                if resp.resourceTemplates: print(f"  - Found Dynamic Resource Templates: {[t.name for t in resp.resourceTemplates]}")
                for template in resp.resourceTemplates:
                    uri = template.uriTemplate
                    # The key for the session map MUST be the pattern itself.
                    self.resource_to_session[uri] = server_name
                    if uri not in self.dynamic_resources: 
                        self.dynamic_resources.append(uri)
            except Exception as e:
                # This is also okay, some servers don't have dynamic resources.
                print(f"Failed to load dynamic resources from server '{server_name}': {e}")

            
            # List prompts
            try:
                prompts_list = await session.list_prompts()
                print(f"Found {len(prompts_list.prompts)} prompts from server '{server_name}'")
                for prompt in prompts_list.prompts:
                    self.available_prompts[prompt.name] = prompt
                    self.prompt_to_session[prompt.name] = server_name
                    print(f"Loaded prompt '{prompt.name}' from server '{server_name}'")
            except Exception as e:
                print(f"Failed to load prompts from server '{server_name}': {e}")
                
        except Exception as e:
            print(f"Failed to load capabilities from server '{server_name}': {e}")
                
    async def _rebuild_mcp_tool_schemas(self):
        """Rebuilds the list of tools from connected MCP servers in a LangChain-compatible format."""
        self.available_tools = []
        for _, (_, tool_object) in self.tool_to_session.items():
            # LangChain's .bind_tools can often work directly with this MCP schema
            tool_schema = {
                "name": tool_object.name,
                "description": tool_object.description,
                "args_schema": self.create_pydantic_model_from_schema(tool_object.name, tool_object.inputSchema)
            }
            self.available_tools.append(tool_schema)
        print(f"Available tools after rebuild: {len(self.available_tools)}")

    def create_pydantic_model_from_schema(self, name: str, schema: dict) -> Type[BaseModel]:
        """Dynamically creates a Pydantic model from a JSON schema for LangChain tool binding."""
        fields = {}
        if schema and 'properties' in schema:
            for prop_name, prop_details in schema['properties'].items():
                field_type = str  # Default to string
                # A more robust implementation would map JSON schema types to Python types
                if prop_details.get('type') == 'integer': field_type = int
                elif prop_details.get('type') == 'number': field_type = float
                elif prop_details.get('type') == 'boolean': field_type = bool
                
                fields[prop_name] = (field_type, Field(..., description=prop_details.get('description')))
        
        return create_model(name, **fields)  # type: ignore

    async def execute_mcp_tool(self, tool_name: str, tool_args: Dict) -> str:
        if tool_name == "oraclevs_retriever":
            # --- Server settings ---
            if getattr(state, "server", None):
                server = state.server
                if server.get("url") and server.get("port") and server.get("key"):
                    tool_args["server_url"] = f"{server['url']}:{server['port']}"
                    tool_args["api_key"] = server["key"]

            # --- Database alias ---
            if getattr(state, "client_settings", None):
                db = state.client_settings.get("database", {})
                if db.get("alias"):
                    tool_args["database_alias"] = db["alias"]

                # --- Vector search settings ---
                vs = state.client_settings.get("vector_search", {})
                if vs.get("alias"):
                    tool_args["vector_store_alias"] = vs["alias"]
                if vs.get("vector_store"):
                    tool_args["vector_store"] = vs["vector_store"]

            # --- Question fallback ---
            if not tool_args.get("question"):
                user_messages = [
                    msg for msg in getattr(state, "messages", []) if msg.get("role") == "user"
                ]
                if user_messages:
                    tool_args["question"] = user_messages[-1]["content"]
                else:
                    tool_args["question"] = "What information is available in the vector store?"

        try:
            session, _ = self.tool_to_session[tool_name]
            result = await session.call_tool(tool_name, arguments=tool_args)
            if not result.content: return "Tool executed successfully."
            
            # Handle different content types properly
            if isinstance(result.content, list):
                text_parts = []
                for item in result.content:
                    # Check if item has a text attribute
                    if hasattr(item, 'text'):
                        text_parts.append(str(item.text))
                    else:
                        # Handle other content types
                        text_parts.append(str(item))
                return " | ".join(text_parts)
            else:
                return str(result.content)
        except Exception as e:
            # Check if it's a closed resource error
            if "ClosedResourceError" in str(type(e)) or "closed" in str(e).lower():
                raise Exception("MCP session is closed. Please try again.") from e
            else:
                raise
    
    async def invoke(self, message_history: List[Dict]) -> Tuple[str, List[Dict], List[Dict]]:
        """
        Main entry point. Now returns a tuple of:
        (final_text_response, tool_calls_trace, new_full_history)
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                langchain_messages = self._convert_dict_to_langchain_messages(message_history)
                
                # Separate the final text response from the tool trace
                final_text_response = ""
                tool_calls_trace = [] 
                
                max_iterations = 10
                tool_execution_failed = False
                for iteration in range(max_iterations):
                    await self._rebuild_mcp_tool_schemas()
                    model_with_tools = self.langchain_model.bind_tools(self.available_tools)
                    response_message: AIMessage = await model_with_tools.ainvoke(langchain_messages)
                    langchain_messages.append(response_message)
                    
                    # Capture the final text response from the last message
                    if response_message.content:
                        final_text_response = response_message.content
                    
                    if not response_message.tool_calls:
                        break

                    for tool_call in response_message.tool_calls:
                        tool_name = tool_call['name']
                        tool_args = tool_call['args']
                        
                        try:
                            result_content = await self.execute_mcp_tool(tool_name, tool_args)
                            tool_calls_trace.append({
                                "name": tool_name,
                                "args": tool_args,
                                "result": result_content
                            })
                        except Exception as e:
                            if "MCP session is closed" in str(e) and attempt < max_retries - 1:
                                print(f"MCP session closed, reinitializing (attempt {attempt + 1})")
                                await self.cleanup(); await self.connect_to_servers()
                                await asyncio.sleep(0.1); tool_execution_failed = True; break
                            else:
                                result_content = f"Error executing tool {tool_name}: {e}"
                                tool_calls_trace.append({
                                    "name": tool_name,
                                    "args": tool_args,
                                    "error": result_content
                                })

                        langchain_messages.append(ToolMessage(content=result_content, tool_call_id=tool_call['id']))
                    
                    if tool_execution_failed: break
                
                if tool_execution_failed and attempt < max_retries - 1: continue
                
                final_history_dict = self._convert_langchain_messages_to_dict(langchain_messages)
                
                return final_text_response, tool_calls_trace, final_history_dict

            except RuntimeError as e:
                if "Event loop is closed" in str(e) and attempt < max_retries - 1:
                    print(f"Event loop closed, reinitializing model (attempt {attempt + 1})")
                    self.langchain_model = self._create_langchain_model(**self.model_settings)
                    await asyncio.sleep(0.1); continue
                else: raise Exception("Event loop closed. Please try again.") from e
            except Exception as e:
                if attempt >= max_retries - 1: raise
                print(f"Invoke attempt {attempt + 1} failed, retrying: {e}")
                await asyncio.sleep(0.1)
        
        raise Exception("Failed to invoke MCP client after all retries")

    async def cleanup(self):
        """Clean up all resources properly."""
        try:
            # Close all sessions using the exit stack to avoid context issues
            await self.exit_stack.aclose()
        except Exception as e:
            # Suppress errors related to async context management as they don't affect functionality
            if "cancel scope" not in str(e).lower() and "asyncio" not in str(e).lower():
                print(f"Error during cleanup: {e}")
        
        try:
            # Clear sessions
            self.sessions.clear()
            
            # Clear other data structures
            self.tool_to_session.clear()
            self.available_prompts.clear()
            self.static_resources.clear()
            self.dynamic_resources.clear()
            self.resource_to_session.clear()
            self.prompt_to_session.clear()
            self.available_tools.clear()
            
            # Recreate the exit stack for future use
            self.exit_stack = AsyncExitStack()
        except Exception as e:
            print(f"Error during cleanup: {e}")
