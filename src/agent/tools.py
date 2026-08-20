"""
Neo4j-backed tools for querying the CPI integration graph.
These functions can be used with Gemini's automatic function calling.

Design note: exceptions are surfaced in the return value (as an "error" key
or entry) rather than silently swallowed into an empty result. A silent
empty result is indistinguishable from "genuinely nothing found," which
previously caused the agent to fabricate answers instead of reporting a
real query failure.
"""

from __future__ import annotations

from src.graph.neo4j_client import run_query


def find_iflows_using_resource(filename: str) -> list:
    """
    Find all iFlows that use a specific resource file.

    Args:
        filename: The name of the resource file (e.g., "script1.groovy", "MM_Convert.mmap")

    Returns:
        List of artifact_id strings for iFlows using this resource.
        Empty list if genuinely not found. On query failure, returns a
        single-item list with an {"error": ...} dict.
    """
    query = """
    MATCH (i:IFlow)<-[:BELONGS_TO]-(s:Step)-[:USES]->(r:Resource {filename: $filename})
    RETURN DISTINCT i.id AS artifact_id
    ORDER BY i.id
    """
    try:
        results = run_query(query, {"filename": filename})
        return [r["artifact_id"] for r in results]
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def get_resource_detail(filename: str) -> dict:
    """Get detailed information about a specific resource, including which iFlows use it."""
    query = """
    MATCH (r:Resource {filename: $filename})
    OPTIONAL MATCH (i:IFlow)<-[:BELONGS_TO]-(:Step)-[:USES]->(r)
    RETURN r.filename AS filename, r.kind AS kind, r.resolved AS resolved,
           r.purpose AS purpose, r.complexity AS complexity,
           collect(DISTINCT i.id) AS used_in_iflows
    """
    try:
        results = run_query(query, {"filename": filename})
        return results[0] if results else {}
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def describe_iflow(artifact_id: str) -> dict:
    """
    Describe a specific iFlow integration: its steps, resources each step
    uses, and version info.

    Args:
        artifact_id: The artifact ID of the iFlow (e.g., "NorthWind_Customer_OData_Git")

    Returns:
        Dictionary with artifact_id, version, and a "steps" list (each with
        id, name, bpmn_type, activity_type, resources_used). Empty dict if
        iFlow genuinely not found. {"error": ...} on query failure.
    """
    query = """
    MATCH (i:IFlow {id: $artifact_id})
    OPTIONAL MATCH (i)<-[:BELONGS_TO]-(s:Step)
    OPTIONAL MATCH (s)-[:USES]->(r:Resource)
    RETURN i.id AS artifact_id, i.version AS version,
           s.id AS step_id, s.name AS step_name,
           s.bpmn_type AS bpmn_type, s.activity_type AS activity_type,
           collect(DISTINCT r.filename) AS resources_used
    """
    try:
        results = run_query(query, {"artifact_id": artifact_id})
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}

    if not results:
        return {}

    artifact_id_val = results[0]["artifact_id"]
    version = results[0]["version"]
    steps = []
    for row in results:
        if row["step_id"] is None:
            continue
        steps.append({
            "id": row["step_id"],
            "name": row["step_name"],
            "bpmn_type": row["bpmn_type"],
            "activity_type": row["activity_type"],
            "resources_used": [r for r in row["resources_used"] if r],
        })

    return {
        "artifact_id": artifact_id_val,
        "version": version,
        "steps": steps,
    }


def get_iflow_resources(artifact_id: str) -> list:
    """
    List all resources (scripts, mappings, schemas) used by a specific
    iFlow, with their kind and purpose if resolved.

    Args:
        artifact_id: The artifact ID of the iFlow (e.g., "NorthWind_Customer_OData_Git")

    Returns:
        List of dicts with filename, kind, purpose. Empty list if the
        iFlow uses no resources. {"error": ...} single-item list on failure.
    """
    query = """
    MATCH (i:IFlow {id: $artifact_id})<-[:BELONGS_TO]-(:Step)-[:USES]->(r:Resource)
    RETURN DISTINCT r.filename AS filename, r.kind AS kind, r.purpose AS purpose,
           r.complexity AS complexity, r.details_json AS details_json
    """
    try:
        results = run_query(query, {"artifact_id": artifact_id})
        return [dict(r) for r in results]
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def get_iflow_parameters(artifact_id: str) -> list:
    """List externalized parameters configured for a specific iFlow, including their configured values."""
    query = """
    MATCH (i:IFlow {id: $artifact_id})-[:HAS_PARAMETER]->(p:Parameter)
    RETURN p.name AS name, p.attribute_label AS label,
           p.attribute_category AS category, p.configured_value AS value,
           p.is_required AS is_required
    ORDER BY p.attribute_category, p.name
    """
    try:
        return run_query(query, {"artifact_id": artifact_id})
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def get_iflow_diagram(artifact_id: str) -> str:
    """Return a Mermaid flowchart diagram string for the given iFlow."""
    from src.graph.visualizer import generate_mermaid
    try:
        return generate_mermaid(artifact_id)
    except Exception as exc:
        return f"Error generating diagram: {exc}"


def get_iflow_systems(artifact_id: str) -> list:
    """
    Get a list of external systems that an iFlow connects to.

    Args:
        artifact_id: The artifact ID of the iFlow (e.g., "NorthWind_Customer_OData_Git")

    Returns:
        List of dicts with system_name, direction, component_type, address.
        Empty list if genuinely none. {"error": ...} single-item list on failure.
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
        return run_query(query, {"artifact_id": artifact_id})
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def list_all_iflows() -> list:
    """
    List all iFlows in the graph with their IDs and versions.

    Returns:
        List of dicts with artifact_id, version. {"error": ...} on failure.
    """
    query = """
    MATCH (i:IFlow)
    RETURN i.id AS artifact_id, i.version AS version
    ORDER BY i.id
    """
    try:
        return run_query(query, {})
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def find_iflows_by_protocol(protocol: str) -> list:
    """
    Find all iFlows that use a specific communication protocol/component type.

    Args:
        protocol: The protocol or component type (e.g., "SOAP", "HTTP", "OData", "JMS")

    Returns:
        List of artifact_id strings. {"error": ...} single-item list on failure.
    """
    query = """
    MATCH (i:IFlow)<-[:BELONGS_TO]-(:Step)-[calls:CALLS {component_type: $protocol}]->(:System)
    RETURN DISTINCT i.id AS artifact_id
    ORDER BY i.id
    """
    try:
        results = run_query(query, {"protocol": protocol})
        return [r["artifact_id"] for r in results]
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def find_resources_by_complexity(complexity: str) -> list:
    """
    List resources (scripts/mappings) matching a complexity level:
    'trivial', 'moderate', or 'business-logic'. Useful for finding all
    business logic across the landscape, or candidates for review/refactoring.
    """
    query = """
    MATCH (r:Resource {complexity: $complexity})
    RETURN r.filename AS filename, r.purpose AS purpose
    """
    try:
        results = run_query(query, {"complexity": complexity})
        return [dict(r) for r in results]
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def search_iflows_by_keyword(keyword: str) -> list:
    """Find iFlows whose id or step names contain a keyword (case-insensitive)."""
    query = """
    MATCH (i:IFlow)
    OPTIONAL MATCH (i)<-[:BELONGS_TO]-(s:Step)
    WITH i, collect(s.name) AS stepNames
    WHERE toLower(i.id) CONTAINS toLower($keyword)
       OR any(name IN stepNames WHERE toLower(name) CONTAINS toLower($keyword))
    RETURN DISTINCT i.id AS artifact_id
    """
    try:
        results = run_query(query, {"keyword": keyword})
        return [r["artifact_id"] for r in results]
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def get_unused_resources() -> list:
    """List resources (scripts/mappings/schemas) that no Step actually uses."""
    query = """
    MATCH (r:Resource)
    WHERE NOT (()-[:USES]->(r))
    RETURN r.filename AS filename
    """
    try:
        results = run_query(query, {})
        return [r["filename"] for r in results]
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def get_iflow_step_count_ranked() -> list:
    """Rank all iFlows by number of steps, descending."""
    query = """
    MATCH (i:IFlow)<-[:BELONGS_TO]-(s:Step)
    RETURN i.id AS artifact_id, count(s) AS step_count
    ORDER BY step_count DESC
    """
    try:
        results = run_query(query, {})
        return [dict(r) for r in results]
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]


def find_systems_shared_across_iflows(min_count: int = 2) -> list:
    """List systems used by more than one iFlow, with counts."""
    query = """
    MATCH (s:System)<-[:CALLS]-(:Step)-[:BELONGS_TO]->(i:IFlow)
    WITH s.name AS system, count(DISTINCT i) AS iflow_count
    WHERE iflow_count >= $min_count
    RETURN system, iflow_count
    ORDER BY iflow_count DESC
    """
    try:
        results = run_query(query, {"min_count": min_count})
        return [dict(r) for r in results]
    except Exception as exc:
        return [{"error": f"Query failed: {exc}"}]
