"""
Generate Mermaid flowcharts from iFlow data stored in Neo4j.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from src.graph.neo4j_client import run_query


def _format_condition(condition: str, max_length: int = 35) -> str:
    """Show the distinguishing comparison at the end of an XPath condition."""
    comparison = re.search(
        r"(?:/|^)([A-Za-z_][\w:.-]*)\s*(=|!=|<=|>=|<|>)\s*(.+?)\s*$",
        condition,
    )
    if comparison:
        label = " ".join(comparison.groups())
        if len(label) <= max_length:
            return label
        return label[-max_length:]

    return condition[-max_length:]


def generate_mermaid(artifact_id: str) -> str:
    """
    Generate a Mermaid flowchart for an iFlow from Neo4j data.
    
    Args:
        artifact_id: The artifact ID of the iFlow (e.g., "NorthWind_Customer_OData_Git")
    
    Returns:
        A complete Mermaid flowchart string (flowchart TD format)
    """
    # Query 1: Get all steps for the iFlow
    steps_query = """
    MATCH (i:IFlow {id: $artifact_id})<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s:Step)
    RETURN s.id AS step_id, s.name AS step_name, s.bpmn_type AS bpmn_type
    ORDER BY s.id
    """
    steps = run_query(steps_query, {"artifact_id": artifact_id})
    
    if not steps:
        return f"flowchart TD\n    note[\"No steps found for {artifact_id}\"]"
    
    # Query 2: Get all NEXT edges between steps
    edges_query = """
    MATCH (i:IFlow {id: $artifact_id})<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s1:Step)
    MATCH (i)<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s2:Step)
    MATCH (s1)-[next:NEXT]->(s2)
    RETURN s1.id AS source_id, s2.id AS target_id, next.condition AS condition
    ORDER BY s1.id, s2.id
    """
    edges = run_query(edges_query, {"artifact_id": artifact_id})
    
    # Query 3: Get all resources used by each step
    resources_query = """
    MATCH (i:IFlow {id: $artifact_id})<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s:Step)-[:USES]->(r:Resource)
    RETURN s.id AS step_id, r.filename AS filename, r.kind AS kind
    ORDER BY s.id, r.filename
    """
    resources = run_query(resources_query, {"artifact_id": artifact_id})
    
    # Query 4: Get all systems called by steps
    systems_query = """
    MATCH (i:IFlow {id: $artifact_id})<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s:Step)-[calls:CALLS]->(sys:System)
    RETURN s.id AS step_id, sys.name AS system_name, calls.direction AS direction, calls.component_type AS component_type
    ORDER BY s.id, sys.name
    """
    systems = run_query(systems_query, {"artifact_id": artifact_id})
    
    # Build resource map: step_id -> list of resources
    resource_map = {}
    for r in resources:
        step_id = r["step_id"]
        if step_id not in resource_map:
            resource_map[step_id] = []
        resource_map[step_id].append(r)
    
    # Build system map: step_id -> list of systems
    system_map = {}
    for s in systems:
        step_id = s["step_id"]
        if step_id not in system_map:
            system_map[step_id] = []
        system_map[step_id].append(s)
    
    # Get unique systems for node definitions
    unique_systems = {}
    for s in systems:
        system_name = s["system_name"]
        if system_name not in unique_systems:
            unique_systems[system_name] = s
    
    # Start building Mermaid output
    lines = ["flowchart TD"]
    
    # Step 1: Define all step nodes
    for step in steps:
        step_id = step["step_id"]
        step_name = step["step_name"]
        bpmn_type = step["bpmn_type"] or ""
        
        # Build label: step name + type on separate line
        label_parts = [step_name]
        if bpmn_type:
            label_parts.append(bpmn_type)
        
        # Add resources to label if any
        if step_id in resource_map:
            for res in resource_map[step_id]:
                res_filename = res["filename"]
                label_parts.append(f"→ {res_filename}")
        
        label = "<br/>".join(label_parts)
        
        # Use different syntax for start/end events
        if bpmn_type in ["startEvent", "endEvent"]:
            lines.append(f'    {step_id}(("{label}"))')
        else:
            lines.append(f'    {step_id}["{label}"]')
    
    # Step 2: Define all system nodes (styled as external)
    for system_name in unique_systems:
        # Sanitize system name for node ID
        system_id = system_name.replace(" ", "_").replace("-", "_")
        lines.append(f'    {system_id}["🌐 {system_name}"]')
    
    # Step 3: Add NEXT edges (process flow)
    for edge in edges:
        source_id = edge["source_id"]
        target_id = edge["target_id"]
        condition = edge["condition"]
        
        if condition:
            condition_label = _format_condition(condition)
            lines.append(f'    {source_id} -->|"{condition_label}"| {target_id}')
        else:
            lines.append(f'    {source_id} --> {target_id}')
    
    # Step 4: Add CALLS edges (to systems) - dashed line
    for sys in systems:
        step_id = sys["step_id"]
        system_name = sys["system_name"]
        direction = sys["direction"] or "Send"
        component_type = sys["component_type"] or "Unknown"
        
        # Sanitize system name for node ID
        system_id = system_name.replace(" ", "_").replace("-", "_")
        
        # Build edge label
        edge_label = f"{direction}: {component_type}"
        
        # Use dashed edge for system calls
        lines.append(f'    {step_id} -.->|"{edge_label}"| {system_id}')
    
    # Step 5: Add styling for system nodes
    lines.append("")
    lines.append("    classDef systemNode fill:#FFE4B5,stroke:#FF8C00,stroke-width:2px,color:#000")
    for system_name in unique_systems:
        system_id = system_name.replace(" ", "_").replace("-", "_")
        lines.append(f'    class {system_id} systemNode')
    
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Mermaid flowchart for an iFlow")
    artifact_group = parser.add_mutually_exclusive_group(required=True)
    artifact_group.add_argument(
        "--artifact-id",
        help="Artifact ID of the iFlow (e.g., NorthWind_Customer_OData_Git)"
    )
    artifact_group.add_argument(
        "--all",
        action="store_true",
        help="Generate diagrams for every iFlow in Neo4j"
    )
    
    args = parser.parse_args()
    diagrams_dir = Path("output/diagrams")
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    if args.all:
        iflow_rows = run_query("MATCH (i:IFlow) RETURN i.id AS artifact_id ORDER BY i.id")
        for row in iflow_rows:
            artifact_id = row["artifact_id"]
            output_file = diagrams_dir / f"{artifact_id}.mmd"
            mermaid_output = generate_mermaid(artifact_id)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(mermaid_output)
            print(f"[OK] Diagram written to: {output_file}")
    else:
        artifact_id = args.artifact_id
        mermaid_output = generate_mermaid(artifact_id)
        print(mermaid_output)

        output_file = diagrams_dir / f"{artifact_id}.mmd"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(mermaid_output)
        print(f"\n\n[OK] Diagram written to: {output_file}", file=__import__("sys").stderr)
