# Oracle Vector Store Integration Guide

This guide explains how to properly integrate and use the Oracle Vector Store (OracleVS) with the AI Optimizer project.

## Overview

The Oracle Vector Store integration allows the AI Optimizer to perform semantic search over documents stored in an Oracle database using vector embeddings. This enables Retrieval-Augmented Generation (RAG) capabilities where the AI can retrieve relevant information from a knowledge base before generating responses.

## Architecture

The integration uses the Model Context Protocol (MCP) to connect the client-side application with server-side tools:

1. **Client Side**: The MCP client in `src/client/mcp/client.py` handles communication with MCP servers
2. **Server Side**: The OracleVS tool in `src/server/mcp/tools/oraclevs_mcp_server.py` provides vector search capabilities
3. **Database Connection**: The tool connects to Oracle databases through the API server's database management system

## Prerequisites

1. **Oracle Database** with Vector Search capabilities (Oracle 23c or later recommended)
2. **Ollama** with the `nomic-embed-text` model installed for generating embeddings
3. **Properly configured database connection** in the application settings

## Configuration

### Database Setup

1. Ensure your Oracle database has the Vector Store tables created with proper vector indexes
2. Configure database connection settings in the application's database configuration tab
3. Verify that vector store tables are detected and shown in the Vector Storage section

### Vector Store Configuration

In the application's Database configuration:
1. Select the appropriate database connection
2. Choose the vector store table from the dropdown menus
3. Configure search parameters like Top K, Search Type, etc.

## How It Works

### Client-Side Integration

The MCP client automatically passes the following parameters to the OracleVS tool:

- `server_url`: The API server URL for database connection
- `api_key`: Authentication key for the API server
- `database_alias`: The selected database connection alias
- `vector_store_alias`: The selected vector store alias
- `vector_store`: The actual vector store table name

### Server-Side Implementation

The OracleVS MCP server (`src/server/mcp/tools/oraclevs_mcp_server.py`) handles:

1. **Database Connection**: Connects to the Oracle database using provided credentials
2. **Embedding Generation**: Uses Ollama with `nomic-embed-text` model to generate query embeddings
3. **Vector Search**: Performs similarity search against the vector store
4. **Result Formatting**: Returns relevant documents in a structured format

## Usage

### Enabling Vector Search

1. Navigate to the Configuration → Database section
2. Ensure a database is connected and has vector store tables
3. In the ChatBot interface, select "Vector Search" from the Tool Selection dropdown
4. Configure the vector store parameters in the sidebar

### Search Parameters

- **Search Type**: Choose between Similarity or Maximal Marginal Relevance (MMR)
- **Top K**: Number of results to return (1-10000)
- **Vector Store**: Select the appropriate vector store table

### API Usage

The tool can be called with these parameters:

```json
{
  "question": "What information is stored about Oracle?",
  "search_type": "Similarity",
  "top_k": 5,
  "vector_store": "your_vector_store_table_name"
}
```

## Troubleshooting

### Common Issues

1. **"No database connection available"**: 
   - Ensure database credentials are properly configured
   - Verify the database is accessible from the server
   - Check that the API server is running

2. **"No vector store tables found"**:
   - Verify vector store tables exist in the database
   - Check that the tables have the proper GENAI metadata comments
   - Ensure the database user has proper permissions

3. **Tool not appearing in client**:
   - Verify the MCP server configuration in `src/server/mcp/server_config.json`
   - Check that the OracleVS server script is executable
   - Restart the application to reload MCP servers

### Debugging Steps

1. Check the server logs for connection errors
2. Verify Ollama is running and has the `nomic-embed-text` model
3. Test database connectivity with SQL*Plus or another Oracle client
4. Ensure the vector store tables have proper metadata comments

## Security Considerations

1. **Database Credentials**: Never commit database credentials to version control
2. **API Keys**: Use strong, randomly generated API keys
3. **Network Security**: Ensure database connections use secure protocols
4. **Access Control**: Limit database user permissions to only necessary operations

## Performance Optimization

1. **Vector Indexes**: Ensure proper vector indexes are created on vector store tables
2. **Embedding Model**: Use appropriate embedding models for your use case
3. **Search Parameters**: Tune Top K and other parameters for optimal performance
4. **Database Configuration**: Optimize Oracle database settings for vector operations

## Extending the Integration

### Adding New Search Types

To add new search types:
1. Modify the OracleVS tool in `src/server/mcp/tools/oraclevs_mcp_server.py`
2. Update the client-side parameter passing in `src/client/mcp/client.py`
3. Add UI elements in the vector search sidebar configuration

### Custom Embedding Models

To use different embedding models:
1. Update the embedding initialization in the OracleVS server
2. Ensure the model is available in Ollama or your embedding service
3. Update any dimension-specific code to match the new model

## Testing

Use the provided test scripts:
- `test_oraclevs_tool.py`: Tests the basic OracleVS tool functionality
- `test_vector_store.py`: Tests vector store parameter passing

Run tests with:
```bash
python3 test_oraclevs_tool.py
python3 test_vector_store.py
