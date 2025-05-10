# Wikidata MCP

Este paquete proporciona acceso a Wikidata a través del Model Context Protocol (MCP) para Goose y Claude Desktop.

## ¿Qué es esto?

Este paquete permite a Goose y Claude Desktop conectarse a un servidor MCP de Wikidata, lo que les da la capacidad de:

- Buscar entidades y propiedades en Wikidata
- Obtener metadatos de entidades
- Ejecutar consultas SPARQL
- Acceder a información estructurada sobre millones de conceptos

## Opciones de instalación

Hay varias formas de configurar Goose o Claude Desktop para usar nuestro servidor Wikidata MCP:

### Para Goose

#### Opción 1: Conexión directa (Recomendada)

Puedes conectarte directamente al servidor MCP usando el comando `--with-remote-extension`:

```bash
goose session --with-remote-extension https://wikidata-mcp.onrender.com/sse
```

O para ejecutar un comando específico:

```bash
goose run -t "wikidata, quiénes son los últimos 3 papas?" --with-remote-extension https://wikidata-mcp.onrender.com/sse
```

#### Opción 2: Usando nuestro paquete npm

1. Instala nuestro paquete globalmente:
   ```bash
   npm install -g wikidata-mcp
   ```

2. Usa el comando `wikidata-mcp` como extensión:
   ```bash
   goose session --with-extension "wikidata-mcp"
   ```

### Para Claude Desktop

#### Opción 1: Configuración directa

Esta opción no requiere instalar nuestro paquete npm. Simplemente configura Claude Desktop para usar el paquete `mcp-remote` para conectarse directamente a nuestro servidor.

1. Asegúrate de tener [Node.js](https://nodejs.org) instalado en tu computadora.

2. Edita el archivo de configuración de Claude Desktop:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`

3. Reemplaza el contenido del archivo con:

```json
{
  "mcp": {
    "command": "npx",
    "args": [
      "mcp-remote",
      "--url",
      "https://wikidata-mcp.onrender.com/sse"
    ]
  }
}
```

4. Reinicia Claude Desktop.

#### Opción 2: Usando nuestro paquete npm

Si prefieres usar nuestro paquete npm, sigue estos pasos:

1. Instala nuestro paquete globalmente:
   ```bash
   npm install -g wikidata-mcp
   ```

2. Edita el archivo de configuración de Claude Desktop:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`

3. Reemplaza el contenido del archivo con:

```json
{
  "mcp": {
    "command": "wikidata-mcp"
  }
}
```

4. Reinicia Claude Desktop.

## Solución de problemas

### Para Goose

Si tienes problemas para conectarte al servidor Wikidata MCP con Goose, prueba lo siguiente:

1. Asegúrate de estar usando la URL correcta con el endpoint `/sse`: `https://wikidata-mcp.onrender.com/sse`
2. Verifica que Node.js esté instalado correctamente ejecutando `node --version` en tu terminal.
3. Intenta ejecutar Goose con la bandera `--debug` para ver más información sobre la conexión.
4. Asegúrate de que no haya otras instancias de Goose ejecutándose (usa `pkill -f goose` para terminar todos los procesos).

### Para Claude Desktop

Si tienes problemas para conectarte al servidor Wikidata MCP con Claude Desktop, prueba lo siguiente:

1. Asegúrate de tener la última versión de Claude Desktop.
2. Verifica que Node.js esté instalado correctamente ejecutando `node --version` en tu terminal.
3. Verifica la sintaxis de tu archivo `claude_desktop_config.json`.
4. Reinicia completamente Claude Desktop.
5. Revisa los logs de Claude Desktop:
   - macOS: `~/Library/Logs/Claude/mcp*.log`
   - Windows: `%APPDATA%\Claude\logs\mcp*.log`

## Licencia

MIT
