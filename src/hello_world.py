import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools


client = MultiServerMCPClient(
    {
        "optimizer": {
            "transport": "streamable_http",
            "url": "http://localhost:8000/mcp/",
            "headers": {"Authorization": "Bearer demo_api_key"},
        }
    }
)
async def call_tool(name: str):
    tools = await client.get_tools()
    agent = create_react_agent("openai:gpt-4o-mini", tools)
    math_response = await agent.ainvoke({"messages": "what's (3 + 5) x 12?"})
    print(math_response)
    
# async def call_tool(name: str):
#     async with client.session("optimizer") as session:
        # tools = await load_mcp_tools(session)
        # agent = create_react_agent("openai:gpt-4o-mini", tools)
        # # math_response = await agent.ainvoke({"messages": "what's (3 + 5) x 12?"})
        # # weather_response = await agent.ainvoke({"messages": "what is the weather in nyc?"})
        # database_response = await agent.ainvoke({"messages": "connect to OPTIMIZER_DEFAULT"})
        # database_response = await agent.ainvoke({"messages": "show me a list of table names"})
        # print(database_response)
        # # print(weather_response)

asyncio.run(call_tool("Ford"))

# async def call_tool(name: str):
#     async with streamablehttp_client(config) as (read, write, _):
#         async with ClientSession(read, write) as session:
#             # Initialize the connection
#             await session.initialize()

#             # Get tools
#             tools = await load_mcp_tools(session)
#             agent = create_react_agent("openai:gpt-4o-mini", tools)
#             math_response = await agent.ainvoke({"messages": "what's (3 + 5) x 12?"})
#             print(math_response)


# asyncio.run(call_tool("Ford"))

# client = Client(config)
# async def call_tool(name: str):
#     async with client:
#         print(f"Connected: {client.is_connected()}")
#         tools = await client.load_mcp_tools(client)
#         # agent = create_react_agent("openai:gpt-4o-mini", tools)
#         # math_response = await agent.ainvoke({"messages": "what's (3 + 5) x 12?"})
#         # print(math_response)
#         # result = await client.call_tool("optimizer_greet", {"name": name})
#         # print(result)
#         # result = await client.call_tool("optimizer_multiply", {"a": 5, "b": 3})
#         # print(result)


# from mcp import ClientSession
# from mcp.client.streamable_http import streamablehttp_client

# from langgraph.prebuilt import create_react_agent
# from langchain_mcp_adapters.tools import load_mcp_tools

# async with streamablehttp_client("http://localhost:8000/mcp/") as (read, write, _):
#     async with ClientSession(read, write) as session:
#         # Initialize the connection
#         await session.initialize()

#         # Get tools
#         tools = await load_mcp_tools(session)
#         agent = create_react_agent("openai:gpt-4.1", tools)
#         math_response = await agent.ainvoke({"messages": "what's (3 + 5) x 12?"})
