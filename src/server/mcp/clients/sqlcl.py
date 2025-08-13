import asyncio
from fastmcp import Client

# Your configuration dictionary using multiple servers
config = {
    "mcpServers": {
        "sqlcl": {
            "transport": "stdio",
            "command": "sql",
            "args": ["-mcp"]
        }
    }
}

client = Client(config)

async def main():
    async with client:
        # Test connection
        pong = await client.ping()
        print("Ping response:", pong)

        # List available tools on the sqlcl server
        tools = await client.list_tools()
        print("Available tools:", tools)

        # Example: call a tool if you know its name
        # result = await client.call_tool("your_tool_name", {"param": "value"})
        # print("Tool result:", result)

asyncio.run(main())
