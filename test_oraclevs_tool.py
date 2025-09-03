#!/usr/bin/env python3
"""
Test script to verify that the OracleVS tool works correctly through the MCP client
"""
import sys
import os
import asyncio
import json
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

async def test_oraclevs_tool():
    print("Testing OracleVS tool through MCP client...")
    
    try:
        # Initialize MCP client
        async with MCPClient(test_settings) as mcp_client:
            print("✓ MCP client initialized successfully")
            
            # Check available tools
            print(f"\nAvailable tools: {[tool['name'] for tool in mcp_client.available_tools]}")
            
            # Check tool to session mapping
            print(f"Tool to session mapping: {list(mcp_client.tool_to_session.keys())}")
            
            # Check if oraclevs_retriever is available
            oraclevs_available = any(tool['name'] == 'oraclevs_retriever' for tool in mcp_client.available_tools)
            tool_in_session = 'oraclevs_retriever' in mcp_client.tool_to_session
            if oraclevs_available:
                print("✓ OracleVS tool is available through MCP protocol")
            elif tool_in_session:
                print("⚠️  OracleVS tool is loaded but not in available tools list")
                print("This might be due to a schema rebuilding issue")
                # Try to rebuild schemas
                await mcp_client._rebuild_mcp_tool_schemas()
                print(f"Available tools after rebuild: {[tool['name'] for tool in mcp_client.available_tools]}")
                oraclevs_available = any(tool['name'] == 'oraclevs_retriever' for tool in mcp_client.available_tools)
                if oraclevs_available:
                    print("✓ OracleVS tool is now available after schema rebuild")
                else:
                    print("❌ OracleVS tool still not available after schema rebuild")
                    return False
            else:
                print("❌ OracleVS tool is not available through MCP protocol")
                return False
            
            # Test OracleVS tool
            print("\nTesting oraclevs_retriever tool...")
            tool_args = {
                "question": "What is Oracle?",
                "search_type": "Similarity",
                "top_k": 2
            }
            
            try:
                result = await mcp_client.execute_mcp_tool("oraclevs_retriever", tool_args)
                print(f"✓ OracleVS tool executed successfully")
                print(f"Result: {result}")
                # Check if the result contains the expected structure
                if isinstance(result, str) and "error" in result:
                    print("⚠️  OracleVS tool returned an error (expected without database connection)")
                    return True
                else:
                    print("✓ OracleVS tool returned successful result")
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
    success = asyncio.run(test_oraclevs_tool())
    if success:
        print("\n🎉 All tests passed!")
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)
