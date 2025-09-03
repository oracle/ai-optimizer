#!/usr/bin/env python3
"""
Test script to verify that the OracleVS tool works correctly with vector_store parameter
"""
import sys
import os
import asyncio
sys.path.insert(0, 'src')

from client.mcp.client import MCPClient

# Test settings with a simple model
test_settings = {
    'll_model': {
        'model': 'llama3.1',
        'temperature': 1.0,
        'max_completion_tokens': 2048
    }
}

# Update server config to use correct path
import json
import os
server_config_path = 'src/server/mcp/server_config.json'
if os.path.exists(server_config_path):
    with open(server_config_path, 'r') as f:
        config = json.load(f)
    if 'mcpServers' in config and 'oraclevs' in config['mcpServers']:
        config['mcpServers']['oraclevs']['args'] = ['src/server/mcp/tools/oraclevs_mcp_server.py']
        with open(server_config_path, 'w') as f:
            json.dump(config, f, indent=2)

async def test_vector_store_tool():
    print("Testing OracleVS tool with vector_store parameter...")
    
    try:
        # Initialize MCP client
        async with MCPClient(test_settings) as mcp_client:
            print("✓ MCP client initialized successfully")
            
            # Check available tools
            print(f"\nAvailable tools: {[tool['name'] for tool in mcp_client.available_tools]}")
            
            # Check if oraclevs_retriever is available
            tool_in_session = 'oraclevs_retriever' in mcp_client.tool_to_session
            if not tool_in_session:
                print("❌ OracleVS tool is not loaded")
                return False
            
            # Rebuild schemas to ensure tool is available
            await mcp_client._rebuild_mcp_tool_schemas()
            oraclevs_available = any(tool['name'] == 'oraclevs_retriever' for tool in mcp_client.available_tools)
            if not oraclevs_available:
                print("❌ OracleVS tool is not available in rebuilt schema")
                return False
            
            print("✓ OracleVS tool is available")
            
            # Test OracleVS tool with vector_store parameter
            print("\nTesting oraclevs_retriever tool with vector_store parameter...")
            tool_args = {
                "question": "What information is stored about Oracle?",
                "search_type": "Similarity",
                "top_k": 5,
                "vector_store": "plan_vector"
            }
            
            try:
                result = await mcp_client.execute_mcp_tool("oraclevs_retriever", tool_args)
                print(f"✓ OracleVS tool executed successfully")
                print(f"Result: {result}")
                return True
            except Exception as e:
                print(f"❌ OracleVS tool failed: {e}")
                import traceback
                traceback.print_exc()
                return False
                
    except Exception as e:
        print(f"❌ MCP client initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_vector_store_tool())
    if success:
        print("\n🎉 Test passed!")
    else:
        print("\n❌ Test failed!")
        sys.exit(1)
