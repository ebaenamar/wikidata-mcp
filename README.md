# Wikidata MCP Server (SSE Version)

A Model Context Protocol (MCP) server with Server-Sent Events (SSE) transport that connects Large Language Models to Wikidata's structured knowledge base. This server enables LLMs to search for entities, retrieve metadata, query relationships, and execute SPARQL queries to access factual information from Wikidata.

## Features

- **SSE Transport**: Network-accessible MCP server (vs. stdio in the original version)
- Search for Wikidata entities by name
- Search for Wikidata properties by name
- Retrieve entity metadata (labels, descriptions)
- Get entity properties and their values
- Execute SPARQL queries against Wikidata's endpoint
- Find entity facts with optional property filtering
- Get related entities with optional relation filtering
- Access common property references and SPARQL examples
- Use prompt templates for common Wikidata interaction patterns

## Live Demo

The server is deployed and accessible at:

- **URL**: [https://wikidata-mcp-mirror.onrender.com](https://wikidata-mcp-mirror.onrender.com)
- **SSE Endpoint**: [https://wikidata-mcp-mirror.onrender.com/messages/](https://wikidata-mcp-mirror.onrender.com/messages/)
- **Health Check**: [https://wikidata-mcp-mirror.onrender.com/health](https://wikidata-mcp-mirror.onrender.com/health)

## Usage with Claude Desktop

To use this server with Claude Desktop:

1. Edit the Claude Desktop configuration file located at:
   ```
   ~/Library/Application Support/Claude/claude_desktop_config.json
   ```

2. Configure it to use the remote MCP server:
   ```json
   {
     "mcpServers": {
       "Wikidata Knowledge Remote": {
         "command": "mcp-remote",
         "args": [
           "https://wikidata-mcp-mirror.onrender.com/messages/"
         ]
       }
     }
   }
   ```

3. Restart Claude Desktop

4. When using Claude, you can now access Wikidata knowledge through the configured MCP server.

## Local Development

### Prerequisites

- Python 3.10+
- Virtual environment tool (venv, conda, etc.)

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/ebaenamar/wikidata-mcp.git
   cd wikidata-mcp-server-sse
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the server locally:
   ```bash
   python server_sse.py
   ```

   The server will start on `http://localhost:8000` by default.

## Testing the Server

You can test the server using the included test client:

```bash
python test_mcp_client.py
```

Or manually with curl:

```bash
# Connect to SSE endpoint
curl -N -H "Accept: text/event-stream" https://wikidata-mcp-mirror.onrender.com/messages/

# Send a message (replace SESSION_ID with the one received from the SSE endpoint)
curl -X POST "https://wikidata-mcp-mirror.onrender.com/messages/?session_id=YOUR_SESSION_ID" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-client","version":"0.1.0"}},"id":0}'
```

## Deployment on Render.com

This server is configured for deployment on Render.com using the `render.yaml` file.

### Deployment Configuration

- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn -k uvicorn.workers.UvicornWorker server_sse:app`
- **Environment Variables**:
  - `PORT`: 10000
- **Health Check Path**: `/health`

### Docker Support

The repository includes a Dockerfile that's used by Render.com for containerized deployment. This allows the server to run in a consistent environment with all dependencies properly installed.

### How to Deploy

1. Fork or clone this repository to your GitHub account
2. Create a new Web Service on Render.com
3. Connect your GitHub repository
4. Render will automatically detect the `render.yaml` file and configure the deployment
5. Click "Create Web Service"

After deployment, you can access your server at the URL provided by Render.com.

## Architecture

The server is built using:

- **FastAPI**: For handling HTTP requests and routing
- **SSE Transport**: For bidirectional communication with clients
- **MCP Framework**: For implementing the Model Context Protocol
- **Wikidata API**: For accessing Wikidata's knowledge base

### Key Components

- `server_sse.py`: Main server implementation with SSE transport
- `wikidata_api.py`: Functions for interacting with Wikidata's API and SPARQL endpoint
- `requirements.txt`: Dependencies for the project
- `Dockerfile`: Container configuration for Docker deployment on Render
- `render.yaml`: Configuration for deployment on Render.com
- `test_mcp_client.py`: Test client for verifying server functionality

## Available MCP Tools

The server provides the following MCP tools:

- `search_wikidata_entity`: Search for entities by name
- `search_wikidata_property`: Search for properties by name
- `get_wikidata_metadata`: Get entity metadata (label, description)
- `get_wikidata_properties`: Get all properties for an entity
- `execute_wikidata_sparql`: Execute a SPARQL query
- `find_entity_facts`: Search for an entity and find its facts
- `get_related_entities`: Find entities related to a given entity

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Based on the Model Context Protocol (MCP) specification
- Uses Wikidata as the knowledge source
- Inspired by the MCP examples from the official documentation
