"""Assemble Neo4j-backed content for a single iFlow technical specification."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.agent.tools import (
    describe_iflow,
    get_adapter_security_summary,
    get_error_handling_coverage,
    get_iflow_diagram,
    get_iflow_metadata,
    get_iflow_parameters,
    get_iflow_processes,
    get_iflow_resources,
    get_iflow_systems,
    get_subflow_chain,
)


def _field_mappings(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract resolved field mappings from mapping resource details."""
    mappings: list[dict[str, Any]] = []
    for resource in resources:
        if resource.get("kind") != "mapping":
            continue
        details = resource.get("details_json")
        if not details:
            continue
        try:
            resolved = json.loads(details)
        except (TypeError, json.JSONDecodeError):
            continue
        for mapping in resolved.get("field_mappings", []):
            mappings.append({"resource": resource.get("filename", ""), **mapping})
    return mappings


def _group_parameters(parameters: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for parameter in parameters:
        if "error" in parameter:
            grouped["_errors"].append(parameter)
        else:
            grouped[parameter.get("category") or "Uncategorized"].append(parameter)
    return dict(grouped)


def _scope_cache_dir() -> Path:
    cache_dir = Path("output/.scope_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def generate_scope_summary(artifact_id: str) -> str:
    """Generate or retrieve a cached business-level iFlow scope summary."""
    iflow = describe_iflow(artifact_id)
    systems = get_iflow_systems(artifact_id)
    resources = get_iflow_resources(artifact_id)
    steps = sorted(iflow.get("steps", []), key=lambda step: step.get("id", ""))
    step_count = len(steps)

    hash_input = json.dumps(
        {
            "systems": systems,
            "resources": resources,
            "steps": steps,
            "step_count": step_count,
        },
        sort_keys=True,
        default=str,
    )
    content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    cache_path = _scope_cache_dir() / f"{content_hash}.txt"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    system_lines = []
    for system in systems:
        if "error" in system:
            continue
        system_name = system.get("system_name", "")
        direction = system.get("direction", "")
        if direction == "Sender":
            role = "this system TRIGGERS the integration, it does not necessarily provide the business data"
        elif direction == "Receiver":
            role = "this system is CALLED BY the integration to retrieve or send data"
        else:
            role = "integration direction is not specified"
        system_lines.append(f"- {system_name} (direction: {direction}) - {role}")
    key_logic = [
        {
            "filename": resource.get("filename", ""),
            "purpose": resource.get("purpose"),
            "complexity": resource.get("complexity"),
        }
        for resource in resources
        if resource.get("purpose") is not None
    ]
    process_steps = [
        f"{step.get('name', '')} ({step.get('activity_type') or step.get('bpmn_type', '')})"
        for step in steps
    ]
    prompt = f"""Write a 2-3 sentence business-toned summary of what this SAP CPI integration does, suitable for a Technical Specification document's 'Scope' section. Do not describe individual technical steps - describe the business purpose and outcome only. Identify the core data operation (e.g. what data is being read, transformed, or sent) and make that the focus of the summary - do not focus on supporting/infrastructure steps like header setting or logging. Base the data flow direction strictly on which system is the Sender (trigger) vs Receiver (called system) - do not assume the Sender provides the data being processed. Trace the actual step sequence in order to determine where data originates and where it ends up.

Systems involved:
{chr(10).join(system_lines) or 'None'}
Process steps in order: {', '.join(process_steps) or 'None'}
Key business logic: {json.dumps(key_logic)}

Respond with only the summary paragraph, no preamble."""

    # Import lazily so cached summaries do not require Gemini configuration.
    from src.agent.chat import client

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
    )
    summary = (response.text or "").strip()
    if not summary:
        raise RuntimeError("Gemini returned an empty scope summary")

    cache_path.write_text(summary, encoding="utf-8")
    return summary


def build_ts_content(artifact_id: str) -> dict:
    """Gather all Neo4j-backed data needed for an iFlow TS document."""
    iflow = describe_iflow(artifact_id)
    metadata = get_iflow_metadata(artifact_id)
    resources = get_iflow_resources(artifact_id)
    systems = get_iflow_systems(artifact_id)
    parameters = get_iflow_parameters(artifact_id)
    processes = get_iflow_processes(artifact_id)
    subflows = get_subflow_chain(artifact_id)
    error_handling = get_error_handling_coverage()

    resource_details = []
    for resource in resources:
        details = resource.get("details_json")
        business_note = None
        if details:
            try:
                business_note = json.loads(details).get("business_note")
            except (TypeError, json.JSONDecodeError):
                business_note = None
        resource_details.append({
            key: value for key, value in resource.items() if key != "details_json"
        } | {"business_note": business_note})
    steps = sorted(iflow.get("steps", []), key=lambda step: step.get("id", ""))

    # Extract error handling details for this specific iFlow
    error_details_by_process = {}
    if "iflows_with_error_handling" in error_handling:
        for entry in error_handling["iflows_with_error_handling"]:
            if entry["artifact_id"] == artifact_id:
                for detail in entry["details"]:
                    error_details_by_process[detail["process_id"]] = detail
                break

    return {
        "artifact_id": iflow.get("artifact_id", artifact_id),
        "version": iflow.get("version", ""),
        "developer_description": metadata.get("developer_description", ""),
        "scope_summary": generate_scope_summary(artifact_id),
        "steps": steps,
        "systems": systems,
        "resources": resource_details,
        "field_mappings": _field_mappings(resources),
        "parameters": _group_parameters(parameters),
        "diagram": get_iflow_diagram(artifact_id),
        "processes": processes.get("processes", []),
        "error_details_by_process": error_details_by_process,
        "subflows": subflows,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m src.docgen.ts_document <artifact_id>")

    print(json.dumps(build_ts_content(sys.argv[1]), indent=2))
