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
        Dict with counts: {"steps": int, "processes": int, "resources": int, "systems": int,
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
    processes = artifact.get("processes", [])
    message_flows = artifact.get("message_flows", [])
    systems = artifact.get("systems", [])
    resolved_resources = artifact.get("resolved_resources", {})
    resources_list = artifact.get("resources", {})
    externalized_parameters = artifact.get("externalized_parameters", [])

    if not artifact_id:
        raise ValueError(f"No artifact_id found in {json_path}")

    # Step 1: Clean up existing IFlow, Steps, Processes, and package-scoped
    # Parameters, Package, and System nodes are shared across IFlows. Resources
    # are artifact-scoped, so their identity is ``artifact_id::filename``.
    # The legacy cleanup also removes Steps from artifacts loaded
    # before Process nodes were introduced.
    cleanup_parameters_query = """
    MATCH (i:IFlow {id: $artifact_id})-[:HAS_PARAMETER]->(p:Parameter)
    DETACH DELETE p
    """
    run_query(cleanup_parameters_query, {"artifact_id": artifact_id})

    cleanup_legacy_steps_query = """
    MATCH (i:IFlow {id: $artifact_id})
    OPTIONAL MATCH (i)<-[:BELONGS_TO]-(s:Step)
    DETACH DELETE s
    """
    run_query(cleanup_legacy_steps_query, {"artifact_id": artifact_id})

    cleanup_processes_query = """
    MATCH (i:IFlow {id: $artifact_id})
    OPTIONAL MATCH (i)<-[:PART_OF]-(p:Process)
    OPTIONAL MATCH (p)<-[:BELONGS_TO]-(s:Step)
    DETACH DELETE s, p
    """
    run_query(cleanup_processes_query, {"artifact_id": artifact_id})

    cleanup_iflow_query = """
    MATCH (i:IFlow {id: $artifact_id})
    DETACH DELETE i
    """
    run_query(cleanup_iflow_query, {"artifact_id": artifact_id})

    # Remove the prior artifact-scoped resource set so a reload also removes
    # resources no longer present in the artifact output.
    cleanup_resources_query = """
    MATCH (r:Resource {artifact_id: $artifact_id})
    DETACH DELETE r
    """
    run_query(cleanup_resources_query, {"artifact_id": artifact_id})

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

    # The new parser output keeps nodes and edges within their owning process.
    # Retain a single main process fallback for older output files.
    if not processes:
        processes = [{
            "id": "main",
            "classification": "main",
            "nodes": nodes,
            "edges": edges,
        }]

    process_count = 0
    node_ids = {
        node.get("id", "")
        for process in processes
        for node in process.get("nodes", [])
    }

    # Step 4: Create Process nodes, then their Step nodes.
    for process in processes:
        process_id = process.get("id", "")
        if not process_id:
            continue

        process_key = f"{artifact_id}::{process_id}"
        create_process = """
        MATCH (i:IFlow {id: $artifact_id})
        MERGE (p:Process {process_key: $process_key})
        SET p.id = $process_id, p.classification = $classification
        MERGE (p)-[:PART_OF]->(i)
        RETURN p
        """
        run_query(
            create_process,
            {
                "artifact_id": artifact_id,
                "process_key": process_key,
                "process_id": process_id,
                "classification": process.get("classification"),
            },
        )
        process_count += 1

        for node in process.get("nodes", []):
            node_id = node.get("id", "")
            node_name = node.get("name", "")
            bpmn_type = node.get("bpmn_type", "")
            activity_type = node.get("type")

            if not node_id:
                continue

            step_key = f"{artifact_id}::{node_id}"
            details = node.get("details")
            details_json = json.dumps(details) if "details" in node else None
            split_expression = None
            multicast_type = None
            error_trigger_type = None
            if activity_type == "Splitter":
                split_expression = (details or {}).get("splitExprValue", {}).get("value")
            elif activity_type == "Multicast":
                multicast_type = (details or {}).get("subActivityType", {}).get("value")
            elif activity_type in {"StartErrorEvent", "ErrorEventSubProcessTemplate"}:
                error_trigger_type = (details or {}).get("trigger", {}).get("triggered_by")

            create_step = """
            MATCH (p:Process {process_key: $process_key})
            MERGE (s:Step {step_key: $step_key})
            SET s.id = $node_id,
                s.name = $node_name,
                s.bpmn_type = $bpmn_type,
                s.activity_type = $activity_type,
                s.details_json = $details_json,
                s.split_expression = $split_expression,
                s.multicast_type = $multicast_type,
                s.error_trigger_type = $error_trigger_type
            MERGE (s)-[:BELONGS_TO]->(p)
            RETURN s
            """
            run_query(
                create_step,
                {
                    "process_key": process_key,
                    "step_key": step_key,
                    "node_id": node_id,
                    "node_name": node_name,
                    "bpmn_type": bpmn_type,
                    "activity_type": activity_type,
                    "details_json": details_json,
                    "split_expression": split_expression,
                    "multicast_type": multicast_type,
                    "error_trigger_type": error_trigger_type,
                },
            )
            step_count += 1

            # Step 5: Link resources to this Step
            node_resources = node.get("resources", [])
            for resource_filename in node_resources:
                resource_key = f"{artifact_id}::{resource_filename}"
                kind = infer_resource_kind(resource_filename)
                resolved_data = resolved_resources.get(resource_filename, {})
                resolved = resolved_data.get("resolved", False)

                # Extract resource-specific parser enrichments.
                purpose = resolved_data.get("purpose") if kind == "groovy" else None
                complexity = resolved_data.get("complexity") if kind == "groovy" else None
                cpi_apis_json = json.dumps(resolved_data.get("cpi_apis", [])) if kind == "groovy" else None
                mapping_format = resolved_data.get("format") if kind == "mapping" else None
                if mapping_format not in {"xitrafo", "java_operation_mapping"}:
                    mapping_format = None
                has_complex_transformations = (
                    any(mapping.get("raw_structure") is not None for mapping in resolved_data.get("field_mappings", []))
                    if kind == "mapping" else None
                )

                resource_details_json = json.dumps(resolved_data) if resolved_data else None

                link_resource = """
                MATCH (s:Step {step_key: $step_key})
                MERGE (r:Resource {resource_key: $resource_key})
                SET r.filename = $filename,
                    r.artifact_id = $artifact_id,
                    r.kind = $kind,
                    r.resolved = $resolved,
                    r.details_json = $details_json,
                    r.purpose = $purpose,
                    r.complexity = $complexity,
                    r.cpi_apis_json = $cpi_apis_json,
                    r.mapping_format = $mapping_format,
                    r.has_complex_transformations = $has_complex_transformations
                MERGE (s)-[:USES]->(r)
                RETURN r
                """
                run_query(
                    link_resource,
                    {
                        "step_key": step_key,
                        "resource_key": resource_key,
                        "artifact_id": artifact_id,
                        "filename": resource_filename,
                        "kind": kind,
                        "resolved": resolved,
                        "details_json": resource_details_json,
                        "purpose": purpose,
                        "complexity": complexity,
                        "cpi_apis_json": cpi_apis_json,
                        "mapping_format": mapping_format,
                        "has_complex_transformations": has_complex_transformations,
                    },
                )
                resource_count += 1

    # Step 6: Create Step-to-Step edges (NEXT relationships).
    for process in processes:
        for edge in process.get("edges", []):
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

    # Step 7: Link ProcessCallElement Steps to processes in the same IFlow.
    for process in processes:
        for node in process.get("nodes", []):
            if node.get("type") != "ProcessCallElement":
                continue
            process_id = (node.get("details") or {}).get("process_id", {}).get("value")
            if not process_id:
                continue
            run_query(
                """
                MATCH (s:Step {step_key: $step_key})
                MATCH (p:Process {process_key: $process_key})
                MERGE (s)-[:INVOKES]->(p)
                RETURN s, p
                """,
                {
                    "step_key": f"{artifact_id}::{node.get('id', '')}",
                    "process_key": f"{artifact_id}::{process_id}",
                },
            )

    # Step 8: Create System nodes and link Steps to Systems via message flows
    for msg_flow in message_flows:
        source_ref = msg_flow.get("sourceRef", "")
        target_ref = msg_flow.get("targetRef", "")
        direction = msg_flow.get("direction")
        component_type = msg_flow.get("component_type")
        address = msg_flow.get("address")
        properties = msg_flow.get("properties")
        properties_json = json.dumps(properties) if isinstance(properties, dict) else None
        externalized_count = sum(
            value.get("is_externalized") is True
            for value in (properties or {}).values()
            if isinstance(value, dict)
        )
        literal_count = sum(
            value.get("is_externalized") is False
            for value in (properties or {}).values()
            if isinstance(value, dict)
        )

        # Find which is a step and which is a system
        source_is_step = source_ref in node_ids
        target_is_step = target_ref in node_ids

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
            CREATE (s)-[:CALLS {direction: $direction, component_type: $component_type, address: $address, properties_json: $properties_json, externalized_count: $externalized_count, literal_count: $literal_count}]->(sys)
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
                    "properties_json": properties_json,
                    "externalized_count": externalized_count,
                    "literal_count": literal_count,
                },
            )
            system_count += 1

    # Step 9: Create package-level schema Resource nodes (without USES relationships)
    schemas = resources_list.get("schemas", [])
    for schema_filename in schemas:
        resource_key = f"{artifact_id}::{schema_filename}"
        resolved_data = resolved_resources.get(schema_filename, {})
        resolved = resolved_data.get("resolved", False)
        details_json = json.dumps(resolved_data) if resolved_data else None

        create_schema_resource = """
        MERGE (r:Resource {resource_key: $resource_key})
        SET r.filename = $filename,
            r.artifact_id = $artifact_id,
            r.kind = "schema",
            r.resolved = $resolved,
            r.details_json = $details_json
        RETURN r
        """
        run_query(
            create_schema_resource,
            {
                "resource_key": resource_key,
                "artifact_id": artifact_id,
                "filename": schema_filename,
                "resolved": resolved,
                "details_json": details_json,
            },
        )
        resource_count += 1

    # Step 10: Create package-scoped externalized Parameter nodes.
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
        "processes": process_count,
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

    # Find artifact JSON files; subflow_links.json is a relationship manifest,
    # not an IFlowArtifact and is loaded separately by load_subflow_links.
    json_files = sorted(
        f for f in output_dir.glob("*.json") if f.name != "subflow_links.json"
    )

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
