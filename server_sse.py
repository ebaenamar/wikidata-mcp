"""
Wikidata MCP Server with SSE Transport

This module implements a Model Context Protocol (MCP) server with SSE transport
that connects Large Language Models to Wikidata's structured knowledge base.
"""
import os
import json
import asyncio
import anyio
import uvicorn
import traceback
import re
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from mcp.server.sse import SseServerTransport
from mcp.server.fastmcp import FastMCP
from datetime import datetime
from uuid import uuid4
from SPARQLWrapper import SPARQLWrapper, JSON

from mcp.server.fastmcp.prompts import base
from starlette.routing import Route, Mount
from wikidata_api import (
    search_entity,
    search_property,
    get_entity_metadata,
    get_entity_properties,
    execute_sparql
)

# Initialize FastMCP
mcp = FastMCP(name="Wikidata Knowledge")

# ============= MCP TOOLS =============

@mcp.tool()
def search_wikidata_entity(query: str) -> str:
    """
    Search for a Wikidata entity by name.
    
    Args:
        query: The name of the entity to search for (e.g., "Albert Einstein")
        
    Returns:
        The Wikidata entity ID (e.g., Q937) or an error message
    """
    result = search_entity(query)
    if isinstance(result, str) and result.startswith("Error searching for entity:"):
        return json.dumps({
            "error": "Failed to search Wikidata entity.",
            "details": result,
            "suggestion": "Check your network connection or try a different search query."
        })
    if result == "No entity found":
        return json.dumps({
            "error": "No entity found on Wikidata.",
            "details": f"The query '{query}' did not return any results.",
            "suggestion": "Try alternative spellings, more general or specific terms, or ensure the entity exists on Wikidata."
        })
    return result # Expected to be an entity ID string if successful

@mcp.tool()
def search_wikidata_property(query: str) -> str:
    """
    Search for a Wikidata property by name.
    
    Args:
        query: The name of the property to search for (e.g., "instance of")
        
    Returns:
        The Wikidata property ID (e.g., P31) or an error message
    """
    result = search_property(query)
    if isinstance(result, str) and result.startswith("Error searching for property:"):
        return json.dumps({
            "error": "Failed to search Wikidata property.",
            "details": result,
            "suggestion": "Check your network connection or try a different search query."
        })
    if result == "No property found":
        return json.dumps({
            "error": "No property found on Wikidata.",
            "details": f"The query '{query}' did not return any results for a property.",
            "suggestion": "Try alternative spellings, or ensure the property exists on Wikidata (e.g., check common properties list)."
        })
    return result # Expected to be a property ID string if successful

@mcp.tool()
def get_wikidata_metadata(entity_id: str) -> str:
    """
    Get metadata (label and description) for a Wikidata entity.
    
    Args:
        entity_id: The Wikidata entity ID (e.g., Q937)
        
    Returns:
        JSON string containing the entity's label and description
    """
    metadata = get_entity_metadata(entity_id)
    if isinstance(metadata, dict) and "error" in metadata:
        return json.dumps({
            "error": f"Failed to get metadata for entity ID '{entity_id}'.",
            "details": metadata["error"],
            "suggestion": "The entity ID might be invalid, the entity may not exist, or there could be an issue with the metadata service."
        })
    return json.dumps(metadata)

@mcp.tool()
def get_wikidata_properties(entity_id: str) -> str:
    """
    Get all properties for a Wikidata entity.
    
    Args:
        entity_id: The Wikidata entity ID (e.g., Q937)
        
    Returns:
        JSON string containing the entity's properties and their values
    """
    # get_entity_properties calls execute_sparql internally.
    # The execute_sparql in wikidata_api.py now returns detailed JSON errors.
    # This tool calls wikidata_api.get_entity_properties, which in turn calls wikidata_api.execute_sparql
    # So, we need to handle the JSON string that might be an error.

    properties_json_str = get_entity_properties(entity_id)
    try:
        properties_data = json.loads(properties_json_str)

        # Check if the parsed data itself is an error structure from execute_sparql
        if isinstance(properties_data, dict) and 'error' in properties_data and 'error_type' in properties_data:
            # This is an error from execute_sparql, propagated by get_entity_properties
            error_type = properties_data.get('error_type')
            suggestion = "Review the error details. If it's a query issue, the default query for properties might be failing for this entity."
            if error_type == "QueryBadFormed":
                suggestion = "The underlying SPARQL query for fetching properties might be malformed (unlikely for default queries) or there's an issue with the entity ID affecting the query."
            elif error_type == "Timeout" or error_type == "ConnectionError" or error_type == "MaxRetriesExceeded":
                suggestion = "Fetching properties failed due to network issues or timeout. Please try again later."

            return json.dumps({
                "error": f"Failed to get properties for entity ID '{entity_id}'.",
                "details": properties_data.get('error'),
                "error_type": error_type,
                "original_query": properties_data.get('query'),
                "suggestion": suggestion
            })
        # If not an error from execute_sparql, assume it's the actual properties data or a simpler error from get_entity_properties itself
        return properties_json_str # Return the original JSON string which might be data or a simple error

    except json.JSONDecodeError:
        # This means get_entity_properties returned something that was not JSON at all.
        return json.dumps({
            "error": "Received non-JSON response when fetching entity properties.",
            "details": properties_json_str, # Show what was received
            "suggestion": "This indicates an unexpected response format from the properties retrieval function."
        })

@mcp.tool("execute_wikidata_sparql")
def execute_wikidata_sparql(sparql_query: str) -> str:
    """
    Execute a SPARQL query against Wikidata.
    
    Args:
        sparql_query: The SPARQL query to execute.
        
    Returns:
        The results of the SPARQL query.
    """
    validation_result = _validate_sparql_query(sparql_query)
    if not validation_result["is_valid"]:
        return json.dumps({
            "error": "SPARQL query validation failed",
            "details": validation_result["error"],
            "suggestion": validation_result["suggestion"]
        })

    try:
        # Use the imported execute_sparql function from wikidata_api.py
        raw_result = execute_sparql(sparql_query)
        
        # Attempt to parse the result as JSON
        try:
            result_data = json.loads(raw_result)
        except json.JSONDecodeError:
            # If it's not JSON, it might be a raw non-JSON error string (less likely from current wikidata_api)
            # or a successful result that's not JSON (also unlikely for SPARQL results)
            return json.dumps({
                "error": "Received non-JSON response from SPARQL execution.",
                "details": raw_result,
                "suggestion": "Check the SPARQL endpoint or the API's response format."
            })

        # Check if the parsed result contains an error from wikidata_api.py
        if isinstance(result_data, dict) and 'error' in result_data and 'error_type' in result_data:
            error_msg = result_data.get('error', 'Unknown error from wikidata_api')
            error_type = result_data.get('error_type', 'UnknownErrorType')
            original_query = result_data.get('query', sparql_query) # Fallback to input query
            # traceback_info = result_data.get('traceback', 'No traceback available.') # Keep traceback internal for now

            suggestion = "Please review your query and the error details."

            if error_type == "QueryBadFormed":
                suggestion = "The SPARQL query syntax is incorrect. Please check for typos, keyword misuse, or structural issues. Refer to SPARQL documentation or use a SPARQL validator for assistance."
            elif error_type == "Timeout":
                suggestion = "The query execution timed out. Try simplifying the query, adding or adjusting LIMIT/OFFSET clauses, or reducing its complexity. Executing it at a later time might also help."
            elif error_type == "ConnectionError":
                suggestion = "A network connection error occurred while trying to reach the SPARQL endpoint. Please check your internet connection and try again later."
            elif error_type == "MaxRetriesExceeded":
                original_error_type = result_data.get('original_error_type', 'transient issues')
                suggestion = f"The query failed after multiple retries due to repeated '{original_error_type}'. This could be due to network issues or endpoint overload. Try again later. Original error: {error_msg}"
            elif "Error executing query" in error_msg: # General catch from wikidata_api if error_type was not more specific
                suggestion = "An error occurred during query execution. Check the syntax and ensure all identifiers (URIs, variables) are correct."

            # Log the full error for server-side diagnosis
            print(f"SPARQL Query Error (from execute_wikidata_sparql tool): {json.dumps(result_data)}")

            return json.dumps({
                "error": "SPARQL query execution failed.",
                "original_error_message": error_msg,
                "error_type": error_type,
                "query": original_query,
                "suggestion": suggestion
                # "traceback": traceback_info # Exposing traceback to client is optional, often better to keep server-side
            })

        # If no 'error' key with 'error_type', assume success and return the raw_result (which is a JSON string)
        return raw_result

    except Exception as e:
        # This catches errors from the execute_sparql call itself if it raises an exception
        # before returning a JSON error string (e.g., programming error in this tool, not from wikidata_api)
        error_message = str(e)
        print(f"Exception in execute_wikidata_sparql: {error_message}")
        
        # Provide more helpful error messages for common issues
        if "Lexical error" in error_message and "Encountered: " in error_message:
            return json.dumps({"error": f"SPARQL syntax error: {error_message}. Check for unescaped quotes or special characters."})
        return json.dumps({"error": f"Error executing SPARQL query: {error_message}"})

# Helper function for SPARQL validation
def _validate_sparql_query(query: str) -> dict:
    """
    Validates a SPARQL query for common syntax issues.

    Args:
        query: The SPARQL query string.

    Returns:
        A dictionary with "is_valid": True, or "is_valid": False
        and error/suggestion messages.
    """
    # 1. Check for unbalanced parentheses, brackets, and curly braces
    brackets_map = {"(": ")", "[": "]", "{": "}"}
    open_brackets = []
    for char in query:
        if char in brackets_map:
            open_brackets.append(char)
        elif char in brackets_map.values():
            if not open_brackets or brackets_map[open_brackets.pop()] != char:
                return {
                    "is_valid": False,
                    "error": f"Unbalanced closing bracket/parenthesis/brace: '{char}'",
                    "suggestion": "Ensure all opening brackets, parentheses, and braces have a matching closing one in the correct order."
                }
    if open_brackets:
        return {
            "is_valid": False,
            "error": f"Unclosed opening bracket/parenthesis/brace: '{open_brackets[-1]}'",
            "suggestion": "Ensure all opening brackets, parentheses, and braces are closed."
        }

    # 2. Validate common keywords (case-insensitive)
    # SELECT keyword
    if re.search(r"SELECT\s*(?![?*\w(])", query, re.IGNORECASE):
        return {
            "is_valid": False,
            "error": "Invalid SELECT clause.",
            "suggestion": "SELECT keyword should be followed by variables (e.g., ?var), '*', or aggregate functions (e.g., COUNT(?var))."
        }

    # WHERE keyword
    if re.search(r"WHERE\s*(?!\{)", query, re.IGNORECASE) and not re.search(r"WHERE\s*DATA\s*\{", query, re.IGNORECASE) :
         # The second part of the condition is to allow WHERE DATA { ... }
        return {
            "is_valid": False,
            "error": "Invalid WHERE clause.",
            "suggestion": "WHERE keyword should be followed by a graph pattern enclosed in curly braces {} (e.g., WHERE { ?s ?p ?o . })."
        }
    if "WHERE" in query and not (query.count("{") >= query.count("WHERE") and query.count("}") >= query.count("WHERE")):
        # Basic check, might need refinement for complex queries with nested blocks
        # This is a simplified check. A proper parser would be needed for full accuracy.
        pass # Covered by general brace checking, but good to keep in mind.

    # PREFIX keyword
    if re.search(r"PREFIX\s+\w*:\s*(?!<)", query, re.IGNORECASE):
        return {
            "is_valid": False,
            "error": "Invalid PREFIX declaration.",
            "suggestion": "PREFIX declarations should use URIs enclosed in < > (e.g., PREFIX foaf: <http://xmlns.com/foaf/0.1/>)."
        }
    if re.search(r"PREFIX\s+\w*:\s*<[^>]*$", query, re.IGNORECASE): # Missing closing >
        return {
            "is_valid": False,
            "error": "Incomplete URI in PREFIX declaration.",
            "suggestion": "Ensure URIs in PREFIX declarations are properly closed with '>'."
        }

    # FILTER keyword
    # Check for FILTER NOT EXISTS { ... } or FILTER EXISTS { ... } - these are valid
    if re.search(r"FILTER\s*\((?!\s*(NOT\s+EXISTS|EXISTS)\s*\{)", query, re.IGNORECASE):
        # This regex checks for FILTER (...) but excludes FILTER (EXISTS {...}) and FILTER (NOT EXISTS {...})
        # It aims to find filters that should have content inside the parentheses.
        if re.search(r"FILTER\s*\(\s*\)", query, re.IGNORECASE): # Empty FILTER ()
            return {
                "is_valid": False,
                "error": "Empty FILTER clause.",
                "suggestion": "FILTER clauses must contain an expression (e.g., FILTER(?age > 18))."
            }
        # Check for common issues like missing operators or operands if not an EXISTS/NOT EXISTS
        # Example: FILTER(?x = ) or FILTER( = ?y) or FILTER(?x >)
        if re.search(r"FILTER\s*\([^)]*[=<>!]+\s*\)", query, re.IGNORECASE) or \
           re.search(r"FILTER\s*\([^)]*\s*[=<>!]+\s*[^)\w?\"']", query, re.IGNORECASE): # Operand missing after operator
             pass # This is complex to get right with regex, can lead to false positives.
                  # The QueryBadFormed exception from SPARQLWrapper is often better for these.

    # LIMIT / OFFSET keywords
    if re.search(r"(LIMIT|OFFSET)\s+(?!\d+)", query, re.IGNORECASE):
        return {
            "is_valid": False,
            "error": "Invalid LIMIT or OFFSET clause.",
            "suggestion": "LIMIT and OFFSET keywords must be followed by a non-negative integer."
        }

    # ORDER BY keyword
    if re.search(r"ORDER\s+BY\s+(?!(ASC|DESC)\s*\(|\?\w+|IRI|STR|LANG|DATATYPE)", query, re.IGNORECASE):
        return {
            "is_valid": False,
            "error": "Invalid ORDER BY clause.",
            "suggestion": "ORDER BY should be followed by a variable (e.g., ?name), or a function call like ASC(?date) or DESC(?value)."
        }

    # GROUP BY keyword
    if re.search(r"GROUP\s+BY\s+(?!\?\w+)", query, re.IGNORECASE):
        return {
            "is_valid": False,
            "error": "Invalid GROUP BY clause.",
            "suggestion": "GROUP BY should be followed by one or more variables (e.g., GROUP BY ?type)."
        }

    # 3. Check for potentially problematic characters or patterns
    # Example: Unescaped quotes within strings if not handled by bracket checker
    # This is tricky with regex. The SPARQL parser itself is the best validator here.
    # However, we can check for some obvious cases.

    # Check for an odd number of quotes (could indicate unclosed string literals)
    # This is a simplified check and might not cover all edge cases (e.g., escaped quotes within strings)
    if query.count('"') % 2 != 0:
        # Further check if it's part of a lang tag or datatype
        if not re.search(r'@[a-zA-Z]{2,}(?:-[a-zA-Z0-9]+)*\s*(")', query) and not re.search(r'\^\^<[^>]*>\s*(")', query):
             # Check if the quote is inside a comment
            clean_query_for_quotes = re.sub(r"#.*$", "", query, flags=re.MULTILINE) # Remove comments
            if clean_query_for_quotes.count('"') % 2 != 0:
                return {
                    "is_valid": False,
                    "error": "Unbalanced double quotes.",
                    "suggestion": "Ensure all string literals using double quotes are properly opened and closed. Escape internal quotes if necessary (e.g., \\\" )."
                }

    if query.count("'") % 2 != 0:
        clean_query_for_quotes = re.sub(r"#.*$", "", query, flags=re.MULTILINE) # Remove comments
        if clean_query_for_quotes.count("'") % 2 != 0:
            return {
                "is_valid": False,
                "error": "Unbalanced single quotes.",
                "suggestion": "Ensure all string literals using single quotes are properly opened and closed. Escape internal quotes if necessary (e.g., \\' )."
            }

    # Check for common triple pattern mistakes like missing dots (heuristic)
    # This is a very basic heuristic and might not be perfectly accurate.
    # It looks for lines ending with a variable/literal that are likely part of a triple pattern but miss a dot.
    # Needs to be careful about not flagging lines ending with { or ( or prefixes etc.
    lines = query.splitlines()
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        # Check if line seems like a triple but doesn't end with '.', ';', ',', '{', or '}'
        # and is not a PREFIX, BASE, SELECT, etc.
        if stripped_line and not stripped_line.endswith(('.', ';', ',', '{', '}')) \
           and not stripped_line.lower().startswith(("prefix", "base", "select", "construct", "describe", "ask", "#", "optional", "filter", "minus", "graph", "service", "bind", "values", "limit", "offset", "order by", "group by", "having")) \
           and (re.search(r"(\?\w+|\w+:\w+|\"[^\"]*\"|\'[^\']*\')\s*$", stripped_line)):
            # Check if the next non-empty line starts with a variable or keyword that would typically start a new triple pattern
            if i + 1 < len(lines):
                next_stripped_line = lines[i+1].strip()
                if next_stripped_line and (next_stripped_line.startswith("?") or next_stripped_line.lower().split(" ")[0] in ["filter", "optional", "minus", "bind", "values", "graph", "service"]):
                     # This is a potential missing dot if the current line is part of a triple pattern
                     # However, it could also be a list or part of a complex path expression.
                     # This rule is prone to false positives, so disabling for now.
                     # return {
                     # "is_valid": False,
                     # "error": f"Potential missing dot '.' or other separator at the end of a triple pattern.",
                     # "suggestion": f"Check line: '{stripped_line}'. Triple patterns usually end with a dot (.), semicolon (;), or comma (,)."
                     # }
                    pass


    return {"is_valid": True}


@mcp.tool()
def find_entity_facts(entity_name: str, property_name: str = None) -> str:
    """
    Search for an entity and find its facts, optionally filtering by a property.
    
    Args:
        entity_name: The name of the entity to search for
        property_name: Optional name of a property to filter by
        
    Returns:
        A JSON string containing the entity facts
    """
    # Search for the entity (using the already improved search_wikidata_entity tool)
    entity_id_json_str = search_wikidata_entity(entity_name)
    try:
        entity_id_data = json.loads(entity_id_json_str)
        if isinstance(entity_id_data, dict) and "error" in entity_id_data:
            return entity_id_json_str # Propagate error from search_wikidata_entity
        entity_id = entity_id_json_str # If not a dict with error, it's the ID string
    except json.JSONDecodeError:
        # search_wikidata_entity should return entity ID string or JSON error string
        entity_id = entity_id_json_str # Assume it's the ID string

    # Get metadata (using the already improved get_wikidata_metadata tool)
    metadata_json_str = get_wikidata_metadata(entity_id)
    try:
        metadata = json.loads(metadata_json_str)
        if isinstance(metadata, dict) and "error" in metadata:
             # Augment with context if needed, or just propagate
            metadata["context"] = f"Error fetching metadata for entity '{entity_name}' (ID: {entity_id})."
            return json.dumps(metadata)
    except json.JSONDecodeError:
        return json.dumps({
            "error": "Failed to parse metadata response.",
            "details": metadata_json_str,
            "suggestion": "Metadata service might have returned an unexpected format."
        })

    # If a property is specified, search for it (using the already improved search_wikidata_property tool)
    property_id = None
    if property_name:
        property_id_json_str = search_wikidata_property(property_name)
        try:
            property_id_data = json.loads(property_id_json_str)
            if isinstance(property_id_data, dict) and "error" in property_id_data:
                # Property search failed, return error with entity context
                return json.dumps({
                    "entity_found": metadata, # Provide context of what was found
                    "error_searching_property": property_id_data,
                    "suggestion": f"Could not find property '{property_name}' while looking up facts for '{entity_name}'."
                })
            property_id = property_id_json_str # If not a dict with error, it's the ID string
        except json.JSONDecodeError:
            property_id = property_id_json_str # Assume it's the ID string
    
    # Build and execute SPARQL query
    if property_id:
        # Specific property query
        sparql_query = f"""
        SELECT ?value ?valueLabel
        WHERE {{
          wd:{entity_id} wdt:{property_id} ?value.
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}
        """
    else:
        # General entity info query
        sparql_query = f"""
        # General entity info: Fetch core data then labels for efficiency.
        SELECT ?property ?propertyLabel ?value ?valueLabel
        WHERE {{
          {{
            SELECT ?property ?value
            WHERE {{
              wd:{entity_id} ?p ?statement.
              ?statement ?ps ?value.

              ?property wikibase:claim ?p.
              ?property wikibase:statementProperty ?ps.
            }}
            LIMIT 10
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}
        """
    
    # Get facts using the tool's execute_wikidata_sparql which has enhanced error handling
    facts_json_str = execute_wikidata_sparql(sparql_query)
    
    try:
        facts_data = json.loads(facts_json_str)
        # If facts_data contains an error (already processed by execute_wikidata_sparql),
        # it will be propagated as is. This is desired.
    except json.JSONDecodeError:
        # This should ideally not happen if execute_wikidata_sparql always returns valid JSON
        return json.dumps({
            "error": "Failed to parse SPARQL result from internal call to execute_wikidata_sparql.",
            "details": "The response from execute_wikidata_sparql was not valid JSON.",
            "context": {"entity_id": entity_id, "property_id": property_id, "query": sparql_query},
            "suggestion": "This indicates an internal issue with the server's SPARQL execution tool chain."
        })
    
    # Combine all results
    result = {
        "entity": metadata,
        "property": {"id": property_id, "name": property_name} if property_id else None,
        "facts": facts_data
    }
    
    # Return as JSON string
    return json.dumps(result)

@mcp.tool()
def get_related_entities(entity_id: str, relation_property: str = None, limit: int = 10) -> str:
    """
    Find entities related to the given entity, optionally by a specific relation.
    
    Args:
        entity_id: The Wikidata entity ID (e.g., Q937)
        relation_property: Optional Wikidata property ID for the relation (e.g., P31)
        limit: Maximum number of results to return
        
    Returns:
        JSON string containing related entities
    """
    if relation_property:
        # Query for specific relation
        sparql_query = f"""
        SELECT ?related ?relatedLabel
        WHERE {{
          wd:{entity_id} wdt:{relation_property} ?related.
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}
        LIMIT {limit}
        """
    else:
        # Query for any relation
        sparql_query = f"""
        # Find related entities: Apply LIMIT before fetching labels.
        SELECT ?relation ?relationLabel ?related ?relatedLabel
        WHERE {{
          {{
            SELECT ?relation ?related
            WHERE {{
              wd:{entity_id} ?p ?related.
              ?property wikibase:directClaim ?p.
              BIND(?property as ?relation)
              # Ensure ?related is a Wikidata entity
              FILTER(STRSTARTS(STR(?related), "http://www.wikidata.org/entity/"))
            }}
            LIMIT {limit}
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}
        """
    
    # Get related entities using the tool's execute_wikidata_sparql for robust error handling
    related_entities_json_str = execute_wikidata_sparql(sparql_query)

    try:
        # Attempt to parse to ensure it's valid JSON, but return the string
        # as execute_wikidata_sparql already formats errors or results correctly.
        json.loads(related_entities_json_str)
    except json.JSONDecodeError:
        return json.dumps({
            "error": "Failed to parse SPARQL result from internal call to execute_wikidata_sparql for related entities.",
            "details": "The response was not valid JSON.",
            "context": {"entity_id": entity_id, "relation_property": relation_property, "query": sparql_query},
            "suggestion": "This indicates an internal issue with the server's SPARQL execution tool chain."
        })
    
    # Return the JSON string (which might be an error JSON from execute_wikidata_sparql or actual results)
    return related_entities_json_str

# ============= MCP RESOURCES =============

@mcp.resource("wikidata://common-properties")
def common_properties_resource():
    """
    Provides a list of commonly used Wikidata properties.
    """
    return {
        "properties": {
            "P31": "instance of",
            "P279": "subclass of",
            "P569": "date of birth",
            "P570": "date of death",
            "P21": "sex or gender",
            "P27": "country of citizenship",
            "P106": "occupation",
            "P17": "country",
            "P131": "located in administrative entity",
            "P50": "author",
            "P57": "director",
            "P136": "genre",
            "P577": "publication date",
            "P580": "start time",
            "P582": "end time",
            "P361": "part of",
            "P527": "has part",
            "P39": "position held",
            "P800": "notable work",
            "P1412": "languages spoken, written or signed"
        },
        "description": "Common Wikidata properties that can be used to query for specific information about entities."
    }

@mcp.resource("wikidata://sparql-examples")
def sparql_examples_resource():
    """
    Provides example SPARQL queries for common Wikidata tasks.
    """
    return {
        "examples": [
            {
                "name": "Basic entity information",
                "query": """
                # Basic entity information: Subquery for labels after LIMIT.
                SELECT ?property ?propertyLabel ?value ?valueLabel
                WHERE {
                  {
                    SELECT ?property ?value
                    WHERE {
                      wd:Q937 ?p ?statement.  # Q937 = Albert Einstein
                      ?statement ?ps ?value.

                      ?property wikibase:claim ?p.
                      ?property wikibase:statementProperty ?ps.
                    }
                    LIMIT 10
                  }
                  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                }
                """
            },
            {
                "name": "Find all scientists",
                "query": """
                SELECT ?scientist ?scientistLabel
                WHERE {
                  ?scientist wdt:P106 wd:Q901.  # P106 = occupation, Q901 = scientist
                  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                }
                LIMIT 20
                """
            },
            {
                "name": "Find books by an author",
                "query": """
                # Find books by an author: Prioritize specific author link before type check.
                SELECT ?book ?bookLabel
                WHERE {
                  ?book wdt:P50 wd:Q535.  # P50 = author, Q535 = Isaac Asimov
                  # Check if it's a book (instance of book or subclass of book)
                  ?book wdt:P31/wdt:P279* wd:Q571.
                  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                }
                """
            },
            {
                "name": "Find capitals of countries",
                "query": """
                SELECT ?country ?countryLabel ?capital ?capitalLabel
                WHERE {
                  ?country wdt:P31 wd:Q6256.  # P31 = instance of, Q6256 = country
                  ?country wdt:P36 ?capital.  # P36 = capital
                  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                }
                """
            },
            {
                "name": "Find mountains higher than 8000m",
                "query": """
                # Find mountains higher than 8000m: Prioritize height filter before type check.
                SELECT ?mountain ?mountainLabel ?height
                WHERE {
                  ?mountain wdt:P2044 ?height.  # P2044 = elevation above sea level
                  FILTER(?height > 8000)
                  # Ensure it's a mountain (instance of mountain or subclass of mountain)
                  ?mountain wdt:P31/wdt:P279* wd:Q8502.
                  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                }
                ORDER BY DESC(?height)
                """
            }
        ],
        "description": "Example SPARQL queries for common Wikidata tasks. These can be used as templates for more specific queries."
    }

# ============= PROMPT TEMPLATES =============

@mcp.prompt()
def position_holders_template(position_name: str, limit: int = 3) -> list[base.Message]:
    """
    Template for finding people who held a specific position, ordered by recency.
    """
    return [
        base.UserMessage(f"""
You need to find the {limit} most recent holders of the position "{position_name}" in Wikidata.

Follow these steps:
1. First, search for the position ID using search_wikidata_property.
2. Then, craft a SPARQL query to find people who held this position, ordered by start date (most recent first).
3. Use the following SPARQL pattern as a guide:

```
SELECT ?person ?personLabel ?startDate WHERE {{
  ?person p:P39 [
    ps:P39 wd:Q<position_id>;  # position held: <position>
    pq:P580 ?startDate  # start time
  ].
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY DESC(?startDate) LIMIT {limit}
```

4. Execute this query using execute_wikidata_sparql.
5. Format the results in a clear, readable way.
""")
    ]

@mcp.prompt()
def entity_search_template(entity_name: str) -> list[base.Message]:
    """
    Template for searching a Wikidata entity.
    """
    return [
        base.UserMessage(f"""
You need to find accurate and up-to-date information about {entity_name} using Wikidata as your primary source of truth.

IMPORTANT: Do NOT rely on your pre-trained knowledge about {entity_name}, which may be outdated or incorrect. Instead, use ONLY the data returned from Wikidata tools.

Follow these steps precisely:

1. First, search for the entity ID using search_wikidata_entity with the query "{entity_name}".
   - If multiple entities are found, analyze which one most likely matches the user's intent.
   - If no entity is found, try alternative spellings or more specific terms.

2. Once you have the entity ID (e.g., Q12345), get the metadata using get_wikidata_metadata.
   - This will provide you with the official label and description.

3. Get all properties for this entity using get_wikidata_properties.
   - This will give you a comprehensive set of facts about the entity.

4. For more specific information, execute a SPARQL query using execute_wikidata_sparql.
   - Use the common_properties_resource for reference on property IDs.
   - Refer to sparql_examples_resource for query patterns.

5. When presenting information to the user, cite Wikidata as your source and include the entity ID.

Remember: If the information isn't found in Wikidata, clearly state that you don't have that information rather than falling back to potentially outdated knowledge.
""")
    ]

@mcp.prompt()
def property_search_template(property_name: str) -> list[base.Message]:
    """
    Template for searching a Wikidata property.
    """
    return [
        base.UserMessage(f"""
You need to find accurate information about the Wikidata property "{property_name}" using only Wikidata's data.

IMPORTANT: Do NOT rely on your pre-trained knowledge about properties, as Wikidata's property system is specific and may differ from your training data. Use ONLY the data returned from Wikidata tools.

Follow these steps precisely:

1. First, search for the property ID using search_wikidata_property with the query "{property_name}".
   - Property IDs in Wikidata always start with 'P' followed by numbers (e.g., P31 for 'instance of').
   - If no property is found, try alternative terms or check the common_properties_resource.

2. Once you have the property ID (e.g., P31), use it in a SPARQL query with execute_wikidata_sparql to find entities with this property.
   - Example query structure:
     ```
     SELECT ?entity ?entityLabel WHERE {{
       ?entity wdt:P31 wd:Q5.  # Example: Find humans (Q5) using 'instance of' (P31)
       SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
     }}
     LIMIT 10
     ```
   - Replace P31 with your found property ID and adjust the query as needed.

3. Analyze the results to understand how this property is used in Wikidata.

4. When presenting information to the user, explain what the property represents and provide examples of entities that use this property.

Remember: If you cannot find the property in Wikidata, clearly state this rather than making assumptions based on your pre-trained knowledge.
""")
    ]

@mcp.prompt()
def entity_relation_template(entity1_name: str, entity2_name: str) -> list[base.Message]:
    """
    Template for finding relationships between entities.
    """
    return [
        base.UserMessage(f"""
You need to discover the factual relationships between {entity1_name} and {entity2_name} using Wikidata as your authoritative source.

IMPORTANT: Do NOT rely on your pre-trained knowledge about these entities or their relationships, which may be outdated, incomplete, or incorrect. Use ONLY the data returned from Wikidata tools.

Follow these steps precisely:

1. First, search for both entity IDs using search_wikidata_entity:
   - For the first entity: search_wikidata_entity("{entity1_name}")
   - For the second entity: search_wikidata_entity("{entity2_name}")
   - If either entity is not found, try alternative names or more specific terms.

2. Once you have both entity IDs (e.g., Q12345 and Q67890), get their metadata using get_wikidata_metadata to confirm you have the correct entities.

3. Execute a SPARQL query to find direct relationships between them:
   ```
   SELECT ?relation ?relationLabel WHERE {{
     wd:[ENTITY1_ID] ?p wd:[ENTITY2_ID].
     ?property wikibase:directClaim ?p.
     BIND(?property as ?relation)
     SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
   }}
   ```
   - Replace [ENTITY1_ID] and [ENTITY2_ID] with the actual entity IDs.
   - Also try the reverse direction by swapping the entity IDs.

4. If no direct relationship is found, look for indirect relationships:
   ```
   SELECT ?intermediateEntity ?intermediateEntityLabel ?relation1 ?relation1Label ?relation2 ?relation2Label WHERE {{
     wd:[ENTITY1_ID] ?p1 ?intermediateEntity.
     ?intermediateEntity ?p2 wd:[ENTITY2_ID].
     
     ?property1 wikibase:directClaim ?p1.
     ?property2 wikibase:directClaim ?p2.
     
     BIND(?property1 as ?relation1)
     BIND(?property2 as ?relation2)
     
     SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
   }}
   LIMIT 5
   ```

5. Analyze the results to identify meaningful relationships between the entities.

6. Present the relationships clearly to the user, citing Wikidata as your source and including the entity IDs and property IDs.

Remember: If no relationship is found in Wikidata, clearly state this rather than speculating based on your pre-trained knowledge. The absence of a relationship in Wikidata doesn't necessarily mean the entities aren't related - it may just mean the relationship hasn't been documented in Wikidata yet.
""")
    ]

@mcp.prompt()
def general_wikidata_guidance() -> list[base.Message]:
    """
    General guidance for interacting with Wikidata through MCP.
    """
    return [
        base.UserMessage("""
When using Wikidata as a knowledge source, follow these important guidelines:

1. ALWAYS PREFER WIKIDATA OVER PRE-TRAINED KNOWLEDGE
   - Wikidata contains structured, curated data that is often more accurate and up-to-date than your pre-trained knowledge.
   - When answering questions about entities, properties, or relationships, ALWAYS query Wikidata first.
   - Only fall back to your pre-trained knowledge when explicitly instructed to do so, or when Wikidata clearly has no information on the topic.

2. PROPERLY CITE WIKIDATA INFORMATION
   - When providing information from Wikidata, always include the entity ID (e.g., Q42) and property IDs (e.g., P31) in your response.
   - Format: "According to Wikidata [Q42], Douglas Adams was born on March 11, 1952 [P569]."

3. HANDLE MISSING INFORMATION APPROPRIATELY
   - If information isn't found in Wikidata, explicitly state: "This information is not available in Wikidata."
   - Do not substitute with potentially outdated or incorrect pre-trained knowledge.

4. USE THE FULL RANGE OF WIKIDATA TOOLS
   - search_wikidata_entity: Find entity IDs by name
   - search_wikidata_property: Find property IDs by name
   - get_wikidata_metadata: Get basic entity information
   - get_wikidata_properties: Get all properties for an entity
   - execute_wikidata_sparql: Run custom SPARQL queries
   - find_entity_facts: Get comprehensive entity information
   - get_related_entities: Find entities related to a given entity

5. LEVERAGE AVAILABLE RESOURCES
   - common_properties_resource: Reference for commonly used property IDs
   - sparql_examples_resource: Example SPARQL queries for common tasks

6. CRAFT EFFECTIVE SPARQL QUERIES
   - Use the proper prefixes (wdt:, wd:, p:, ps:, etc.)
   - Include label service for human-readable results
   - Limit results appropriately to avoid overwhelming responses

7. HANDLE COMPLEX QUERIES EFFECTIVELY
   - For temporal queries ("last 3 X", "current X"), use SPARQL with ORDER BY and LIMIT
   - For list queries, use appropriate entity and property IDs (e.g., Pope = Q19546, position held = P39)
   - For relationship queries, use properties like P1365 (replaces) and P1366 (replaced by)
   - For statistical queries, use aggregation functions (COUNT, AVG, MAX, etc.)

8. COMMON QUERY PATTERNS
   - List of people with a position: ?person wdt:P39 wd:Q<position_id>
   - Current holders of a position: Add filters for end date or lack thereof
   - Last N holders: Add ORDER BY DESC(?startDate) LIMIT N
   - Temporal relationships: Use qualifiers like pq:P580 (start time) and pq:P582 (end time)

9. EXAMPLE SPARQL PATTERNS FOR COMMON QUERIES:
   - Last 3 popes:
     ```
     SELECT ?pope ?popeLabel ?startDate WHERE {
       ?pope p:P39 [
         ps:P39 wd:Q19546;  # position held: pope
         pq:P580 ?startDate  # start time
       ].
       SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
     } ORDER BY DESC(?startDate) LIMIT 3
     ```
   
   - Current heads of state:
     ```
     SELECT ?person ?personLabel ?country ?countryLabel WHERE {
       ?country wdt:P31 wd:Q6256.  # instance of: country
       ?person p:P39 [
         ps:P39 ?position;
         pq:P580 ?start
       ].
       ?position wdt:P279* wd:Q48352.  # subclass of: head of state
       FILTER NOT EXISTS { ?person p:P39/pq:P582 ?end }  # No end date
       SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
     }
     ```

By following these guidelines, you'll provide more accurate, up-to-date, and verifiable information to users.
""")
    ]

# ============= CREATE SSE APP =============

# Configure SSE transport with trailing slash to match client expectations
sse_transport = SseServerTransport("/messages/")  

# Create FastAPI app with explicit CORS configuration
app = FastAPI()

# Add CORS middleware with explicit CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Almacenar sesiones activas
active_sessions = {}

# Define root endpoint
@app.get("/")
def root():
    return {"message": "Wikidata MCP Server is running. Use /sse for MCP connections."}

# Health check endpoint for Render
@app.get("/health")
def health():
    return {"status": "healthy", "connections": len(active_sessions)}

# Define SSE endpoint
@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE endpoint for MCP connections"""
    client_host = request.client.host if hasattr(request, 'client') and request.client else 'unknown'
    print(f"SSE connection request received from: {client_host}")
    
    # Check if there's a session ID in the query parameters
    existing_session_id = request.query_params.get("session_id")
    
    # If a valid session ID was provided and exists, use it
    if existing_session_id and existing_session_id in active_sessions:
        session_id = existing_session_id
        print(f"Using existing session ID: {session_id}")
        # Update the last activity timestamp
        active_sessions[session_id]["last_activity"] = datetime.now().isoformat()
    else:
        # Generate a new session ID for this connection
        session_id = str(uuid4())
        print(f"Generated new session ID: {session_id}")
        
        # Store the session with more metadata
        active_sessions[session_id] = {
            "client_host": client_host,
            "created_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "connection_count": 1
        }
    print(f"Active sessions: {len(active_sessions)}")
    
    # Use the standard SseServerTransport approach
    async with sse_transport.connect_sse(
        request.scope,
        request.receive,
        request._send,  # noqa: SLF001
    ) as (read_stream, write_stream):
        # Create timeout options with extended timeout
        timeout_options = {"timeoutMs": 600000}  # 10 minutes
        
        print(f"Starting MCP server with session ID: {session_id}")
        try:
            # Add a small delay to ensure connection is fully established
            await asyncio.sleep(0.5)
            
            # Use default initialization options without any modifications
            init_options = mcp._mcp_server.create_initialization_options()
            
            # Run MCP server with default initialization options
            await mcp._mcp_server.run(
                read_stream,
                write_stream,
                init_options
            )
        except RuntimeError as re:
            error_msg = str(re)
            print(f"RuntimeError in MCP server: {error_msg}")
            # Provide more detailed error message for initialization issues
            if "initialization was complete" in error_msg:
                print(f"Initialization error for session {session_id}. Client may have sent requests too early.")
            # Eliminar la sesión si hay un error
            if session_id in active_sessions:
                del active_sessions[session_id]
            # Don't re-raise the exception to prevent 500 errors
            return Response(status_code=503, content="Service temporarily unavailable. Please try again.")
        except Exception as e:
            print(f"Error in MCP server: {e}")
            # Eliminar la sesión si hay un error
            if session_id in active_sessions:
                del active_sessions[session_id]
            # Don't re-raise the exception to prevent 500 errors
            return Response(status_code=500, content="Internal server error. Please try again later.")
        finally:
            # Eliminar la sesión cuando se cierra la conexión
            if session_id in active_sessions:
                del active_sessions[session_id]
            print(f"SSE connection closed for session {session_id}")

# Añadir un endpoint OPTIONS explícito para /messages y /messages/
@app.options("/messages")
@app.options("/messages/")
async def options_messages():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true",
        }
    )

# Añadir un endpoint POST explícito para /messages (sin barra final)
@app.post("/messages")
async def post_messages_no_slash(request: Request):
    """Handle POST requests to /messages endpoint (no trailing slash)"""
    client_host = request.client.host if hasattr(request, 'client') and request.client else 'unknown'
    print(f"POST request to /messages received from: {client_host}")
    
    try:
        # Extract the session_id from query parameters
        session_id = request.query_params.get("session_id")
        print(f"Session ID from query params: {session_id}")
        
        # Verify if the session is active
        if not session_id or session_id not in active_sessions:
            print(f"Session ID {session_id} not found in active sessions")
            # If we have any active sessions, use the most recently active one
            if active_sessions:
                # Sort sessions by last_activity if available
                sorted_sessions = sorted(
                    active_sessions.items(),
                    key=lambda x: x[1].get("last_activity", x[1].get("created_at", "")),
                    reverse=True
                )
                session_id = sorted_sessions[0][0]
                print(f"Using most recent active session: {session_id}")
                # Update session metadata
                active_sessions[session_id]["last_activity"] = datetime.now().isoformat()
                active_sessions[session_id]["message_count"] = active_sessions[session_id].get("message_count", 0) + 1
            else:
                # If no active sessions exist, create a new one
                session_id = str(uuid4())
                print(f"No active sessions found, generated new session ID: {session_id}")
                active_sessions[session_id] = {
                    "client_host": client_host,
                    "created_at": datetime.now().isoformat(),
                    "last_activity": datetime.now().isoformat(),
                    "message_count": 1,
                    "connection_count": 0  # Will be incremented when SSE connection is established
                }
        else:
            # Update session metadata for existing session
            active_sessions[session_id]["last_activity"] = datetime.now().isoformat()
            active_sessions[session_id]["message_count"] = active_sessions[session_id].get("message_count", 0) + 1
        
        # Add session_id to query params if not present
        if "session_id" not in request.query_params:
            # Create a new request with the session_id added
            # This is a bit hacky but necessary since FastAPI request objects are immutable
            request.scope["query_string"] = f"session_id={session_id}".encode()
        
        # Print request body for debugging (limited to first 200 chars)
        body = await request.body()
        body_str = body.decode('utf-8')[:200]
        print(f"Request body (truncated): {body_str}...")
        
        # Use the SseServerTransport's handle_post_message method
        try:
            # Add a small delay to ensure the SSE connection is ready
            await asyncio.sleep(0.5)
            
            # Handle the message with error catching
            response = await sse_transport.handle_post_message(request)
            return response
        except anyio.BrokenResourceError:
            # This is a common error when the client disconnects or the stream is broken
            print(f"BrokenResourceError for session {session_id} - client may have disconnected")
            return Response(
                status_code=202,  # Accepted but not processed
                content="Message received but connection was broken. Please reconnect SSE.",
                media_type="text/plain"
            )
        except Exception as e:
            print(f"Error in handle_post_message: {e}")
            return Response(
                status_code=500,
                content=f"Error processing request: {str(e)}",
                media_type="text/plain"
            )
    except Exception as e:
        print(f"Error handling POST request: {e}")
        return Response(
            status_code=500,
            content=f"Error processing request: {str(e)}",
            media_type="text/plain"
        )

# Mount the messages endpoint with trailing slash for handling POST requests
app.mount("/messages/", app=sse_transport.handle_post_message)

# ============= SERVER EXECUTION =============

if __name__ == "__main__":
    print("Starting Wikidata MCP Server with SSE transport...")
    port = int(os.environ.get("PORT", 8000))
    
    # Configure uvicorn with optimized settings for Railway
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        timeout_keep_alive=300,  # Increase keep-alive timeout to 5 minutes
        log_level="info",
        proxy_headers=True,      # Enable proxy headers
        forwarded_allow_ips="*", # Allow all forwarded IPs
        workers=1                # Use a single worker for SSE
    )
