#!/usr/bin/env node

const { spawn } = require('child_process');
const path = require('path');

// URL de nuestro servidor MCP en Render (oculta para los usuarios)
const SERVER_URL = "https://wikidata-mcp.onrender.com/sse";

// No imprimir mensajes que puedan confundir a Claude Desktop
// console.log(`Connecting to Wikidata MCP Server...`);
// console.log(`This client allows Claude to access and query Wikidata's structured knowledge base.`);

try {
  // Ejecutar mcp-remote con la URL de nuestro servidor
  // Basado en la documentación oficial de MCP
  // Usar la estrategia SSE-only directamente para evitar el intento HTTP-first
  const mcpProcess = spawn('npx', ['-y', 'mcp-remote', SERVER_URL, '--transport', 'sse-only'], { 
    stdio: 'inherit',
    shell: true
  });

  // Manejar el cierre del proceso
  mcpProcess.on('close', (code) => {
    if (code !== 0) {
      console.error(`mcp-remote exited with code ${code}`);
      process.exit(code);
    }
  });

  // Manejar errores
  mcpProcess.on('error', (err) => {
    console.error('Error connecting to Wikidata MCP Server:', err.message);
    process.exit(1);
  });

  // Manejar señales para cerrar limpiamente
  process.on('SIGINT', () => {
    mcpProcess.kill('SIGINT');
  });
  
  process.on('SIGTERM', () => {
    mcpProcess.kill('SIGTERM');
  });
} catch (error) {
  console.error('Error connecting to Wikidata MCP Server:', error.message);
  process.exit(1);
}
