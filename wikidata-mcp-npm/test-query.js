#!/usr/bin/env node

const { spawn } = require('child_process');
const path = require('path');
const net = require('net');
const { randomBytes } = require('crypto');

// Generate a unique ID for this session
const sessionId = randomBytes(8).toString('hex');

// The MCP server URL
const SERVER_URL = "https://wikidata-mcp-mirror.onrender.com/sse";

// Test queries to run
const TEST_QUERIES = [
  {
    name: 'SPARQL Query Test',
    method: 'execute',
    params: {
      toolName: 'execute_wikidata_sparql',
      toolInput: {
        sparql_query: `
          SELECT ?item ?itemLabel ?birth ?death ?successor ?successorLabel WHERE {
            ?item wdt:P39 wd:Q19546.
            ?item rdfs:label "Pope Francis"@en.
            OPTIONAL { ?item wdt:P569 ?birth. }
            OPTIONAL { ?item wdt:P570 ?death. }
            OPTIONAL { ?item wdt:P1366 ?successor. }
            SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
          }
        `
      }
    }
  },
  {
    name: 'Entity Facts Test',
    method: 'execute',
    params: {
      toolName: 'find_entity_facts',
      toolInput: {
        entity_name: 'Pope Francis'
      }
    }
  }
];

// Start the MCP client process
console.log('Starting MCP client...');
const mcpProcess = spawn('node', ['bin/wikidata-mcp.js'], { 
  stdio: ['pipe', 'pipe', 'pipe'],
  cwd: __dirname
});

// Listen for output to detect when the client is ready
mcpProcess.stdout.on('data', (data) => {
  const output = data.toString();
  console.log(`MCP Client: ${output}`);
  
  // Look for the message indicating the client is ready
  if (output.includes('Proxy established successfully')) {
    console.log('MCP client is ready. Starting tests...');
    runTests();
  }
});

mcpProcess.stderr.on('data', (data) => {
  console.error(`MCP Client Error: ${data}`);
});

// Function to run the test queries
async function runTests() {
  try {
    // Find the port from the output
    const port = 3334; // Default port used by mcp-remote
    
    // Run each test query
    for (const test of TEST_QUERIES) {
      console.log(`\n=== Running Test: ${test.name} ===\n`);
      
      // Create a JSON-RPC request
      const request = {
        jsonrpc: '2.0',
        id: Math.floor(Math.random() * 1000),
        method: test.method,
        params: test.params
      };
      
      // Send the request to the MCP client
      const result = await sendRequest(port, request);
      console.log(`\nResult: ${JSON.stringify(result, null, 2)}\n`);
    }
    
    console.log('All tests completed.');
    mcpProcess.kill();
    process.exit(0);
  } catch (error) {
    console.error('Error running tests:', error);
    mcpProcess.kill();
    process.exit(1);
  }
}

// Function to send a request to the MCP client
function sendRequest(port, request) {
  return new Promise((resolve, reject) => {
    const client = new net.Socket();
    let responseData = '';
    
    client.connect(port, '127.0.0.1', () => {
      console.log(`Connected to MCP client on port ${port}`);
      client.write(JSON.stringify(request) + '\n');
    });
    
    client.on('data', (data) => {
      responseData += data.toString();
      
      // Check if we have a complete response
      try {
        const response = JSON.parse(responseData);
        client.end();
        resolve(response);
      } catch (e) {
        // Not a complete JSON object yet, continue reading
      }
    });
    
    client.on('error', (error) => {
      console.error(`Socket error: ${error.message}`);
      client.end();
      reject(error);
    });
    
    client.on('close', () => {
      if (responseData) {
        try {
          const response = JSON.parse(responseData);
          resolve(response);
        } catch (e) {
          reject(new Error(`Invalid JSON response: ${responseData}`));
        }
      } else {
        reject(new Error('Connection closed without response'));
      }
    });
    
    // Set a timeout
    setTimeout(() => {
      client.end();
      reject(new Error('Request timed out'));
    }, 30000); // 30 second timeout
  });
}
