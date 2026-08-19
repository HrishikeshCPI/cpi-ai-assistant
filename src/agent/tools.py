"""
Neo4j-backed tools for querying the CPI integration graph.
These functions can be used with Gemini's automatic function calling.
"""

from __future__ import annotations

from src.graph.neo4j_client import run_query


def find_iflows_using_resource(filename: str) -> list[str]:
    """
    Find all iFlows that use a specific resource file.
    
    Args:
        filename: The name of the resource file (e.g., "script1.groovy", "MM_Convert.mmap")
    
    Returns:
        List of artifact_id strings for iFlows using this resource. Empty list if not found.
    """
    query = """
    MATCH (i:IFlow)<-[:BELONGS_TO]-(s:Step)-[:USES]->(r:Resource {filename: $filename})
    RETURN DISTINCT i.id AS artifact_id
    ORDER BY i.id
    """
    try:
        results = run_query(query, {"filename": filename})
        return [r["artifact_id"] for r in results]
    except Exception:
        return []


def get_resource_detail(filename: str) -> dict:
    """
    Get detailed information about a specific resource file.
    
    Args:
        filename: The name of the resource file (e.g., "script1.groovy", "MM_Convert.mmap")
    
    Returns:
        Dictionary with keys: filename, kind, resolved, purpose, complexity, details_json.
        Empty dict if resource not found.
    """
    query = """
    MATCH (r:Resource {filename: $filename})
    RETURN r.filename AS filename, r.kind AS kind, r.resolved AS resolved,
           r.purpose AS purpose, r.complexity AS complexity, 
           r.details_json AS details_json
    """
    try:
        results = run_query(query, {"filename": filename})
        if results:
            return results[0]
        return {}
    except Exception:
        return {}


def describe_iflow(artifact_id: str) -> dict:
    """
    Describe a specific iFlow integration, including its structure and resources.
    
    Args:
        artifact_id: The artifact ID of the iFlow (e.g., "NorthWind_Customer_OData_Git")
    
    Returns:
        Dictionary with keys: artifact_id, version, steps_count, edges_count, 
        resources_count, systems_count. Empty dict if iFlow not found.
    """
    query = """
    MATCH (i:IFlow {id: $artifact_id})
    OPTIONAL MATCH (i)<-[:BELONGS_TO]-(s:Step)
    OPTIONAL MATCH (s)-[:NEXT]->()
    OPTIONAL MATCH (s)-[:USES]->()
    OPTIONAL MATCH (s)-[:CALLS]->()
    RETURN i.id AS artifact_id, i.version AS version,
           COUNT(DISTINCT s) AS steps_count,
           COUNT(DISTINCT (s)-[:NEXT]->()) AS edges_count,
           COUNT(DISTINCT (s)-[:USES]->()) AS resources_count,
           COUNT(DISTINCT (s)-[:CALLS]->()) AS systems_count
    """
    try:
        results = run_query(query, {"artifact_id": artifact_id})
        if results:
            return results[0]
        return {}
    except Exception:
        return {}


def get_iflow_diagram(artifact_id: str) -> str:
    """Return a Mermaid flowchart diagram string for the given iFlow."""
    from src.graph.visualizer import generate_mermaid

    return generate_mermaid(artifact_id)


def get_iflow_systems(artifact_id: str) -> list[dict]:
    """
    Get a list of external systems that an iFlow connects to.
    
    Args:
        artifact_id: The artifact ID of the iFlow (e.g., "NorthWind_Customer_OData_Git")
    
    Returns:
        List of dictionaries with keys: system_name, direction, component_type, address.
        Empty list if iFlow not found or has no system connections.
    """
    query = """
    MATCH (i:IFlow {id: $artifact_id})<-[:BELONGS_TO]-(s:Step)-[calls:CALLS]->(sys:System)
    RETURN DISTINCT sys.name AS system_name, 
           calls.direction AS direction,
           calls.component_type AS component_type,
           calls.address AS address
    ORDER BY sys.name
    """
    try:
        results = run_query(query, {"artifact_id": artifact_id})
        return results
    except Exception:
        return []


def list_all_iflows() -> list[dict]:
    """
    List all iFlows in the graph with their IDs and versions.
    
    Returns:
        List of dictionaries with keys: artifact_id, version.
        Empty list if no iFlows found.
    """
    query = """
    MATCH (i:IFlow)
    RETURN i.id AS artifact_id, i.version AS version
    ORDER BY i.id
    """
    try:
        results = run_query(query, {})
        return results
    except Exception:
        return []


def find_iflows_by_protocol(protocol: str) -> list[str]:
    """
    Find all iFlows that use a specific communication protocol/component type.
    
    Args:
        protocol: The protocol or component type (e.g., "SOAP", "HTTP", "OData", "JMS")
    
    Returns:
        List of artifact_id strings for iFlows using this protocol. Empty list if not found.
    """
    query = """
    MATCH (i:IFlow)<-[:BELONGS_TO]-(:Step)-[calls:CALLS {component_type: $protocol}]->(:System)
    RETURN DISTINCT i.id AS artifact_id
    ORDER BY i.id
    """
    try:
        results = run_query(query, {"protocol": protocol})
        return [r["artifact_id"] for r in results]
    except Exception:
        return []
def find_resources_by_complexity(complexity: str) -> list[dict]:
    """List resources (scripts/mappings) matching a complexity level: 'trivial', 'moderate', or 'business-logic'. Useful for finding all business logic across the landscape, or candidates for review/refactoring."""
    query = """
    MATCH (r:Resource {complexity: $complexity})
    RETURN r.filename AS filename, r.purpose AS purpose
    """
    results = run_query(query, {"complexity": complexity})
    return [dict(r) for r in results]


def search_iflows_by_keyword(keyword: str) -> list[str]:
    """Find iFlows whose id or step names contain a keyword (case-insensitive)."""
    query = """
    MATCH (i:IFlow)
    OPTIONAL MATCH (i)<-[:BELONGS_TO]-(s:Step)
    WITH i, collect(s.name) AS stepNames
    WHERE toLower(i.id) CONTAINS toLower($keyword)
       OR any(name IN stepNames WHERE toLower(name) CONTAINS toLower($keyword))
    RETURN DISTINCT i.id AS artifact_id
    """
    results = run_query(query, {"keyword": keyword})
    return [r["artifact_id"] for r in results]


def get_unused_resources() -> list[str]:
    """List resources (scripts/mappings/schemas) that no Step actually uses. Helps find orphaned or dead files in the codebase."""
    query = """
    MATCH (r:Resource)
    WHERE NOT (()-[:USES]->(r))
    RETURN r.filename AS filename
    """
    results = run_query(query, {})
    return [r["filename"] for r in results]


def get_iflow_step_count_ranked() -> list[dict]:
    """Rank all iFlows by number of steps, descending. A rough proxy for structural complexity - useful for 'which are our most complex integrations'."""
    query = """
    MATCH (i:IFlow)<-[:BELONGS_TO]-(s:Step)
    RETURN i.id AS artifact_id, count(s) AS step_count
    ORDER BY step_count DESC
    """
    results = run_query(query, {})
    return [dict(r) for r in results]


def find_systems_shared_across_iflows(min_count: int = 2) -> list[dict]:
    """List systems used by more than one iFlow, with counts - shows shared infrastructure/dependencies across the landscape."""
    query = """
    MATCH (s:System)<-[:CALLS]-(:Step)-[:BELONGS_TO]->(i:IFlow)
    WITH s.name AS system, count(DISTINCT i) AS iflow_count
    WHERE iflow_count >= $min_count
    RETURN system, iflow_count
    ORDER BY iflow_count DESC
    """
    results = run_query(query, {"min_count": min_count})
    return [dict(r) for r in results]