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

import json

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
    OPTIONAL MATCH (i)<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s:Step)
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

    response = {
        "artifact_id": artifact_id_val,
        "version": version,
        "steps": steps,
    }

    process_query = """
    MATCH (:IFlow {id: $artifact_id})<-[:PART_OF]-(p:Process)
    WHERE p.classification <> 'main'
    RETURN p.classification AS classification, count(p) AS process_count
    ORDER BY p.classification
    """
    try:
        process_rows = run_query(process_query, {"artifact_id": artifact_id})
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}

    if process_rows:
        labels = {
            "local_subprocess": "local subprocess",
            "error_handling": "error-handling subprocess",
        }
        parts = []
        for row in process_rows:
            count = row["process_count"]
            label = labels.get(row["classification"], row["classification"].replace("_", " "))
            parts.append(f"{count} {label}{'' if count == 1 else 'es'}")
        response["process_structure"] = ", ".join(parts)

    return response


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


def get_subflow_chain(artifact_id: str) -> dict:
    """Return the direct subflows called by an iFlow and its direct callers."""
    query = """
    MATCH (i:IFlow {id: $artifact_id})
    OPTIONAL MATCH (i)-[outgoing:CALLS_SUBFLOW]->(callee:IFlow)
    WITH i, collect(DISTINCT {callee: callee.id, address: outgoing.address}) AS calls
    OPTIONAL MATCH (caller:IFlow)-[incoming:CALLS_SUBFLOW]->(i)
    RETURN i.id AS artifact_id, calls,
           collect(DISTINCT {caller: caller.id, address: incoming.address}) AS called_by
    """
    try:
        rows = run_query(query, {"artifact_id": artifact_id})
        if not rows:
            return {}
        row = rows[0]
        return {
            "artifact_id": row["artifact_id"],
            "calls": [item for item in row["calls"] if item["callee"]],
            "called_by": [item for item in row["called_by"] if item["caller"]],
        }
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def find_subflow_callers(artifact_id: str) -> dict:
    """Find every iFlow that calls the specified reusable subflow."""
    query = """
    MATCH (i:IFlow {id: $artifact_id})
    OPTIONAL MATCH (caller:IFlow)-[c:CALLS_SUBFLOW]->(i)
    RETURN i.id AS artifact_id,
           collect(DISTINCT {caller: caller.id, address: c.address}) AS called_by
    """
    try:
        rows = run_query(query, {"artifact_id": artifact_id})
        if not rows:
            return {}
        row = rows[0]
        return {
            "artifact_id": row["artifact_id"],
            "called_by": [item for item in row["called_by"] if item["caller"]],
        }
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def get_iflow_processes(artifact_id: str) -> dict:
    """List an iFlow's processes, classifications, and Process-scoped Step counts."""
    query = """
    MATCH (i:IFlow {id: $artifact_id})
    OPTIONAL MATCH (i)<-[:PART_OF]-(p:Process)
    OPTIONAL MATCH (p)<-[:BELONGS_TO]-(s:Step)
    RETURN i.id AS artifact_id, p.id AS process_id,
           p.classification AS classification, count(s) AS step_count
    ORDER BY process_id
    """
    try:
        rows = run_query(query, {"artifact_id": artifact_id})
        if not rows:
            return {}
        return {
            "artifact_id": rows[0]["artifact_id"],
            "processes": [
                {
                    "process_id": row["process_id"],
                    "classification": row["classification"],
                    "step_count": row["step_count"],
                }
                for row in rows if row["process_id"] is not None
            ],
        }
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def get_error_handling_coverage() -> dict:
    """Summarize error-handling Processes and their triggers/end steps across all iFlows."""
    iflows_query = "MATCH (i:IFlow) RETURN i.id AS artifact_id ORDER BY artifact_id"
    details_query = """
    MATCH (i:IFlow)<-[:PART_OF]-(p:Process {classification: 'error_handling'})
    OPTIONAL MATCH (p)<-[:BELONGS_TO]-(s:Step)
    RETURN i.id AS artifact_id, p.id AS process_id,
           collect(DISTINCT s.error_trigger_type) AS trigger_types,
           collect(DISTINCT CASE WHEN s.bpmn_type = 'endEvent' THEN s.name END) AS terminal_steps
    ORDER BY artifact_id, process_id
    """
    try:
        all_iflows = [row["artifact_id"] for row in run_query(iflows_query)]
        rows = run_query(details_query)
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["artifact_id"], []).append({
                "process_id": row["process_id"],
                "trigger_types": [value for value in row["trigger_types"] if value is not None],
                "terminal_steps": [value for value in row["terminal_steps"] if value is not None],
            })
        with_error_handling = [
            {
                "artifact_id": artifact_id,
                "error_process_count": len(details),
                "details": details,
            }
            for artifact_id, details in grouped.items()
        ]
        return {
            "iflows_with_error_handling": with_error_handling,
            "total_iflows_checked": len(all_iflows),
            "iflows_without_error_handling": [
                artifact_id for artifact_id in all_iflows if artifact_id not in grouped
            ],
        }
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def get_local_subprocess_calls(artifact_id: str) -> dict:
    """List local Process invocations from an iFlow, excluding cross-iFlow subflow calls."""
    query = """
    MATCH (i:IFlow {id: $artifact_id})<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s:Step)
          -[:INVOKES]->(target:Process)
    WHERE target.classification IN ['local_subprocess', 'error_handling']
    RETURN i.id AS artifact_id, s.name AS step_name, target.id AS target_process_id,
           target.classification AS target_classification
    ORDER BY step_name
    """
    try:
        rows = run_query(query, {"artifact_id": artifact_id})
        return {
            "artifact_id": artifact_id,
            "invocations": [
                {
                    "step_name": row["step_name"],
                    "target_process_id": row["target_process_id"],
                    "target_classification": row["target_classification"],
                }
                for row in rows
            ],
        }
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def find_iflows_by_auth_property(property_key: str, property_value: str | None) -> dict:
    """Find adapter CALLS whose JSON properties contain a requested key/value.

    Pass ``None`` for ``property_value`` to find properties whose value is
    absent, null, or an empty string.
    """
    query = """
    MATCH (i:IFlow)<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s:Step)-[c:CALLS]->(sys:System)
    RETURN i.id AS artifact_id, s.name AS step_name, sys.name AS system_name,
           c.component_type AS component_type, c.properties_json AS properties_json
    ORDER BY artifact_id, step_name, system_name
    """
    try:
        matches = []
        for row in run_query(query):
            properties = json.loads(row["properties_json"] or "{}")
            if property_key not in properties:
                continue
            matched_property = properties[property_key]
            value = matched_property.get("value") if isinstance(matched_property, dict) else matched_property
            is_empty = value is None or value == ""
            if (property_value is None and not is_empty) or (
                property_value is not None and value != property_value
            ):
                continue
            matches.append({
                "artifact_id": row["artifact_id"],
                "step_name": row["step_name"],
                "system_name": row["system_name"],
                "component_type": row["component_type"],
                "matched_property": {property_key: matched_property},
            })
        return {"matches": matches}
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def get_adapter_security_summary(artifact_id: str) -> dict:
    """List an iFlow's adapter calls with externalization and literal property counts."""
    query = """
    MATCH (i:IFlow {id: $artifact_id})<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s:Step)
          -[c:CALLS]->(sys:System)
    RETURN s.name AS step_name, sys.name AS system_name,
           c.component_type AS component_type, c.direction AS direction,
           c.externalized_count AS externalized_count, c.literal_count AS literal_count
    ORDER BY step_name, system_name
    """
    try:
        rows = run_query(query, {"artifact_id": artifact_id})
        return {"artifact_id": artifact_id, "adapters": [dict(row) for row in rows]}
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def find_scripts_using_cpi_api(api_name: str) -> dict:
    """Find Groovy resources that call a named CPI API and report literal arguments."""
    query = """
    MATCH (i:IFlow)<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(:Step)-[:USES]->(r:Resource {kind: 'groovy'})
    WHERE r.cpi_apis_json IS NOT NULL
    RETURN DISTINCT i.id AS artifact_id, r.filename AS script_filename,
           r.cpi_apis_json AS cpi_apis_json
    ORDER BY artifact_id, script_filename
    """
    try:
        matches = []
        for row in run_query(query):
            for api in json.loads(row["cpi_apis_json"]):
                if api.get("api_name") == api_name:
                    matches.append({
                        "artifact_id": row["artifact_id"],
                        "script_filename": row["script_filename"],
                        "literal_argument": api.get("literal_argument"),
                    })
        return {"api_name": api_name, "matches": matches}
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


def find_complex_mappings() -> dict:
    """List mappings with parser-detected complex transformation structures."""
    query = """
    MATCH (i:IFlow)<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(:Step)-[:USES]->(r:Resource)
    WHERE r.has_complex_transformations = true
    RETURN DISTINCT i.id AS artifact_id, r.filename AS filename,
           r.mapping_format AS mapping_format
    ORDER BY artifact_id, filename
    """
    try:
        return {"complex_mappings": [dict(row) for row in run_query(query)]}
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}
