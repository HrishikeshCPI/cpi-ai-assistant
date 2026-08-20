from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from src.graph.neo4j_client import run_query


def load_artifact(json_path: str) -> dict[str, int]:
    """
    Load a single IFlowArtifact JSON file into Neo4j.
    
    Args:
        json_path: Path to output/*.json artifact file
    
    Returns:
        Dict with counts: {"steps": int, "resources": int, "systems": int,
        "message_flows": int, "parameters": int}
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Artifact JSON not found: {json_path}")

    with open(path, encoding="utf-8") as f:
        artifact = json.load(f)

    artifact_id = artifact.get("artifact_id", "")
    version = artifact.get("version", "1.0.0")
    nodes = artifact.get("nodes", [])
    edges = artifact.get("edges", [])
    message_flows = artifact.get("message_flows", [])
    systems = artifact.get("systems", [])
    resolved_resources = artifact.get("resolved_resources", {})
    resources_list = artifact.get("resources", {})
    externalized_parameters = artifact.get("externalized_parameters", [])

    if not artifact_id:
        raise ValueError(f"No artifact_id found in {json_path}")

    # Step 1: Clean up existing IFlow, Steps, and package-scoped Parameters.
    # Package, System, and Resource nodes remain shared across IFlows.
    cleanup_parameters_query = """
    MATCH (i:IFlow {id: $artifact_id})-[:HAS_PARAMETER]->(p:Parameter)
    DETACH DELETE p
    """
    run_query(cleanup_parameters_query, {"artifact_id": artifact_id})

    cleanup_query = """
    MATCH (i:IFlow {id: $artifact_id})
    OPTIONAL MATCH (i)<-[:BELONGS_TO]-(s:Step)
    DETACH DELETE i, s
    """
    run_query(cleanup_query, {"artifact_id": artifact_id})

    # Step 2: Create Package node (MERGE to handle sharing)
    # Use the artifact_id as package name (no clear package/iflow distinction in the data)
    package_name = artifact_id.split(".")[-1] if "." in artifact_id else artifact_id
    create_package = """
    MERGE (p:Package {name: $package_name})
    RETURN p
    """
    run_query(create_package, {"package_name": package_name})

    # Step 3: Create IFlow node and link to Package
    create_iflow = """
    MERGE (p:Package {name: $package_name})
    CREATE (i:IFlow {id: $artifact_id, version: $version})
    CREATE (i)-[:PART_OF]->(p)
    RETURN i
    """
    run_query(create_iflow, {"package_name": package_name, "artifact_id": artifact_id, "version": version})

    step_count = 0
    resource_count = 0
    system_count = 0
    parameter_count = 0

    # Step 4: Create Step nodes and link to IFlow
    for node in nodes:
        node_id = node.get("id", "")
        node_name = node.get("name", "")
        bpmn_type = node.get("bpmn_type", "")
        activity_type = node.get("type")

        if not node_id:
            continue

        step_key = f"{artifact_id}::{node_id}"
        create_step = """
        MATCH (i:IFlow {id: $artifact_id})
        MERGE (s:Step {step_key: $step_key})
        SET s.id = $node_id, s.name = $node_name, s.bpmn_type = $bpmn_type, s.activity_type = $activity_type
        CREATE (s)-[:BELONGS_TO]->(i)
        RETURN s
        """
        run_query(
            create_step,
            {
                "artifact_id": artifact_id,
                "step_key": step_key,
                "node_id": node_id,
                "node_name": node_name,
                "bpmn_type": bpmn_type,
                "activity_type": activity_type,
            },
        )
        step_count += 1

        # Step 5: Link resources to this Step
        node_resources = node.get("resources", [])
        for resource_filename in node_resources:
            kind = infer_resource_kind(resource_filename)
            resolved_data = resolved_resources.get(resource_filename, {})
            resolved = resolved_data.get("resolved", False)

            # Extract purpose and complexity for groovy resources
            purpose = None
            complexity = None
            if kind == "groovy":
                purpose = resolved_data.get("purpose")
                complexity = resolved_data.get("complexity")

            details_json = json.dumps(resolved_data) if resolved_data else None

            link_resource = """
            MATCH (s:Step {step_key: $step_key})
            MERGE (r:Resource {filename: $filename, kind: $kind})
            ON CREATE SET r.resolved = $resolved, r.details_json = $details_json, r.purpose = $purpose, r.complexity = $complexity
            ON MATCH SET r.resolved = $resolved, r.details_json = $details_json, r.purpose = $purpose, r.complexity = $complexity
            CREATE (s)-[:USES]->(r)
            RETURN r
            """
            run_query(
                link_resource,
                {
                    "step_key": step_key,
                    "filename": resource_filename,
                    "kind": kind,
                    "resolved": resolved,
                    "details_json": details_json,
                    "purpose": purpose,
                    "complexity": complexity,
                },
            )
            resource_count += 1

    # Step 6: Create Step-to-Step edges (NEXT relationships)
    for edge in edges:
        source_ref = edge.get("sourceRef", "")
        target_ref = edge.get("targetRef", "")
        condition = edge.get("condition")

        if not source_ref or not target_ref:
            continue

        link_steps = """
        MATCH (s1:Step {step_key: $source_key})
        MATCH (s2:Step {step_key: $target_key})
        CREATE (s1)-[:NEXT {condition: $condition}]->(s2)
        RETURN s1, s2
        """
        run_query(
            link_steps,
            {
                "source_key": f"{artifact_id}::{source_ref}",
                "target_key": f"{artifact_id}::{target_ref}",
                "condition": condition,
            },
        )

    # Step 7: Create System nodes and link Steps to Systems via message flows
    for msg_flow in message_flows:
        source_ref = msg_flow.get("sourceRef", "")
        target_ref = msg_flow.get("targetRef", "")
        direction = msg_flow.get("direction")
        component_type = msg_flow.get("component_type")
        address = msg_flow.get("address")

        # Find which is a step and which is a system
        source_is_step = any(n.get("id") == source_ref for n in nodes)
        target_is_step = any(n.get("id") == target_ref for n in nodes)

        step_id = None
        system_id = None
        system_name = None

        if source_is_step and not target_is_step:
            step_id = source_ref
            system_id = target_ref
        elif target_is_step and not source_is_step:
            step_id = target_ref
            system_id = source_ref

        # Look up system name
        if system_id:
            for sys in systems:
                if sys.get("id") == system_id:
                    system_name = sys.get("name", system_id)
                    break

        if step_id and system_id and system_name:
            link_to_system = """
            MATCH (s:Step {step_key: $step_key})
            MERGE (sys:System {name: $system_name})
            CREATE (s)-[:CALLS {direction: $direction, component_type: $component_type, address: $address}]->(sys)
            RETURN s, sys
            """
            run_query(
                link_to_system,
                {
                    "step_key": f"{artifact_id}::{step_id}",
                    "system_name": system_name,
                    "direction": direction,
                    "component_type": component_type,
                    "address": address,
                },
            )
            system_count += 1

    # Step 8: Create package-level schema Resource nodes (without USES relationships)
    schemas = resources_list.get("schemas", [])
    for schema_filename in schemas:
        resolved_data = resolved_resources.get(schema_filename, {})
        resolved = resolved_data.get("resolved", False)
        details_json = json.dumps(resolved_data) if resolved_data else None

        create_schema_resource = """
        MERGE (r:Resource {filename: $filename, kind: "schema"})
        ON CREATE SET r.resolved = $resolved, r.details_json = $details_json
        ON MATCH SET r.resolved = $resolved, r.details_json = $details_json
        RETURN r
        """
        run_query(
            create_schema_resource,
            {
                "filename": schema_filename,
                "resolved": resolved,
                "details_json": details_json,
            },
        )
        resource_count += 1

    # Step 9: Create package-scoped externalized Parameter nodes.
    for parameter in externalized_parameters:
        parameter_name = parameter.get("name", "")
        if not parameter_name:
            continue

        create_parameter = """
        MATCH (i:IFlow {id: $artifact_id})
        MERGE (p:Parameter {param_key: $param_key})
        SET p.name = $name,
            p.type = $type,
            p.is_required = $is_required,
            p.attribute_category = $attribute_category,
            p.attribute_label = $attribute_label,
            p.configured_value = $configured_value
        MERGE (i)-[:HAS_PARAMETER]->(p)
        RETURN p
        """
        run_query(
            create_parameter,
            {
                "artifact_id": artifact_id,
                "param_key": f"{artifact_id}::{parameter_name}",
                "name": parameter_name,
                "type": parameter.get("type", ""),
                "is_required": parameter.get("is_required", ""),
                "attribute_category": parameter.get("attribute_category", ""),
                "attribute_label": parameter.get("attribute_label", parameter_name),
                "configured_value": parameter.get("configured_value", ""),
            },
        )
        parameter_count += 1

    return {
        "steps": step_count,
        "resources": resource_count,
        "systems": system_count,
        "message_flows": len(message_flows),
        "parameters": parameter_count,
    }


def infer_resource_kind(filename: str) -> str:
    """Infer resource kind from filename extension."""
    lower_name = filename.lower()
    if lower_name.endswith(".groovy"):
        return "groovy"
    elif lower_name.endswith(".mmap"):
        return "mapping"
    elif lower_name.endswith(".wsdl"):
        return "wsdl"
    elif lower_name.endswith(".xsd"):
        return "schema"
    else:
        return "unknown"


if __name__ == "__main__":
    output_dir = Path("output")

    if not output_dir.exists():
        print(f"Output directory not found: {output_dir}")
        sys.exit(1)

    # Find all *.json files (excluding .groovy_cache subfolder)
    json_files = sorted([f for f in output_dir.glob("*.json")])

    if not json_files:
        print("No JSON artifact files found in output/")
        sys.exit(1)

    print(f"Found {len(json_files)} artifact file(s)")
    print()

    total_steps = 0
    total_resources = 0
    total_systems = 0
    total_message_flows = 0
    total_parameters = 0

    for json_file in json_files:
        try:
            counts = load_artifact(str(json_file))
            total_steps += counts["steps"]
            total_resources += counts["resources"]
            total_systems += counts["systems"]
            total_message_flows += counts["message_flows"]
            total_parameters += counts["parameters"]

            print(f"[OK] {json_file.name}")
            print(
                f"  Steps: {counts['steps']}, Resources: {counts['resources']}, "
                f"Systems: {counts['systems']}, Message flows: {counts['message_flows']}"
                f", Parameters: {counts['parameters']}"
            )
        except Exception as exc:
            print(f"[FAILED] {json_file.name}: {exc}")

    print()
    print("=" * 70)
    print(f"TOTAL LOADED:")
    print(f"  Steps: {total_steps}")
    print(f"  Resources: {total_resources}")
    print(f"  Systems: {total_systems}")
    print(f"  Message Flows: {total_message_flows}")
    print(f"  Parameters: {total_parameters}")
