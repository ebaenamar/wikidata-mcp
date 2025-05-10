"""
Wikidata API Module

This module provides functions for interacting with the Wikidata API and SPARQL endpoint.
"""
import json
import requests
import traceback

# Import SPARQLWrapper
from SPARQLWrapper import SPARQLWrapper, JSON

# Constants
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "Wikidata MCP Server/1.0 (https://github.com/ebaenamar/wikidata-mcp; ebaenamar@gmail.com)"

def search_entity(query: str) -> str:
    """
    Search for a Wikidata entity ID by its name.
    
    Args:
        query: The search term
        
    Returns:
        The Wikidata entity ID (e.g., Q937 for Albert Einstein) or an error message
    """
    params = {
        "action": "wbsearchentities",
        "format": "json",
        "language": "en",
        "search": query,
        "type": "item"
    }
    
    headers = {
        "User-Agent": USER_AGENT
    }
    
    try:
        response = requests.get(WIKIDATA_API_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "search" in data and len(data["search"]) > 0:
            return data["search"][0]["id"]
        else:
            return "No entity found"
    except requests.exceptions.RequestException as e:
        return f"Error searching for entity: {str(e)}"

def search_property(query: str) -> str:
    """
    Search for a Wikidata property ID by its name.
    
    Args:
        query: The search term
        
    Returns:
        The Wikidata property ID (e.g., P31 for "instance of") or an error message
    """
    params = {
        "action": "wbsearchentities",
        "format": "json",
        "language": "en",
        "search": query,
        "type": "property"
    }
    
    headers = {
        "User-Agent": USER_AGENT
    }
    
    try:
        response = requests.get(WIKIDATA_API_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "search" in data and len(data["search"]) > 0:
            return data["search"][0]["id"]
        else:
            return "No property found"
    except requests.exceptions.RequestException as e:
        return f"Error searching for property: {str(e)}"

def get_entity_metadata(entity_id: str) -> dict:
    """
    Get label and description for a Wikidata entity.
    
    Args:
        entity_id: The Wikidata entity ID (e.g., Q937)
        
    Returns:
        A dictionary containing the entity's label and description
    """
    params = {
        "action": "wbgetentities",
        "format": "json",
        "ids": entity_id,
        "languages": "en",
        "props": "labels|descriptions"
    }
    
    headers = {
        "User-Agent": USER_AGENT
    }
    
    try:
        response = requests.get(WIKIDATA_API_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "entities" in data and entity_id in data["entities"]:
            entity = data["entities"][entity_id]
            label = entity.get("labels", {}).get("en", {}).get("value", "No label found")
            description = entity.get("descriptions", {}).get("en", {}).get("value", "No description found")
            
            return {
                "id": entity_id,
                "label": label,
                "description": description
            }
        else:
            return {"error": f"Entity {entity_id} not found"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Error retrieving entity metadata: {str(e)}"}

def get_entity_properties(entity_id: str) -> list:
    """
    Get all properties for a Wikidata entity.
    
    Args:
        entity_id: The Wikidata entity ID (e.g., Q937)
        
    Returns:
        A list of property-value pairs for the entity
    """
    sparql_query = f"""
    SELECT ?property ?propertyLabel ?value ?valueLabel
    WHERE {{
      wd:{entity_id} ?p ?statement.
      ?statement ?ps ?value.
      
      ?property wikibase:claim ?p.
      ?property wikibase:statementProperty ?ps.
      
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT 50
    """
    
    return json.loads(execute_sparql(sparql_query))

def execute_sparql(sparql_query: str) -> str:
    """
    Execute a SPARQL query on Wikidata.
    
    Args:
        sparql_query: SPARQL query to execute
        
    Returns:
        JSON-formatted result of the query
    """
    try:
        sparql = SPARQLWrapper(WIKIDATA_SPARQL_ENDPOINT)
        sparql.addCustomHttpHeader("User-Agent", USER_AGENT)
        
        # Add common prefixes to make queries easier to write
        prefixes = """
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX p: <http://www.wikidata.org/prop/>
        PREFIX ps: <http://www.wikidata.org/prop/statement/>
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX bd: <http://www.bigdata.com/rdf#>
        """
        
        # Add prefixes if they're not already in the query
        if not any(prefix in sparql_query for prefix in ["PREFIX", "prefix"]):
            full_query = prefixes + sparql_query
        else:
            full_query = sparql_query
        
        sparql.setQuery(full_query)
        sparql.setReturnFormat(JSON)
        
        results = sparql.query().convert()
        # Return the full results structure, not just the bindings
        return json.dumps(results)
    except Exception as e:
        error_details = {
            "error": f"Error executing query: {str(e)}",
            "query": sparql_query,
            "error_type": str(type(e).__name__),
            "traceback": traceback.format_exc()
        }
        print(f"SPARQL Error Details: {json.dumps(error_details, indent=2)}")
        return json.dumps(error_details)


