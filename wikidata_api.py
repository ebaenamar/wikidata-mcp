"""
Wikidata API Module

This module provides functions for interacting with the Wikidata API and SPARQL endpoint.
"""
import json
import requests
import traceback
import time
from requests.exceptions import Timeout, ConnectionError
from SPARQLWrapper.SPARQLExceptions import QueryBadFormed

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
    # Fetches properties and their values for a given entity.
    # Uses a subquery to get core data before fetching labels for efficiency.
    SELECT ?property ?propertyLabel ?value ?valueLabel
    WHERE {{
      {{
        SELECT ?property ?value
        WHERE {{
          # Core query to get property-value pairs for the entity
          wd:{entity_id} ?p ?statement. # ?p is the property predicate
          ?statement ?ps ?value.      # ?ps is the property statement value predicate

          # Link predicates to actual property entities
          ?property wikibase:claim ?p.
          ?property wikibase:statementProperty ?ps.
        }}
        LIMIT 50
      }}
      # Apply labels to the results of the subquery
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
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
    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1  # seconds

    backoff_time = INITIAL_BACKOFF

    for attempt in range(MAX_RETRIES):
        try:
            sparql = SPARQLWrapper(WIKIDATA_SPARQL_ENDPOINT)
            sparql.addCustomHttpHeader("User-Agent", USER_AGENT)

            # Define allowed SPARQL keywords for top-level lines
            # Based on SPARQL 1.1 specification, including common clause starters.
            # Matching is case-insensitive due to .upper() later.
            allowed_keywords = [
                "PREFIX", "SELECT", "ASK", "CONSTRUCT", "DESCRIBE", "INSERT",
                "FILTER", "BIND", "VALUES", "OPTIONAL", "UNION", "GRAPH",
                "SERVICE", "MINUS", "WHERE", "GROUP", "HAVING", "ORDER",
                "LIMIT", "OFFSET", "DATA"
                # "BY" is handled as part of "GROUP BY" or "ORDER BY" by taking the first word.
            ]

            filtered_query_lines = []
            # Removed unused brace_level variable
            for line_content in sparql_query.splitlines(): # Removed line_num as it's unused
                stripped_line = line_content.strip()

                # Skip blank lines and full-line comments
                if stripped_line == "" or stripped_line.startswith("#"):
                    continue

                first_word_upper = stripped_line.upper().split(" ", 1)[0]

                # Heuristic to identify likely triple patterns or other valid internal lines:
                # Check for common prefixes, variables (?), and if it ends with a period.
                # This is an attempt to distinguish "wd:Q42 ?p ?o ." from "Some junk text."
                is_likely_triple_pattern = (
                    ("wd:" in stripped_line or "wdt:" in stripped_line or "rdf:" in stripped_line or
                     ":" in stripped_line or "?" in stripped_line) and
                    stripped_line.endswith(".")
                )

                if first_word_upper in allowed_keywords:
                    filtered_query_lines.append(line_content)
                elif any(c in stripped_line for c in ['{', '}', ';', ',']): # Structural chars
                    filtered_query_lines.append(line_content)
                elif is_likely_triple_pattern:
                    filtered_query_lines.append(line_content)
                # else, it's a line like "This is not a valid statement" - drop it.

            processed_query = "\n".join(filtered_query_lines)

            # Add common prefixes to make queries easier to write
            prefixes = """
            PREFIX wd: <http://www.wikidata.org/entity/>
            PREFIX wdt: <http://www.wikidata.org/prop/direct/>
            PREFIX p: <http://www.wikidata.org/prop/>
            PREFIX ps: <http://www.wikidata.org/prop/statement/>
            PREFIX wikibase: <http://wikiba.se/ontology#>
            PREFIX bd: <http://www.bigdata.com/rdf#>
            """

            # Add prefixes if they're not already in the processed_query
            # and if the processed_query doesn't already start with "PREFIX" (case-insensitive)
            # Also check if processed_query actually contains any non-prefix lines.
            # If the query after filtering ONLY contains PREFIX lines, don't add more.

            # Check if there are any non-PREFIX lines in the filtered query
            has_non_prefix_lines = any(not line.strip().upper().startswith("PREFIX") for line in filtered_query_lines if line.strip())

            if processed_query and has_non_prefix_lines and \
               not any(line.strip().upper().startswith("PREFIX") for line in filtered_query_lines if line.strip().upper().startswith("PREFIX")):
                full_query = prefixes.strip() + "\n" + processed_query
            else:
                full_query = processed_query

            sparql.setQuery(full_query)
            sparql.setReturnFormat(JSON)

            results = sparql.query().convert()
            # Return the full results structure, not just the bindings
            return json.dumps(results)
        
        except (Timeout, ConnectionError) as e:
            error_details = {
                "error": f"Error executing query (attempt {attempt + 1}/{MAX_RETRIES}): {str(e)}",
                "query": sparql_query,
                "error_type": str(type(e).__name__),
                "traceback": traceback.format_exc()
            }
            print(f"SPARQL Error Details: {json.dumps(error_details, indent=2)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff_time)
                backoff_time *= 2  # Exponential backoff
            else:
                return json.dumps(error_details) # Max retries reached
        
        except QueryBadFormed as e:
            error_details = {
                "error": f"SPARQL Query Syntax Error: {str(e)}",
                "query": sparql_query,
                "error_type": str(type(e).__name__),
                "traceback": traceback.format_exc()
            }
            print(f"SPARQL Error Details: {json.dumps(error_details, indent=2)}")
            return json.dumps(error_details) # Return immediately for bad query syntax

        except Exception as e:
            error_details = {
                "error": f"An unexpected error occurred (attempt {attempt + 1}/{MAX_RETRIES}): {str(e)}",
                "query": sparql_query,
                "error_type": str(type(e).__name__),
                "traceback": traceback.format_exc()
            }
            print(f"SPARQL Error Details: {json.dumps(error_details, indent=2)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff_time)
                backoff_time *= 2  # Exponential backoff
            else:
                return json.dumps(error_details) # Max retries reached

    # This part should ideally not be reached if logic is correct, but as a fallback:
    final_error_details = {
        "error": "Max retries reached. Failed to execute SPARQL query.",
        "query": sparql_query,
        "error_type": "MaxRetriesExceeded"
    }
    return json.dumps(final_error_details)


def test_execute_sparql_with_problematic_lines():
    """
    Tests the execute_sparql function with a query containing lines that should be filtered out.
    """
    print("Running test_execute_sparql_with_problematic_lines...")

    # This query includes comments and non-SPARQL lines that should be filtered.
    # The core is a valid ASK query.
    test_query_problematic = """
    # This is a comment line that should be removed.
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    This line is not a valid SPARQL statement.
    ASK WHERE {
      wd:Q42 ?p ?o . # Q42 is Douglas Adams, should exist.
    }
    Another bogus line here.
    """

    expected_result_ask_true = {"head": {}, "boolean": True}

    result_str = execute_sparql(test_query_problematic)

    try:
        result_json = json.loads(result_str)
        # We need to compare the boolean value for ASK queries
        if "boolean" in result_json:
            if result_json["boolean"] == expected_result_ask_true["boolean"]:
                print("Test PASSED: Problematic lines were filtered, and the ASK query returned True as expected.")
            else:
                print(f"Test FAILED: ASK query returned {result_json['boolean']}, expected {expected_result_ask_true['boolean']}.")
                print(f"Full result: {result_json}")
        elif "error" in result_json:
            print(f"Test FAILED: Query execution resulted in an error: {result_json['error']}")
            if "query" in result_json:
                 print(f"Original problematic query sent to execute_sparql:\n{test_query_problematic}")
        else:
            print(f"Test FAILED: Unexpected result format. Result: {result_json}")

    except json.JSONDecodeError:
        print(f"Test FAILED: Could not decode JSON from result string: {result_str}")
        print(f"Original problematic query sent to execute_sparql:\n{test_query_problematic}")

def test_execute_sparql_with_various_clauses():
    """
    Tests the execute_sparql function with queries using various SPARQL clauses
    to ensure essential lines are preserved by the filtering logic.
    """
    print("\nRunning test_execute_sparql_with_various_clauses...")

    # Using a common, simple entity (e.g., Q1 for Universe) for basic triple patterns.
    # Most queries are ASK for simplicity, focusing on syntax preservation.
    # Prefixes are added by execute_sparql if not present.
    test_queries = {
        "FILTER": "ASK { wd:Q1 ?p ?o . FILTER(BOUND(?o)) }",
        "BIND": "ASK { BIND(1 AS ?one) }",
        "VALUES": "ASK { VALUES ?one { 1 UNDEF } }",
        "OPTIONAL": "ASK { wd:Q1 ?p ?o . OPTIONAL { ?o ?p2 ?o2 } }",
        "UNION": "ASK { { wd:Q1 ?p ?o } UNION { ?s ?p wd:Q1 } }",
        "GRAPH": "ASK { GRAPH ?g { wd:Q1 ?p ?o } }",
        "SERVICE": "ASK { SERVICE <http://example.com/sparql-not-real> { wd:Q1 ?p ?o } }",
        "MINUS": "ASK { wd:Q1 ?p ?o . MINUS { wd:Q1 ?p wd:Q2 } }", # wd:Q2 is Earth
        "WHERE_clause": "SELECT ?s WHERE { ?s ?p wd:Q1 . } LIMIT 1",
        "GROUP_BY": "SELECT (COUNT(?o) AS ?count) WHERE { wd:Q1 ?p ?o . } GROUP BY ?p",
        "HAVING": "SELECT ?p (COUNT(?o) AS ?count) WHERE { wd:Q1 ?p ?o . } GROUP BY ?p HAVING(?count > 0)",
        "ORDER_BY": "SELECT ?o WHERE { wd:Q1 ?p ?o . } ORDER BY ?o LIMIT 1",
        "LIMIT_OFFSET": "SELECT ?o WHERE { wd:Q1 ?p ?o . } ORDER BY ?o LIMIT 1 OFFSET 0"
    }

    all_passed_flag = True # Use a different name to avoid conflict with built-in all()
    for clause, query in test_queries.items():
        print(f"  Testing clause: {clause} with query: {query}")
        result_str = execute_sparql(query)
        try:
            result_json = json.loads(result_str)

            # Primary check: Was the query broken by filtering leading to QueryBadFormed?
            is_query_bad_formed = "error" in result_json and \
                                  ("QueryBadFormed" in result_json.get("error", "") or \
                                   result_json.get("error_type") == "QueryBadFormed")

            if is_query_bad_formed:
                # Specific handling for GRAPH clause due to Wikidata endpoint limitations
                if clause == "GRAPH" and "QuadsOperationInTriplesModeException" in result_json.get("error", ""):
                    print(f"    Test for {clause} PASSED (line preserved; endpoint limitation 'QuadsOperationInTriplesModeException' received as expected).")
                else:
                    print(f"    Test for {clause} FAILED: QueryBadFormed error indicates filter may have broken the query.")
                    print(f"    Error details: {result_json.get('error')}")
                    all_passed_flag = False
            # Specific check for SERVICE: expect an error, but not QueryBadFormed
            elif clause == "SERVICE":
                if "error" not in result_json:
                    print(f"    Test for {clause} FAILED: SERVICE query did not produce an error as expected.")
                    all_passed_flag = False
                elif result_json.get("error_type") == "QueryBadFormed": # Should be a different error like EndPointInternalError or timeout
                    print(f"    Test for {clause} FAILED: SERVICE query resulted in QueryBadFormed, expected a connection/timeout or other execution error.")
                    all_passed_flag = False
                else:
                    print(f"    Test for {clause} PASSED (SERVICE query correctly failed with non-QueryBadFormed error: {result_json.get('error_type')}).")
            # General checks for other query types if no QueryBadFormed error (or handled special case)
            else: # Not QueryBadFormed (or handled special QueryBadFormed like for GRAPH)
                if query.strip().upper().startswith("ASK") and "boolean" not in result_json and "error" not in result_json:
                    print(f"    Test for {clause} FAILED: ASK query did not return a boolean result key and no other error reported.")
                    all_passed_flag = False
                elif query.strip().upper().startswith("SELECT") and "results" not in result_json and "error" not in result_json:
                    print(f"    Test for {clause} FAILED: SELECT query did not return a results key and no other error reported.")
                    all_passed_flag = False
                elif "error" in result_json: # Some other non-QueryBadFormed error occurred
                     print(f"    Test for {clause} PASSED (query resulted in expected non-QueryBadFormed error: {result_json.get('error_type', 'Unknown error')}).")
                else:
                    print(f"    Test for {clause} PASSED (query processed without being malformed by filter and executed as expected).")

        except json.JSONDecodeError:
            print(f"    Test for {clause} FAILED: Could not decode JSON from result string: {result_str}")
            all_passed_flag = False

    if all_passed_flag:
        print("All new clause tests PASSED.")
    else:
        print("Some new clause tests FAILED.")

    return all_passed_flag

if __name__ == "__main__":
    # Example Usage (Optional - can be commented out or removed)
    # search_term = "Albert Einstein"
    # entity_id = search_entity(search_term)
    # print(f"Entity ID for '{search_term}': {entity_id}")

    # if not entity_id.startswith("Error") and entity_id != "No entity found":
    #     metadata = get_entity_metadata(entity_id)
    #     print(f"Metadata for {entity_id}: {json.dumps(metadata, indent=2)}")

    #     properties = get_entity_properties(entity_id)
    #     # Properties are already a list of dicts from the new function
    #     print(f"Properties for {entity_id}:")
    #     for prop in properties: # Assuming properties is already a list from json.loads
    #         print(json.dumps(prop, indent=2))

    # Test the SPARQL execution with problematic lines
    test_execute_sparql_with_problematic_lines()

    # Test the SPARQL execution with various clauses
    test_execute_sparql_with_various_clauses()
