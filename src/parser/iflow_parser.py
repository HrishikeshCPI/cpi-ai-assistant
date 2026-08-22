from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from lxml import etree

from src.models.schema import IFlowArtifact
from src.parser.parameters_resolver import resolve_parameters
from src.parser.resolver_registry import resolve_resource

BPMN_NS = {
    "bpmn2": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "ifl": "http:///com.sap.ifl.model/Ifl.xsd",
}


def _read_manifest(package_path: Path) -> tuple[str, str, list[str]]:
    manifest_path = package_path / "META-INF" / "MANIFEST.MF"
    warnings: list[str] = []
    properties: dict[str, str] = {}

    if not manifest_path.exists():
        warnings.append(f"Manifest file not found: {manifest_path}")
        return "", "", warnings

    try:
        content = manifest_path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive fallback
        warnings.append(f"Could not read manifest: {exc}")
        return "", "", warnings

    for raw_line in content.splitlines():
        if not raw_line.strip() or ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        properties[key.strip()] = value.strip()

    artifact_id = properties.get("Bundle-SymbolicName", package_path.name)
    artifact_id = artifact_id.split(";", 1)[0].strip()
    version = properties.get("Bundle-Version", "")
    return artifact_id, version, warnings


def _list_folder_files(base_dir: Path) -> list[str]:
    if not base_dir.exists() or not base_dir.is_dir():
        return []
    return sorted(p.name for p in base_dir.iterdir() if p.is_file())


def _read_developer_description(package_path: Path) -> str:
    """Best-effort display metadata; this is deliberately not authoritative."""
    for metainfo_path in package_path.rglob("metainfo.prop"):
        try:
            for line in metainfo_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("description="):
                    return line.split("=", 1)[1]
        except OSError:
            continue
    return ""


def _property_text(property_node: etree._Element) -> tuple[str, str]:
    key = ""
    value = ""
    for child in property_node:
        tag = etree.QName(child).localname.lower()
        if tag == "key" and child.text:
            key = child.text.strip()
        elif tag == "value" and child.text:
            value = child.text.strip()
    return key, value


def _is_externalized(value: str) -> bool:
    """Return whether a value is exactly one CPI externalized placeholder."""
    return re.fullmatch(r"\{\{.*\}\}", value) is not None


def _node_resources(node: etree._Element) -> list[str]:
    resources: list[str] = []
    extension_elements = node.find("bpmn2:extensionElements", namespaces=BPMN_NS)
    if extension_elements is None:
        return resources

    for property_node in extension_elements.findall("ifl:property", namespaces=BPMN_NS):
        key, value = _property_text(property_node)
        if not key or not value:
            continue
        normalized_key = key.lower()
        if "script" in normalized_key or "resource" in normalized_key or "mappingname" in normalized_key:
            if "mappingname" in normalized_key and not value.lower().endswith(".mmap"):
                value = f"{value}.mmap"
            resources.append(value)
    return resources


def _node_type(node: etree._Element) -> str:
    extension_elements = node.find("bpmn2:extensionElements", namespaces=BPMN_NS)
    if extension_elements is None:
        # CPI stores the activity type for error start/end events on the
        # nested errorEventDefinition rather than on the BPMN event itself.
        extension_elements = node.find(
            "bpmn2:errorEventDefinition/bpmn2:extensionElements", namespaces=BPMN_NS
        )
    if extension_elements is None:
        return ""

    for property_node in extension_elements.findall("ifl:property", namespaces=BPMN_NS):
        key, value = _property_text(property_node)
        if key.lower() == "activitytype":
            return value
    return ""


def _node_property(node: etree._Element, property_name: str) -> str:
    """Return an activity extension property by its exact key name."""
    extension_elements = node.find("bpmn2:extensionElements", namespaces=BPMN_NS)
    if extension_elements is None:
        return ""
    for property_node in extension_elements.findall("ifl:property", namespaces=BPMN_NS):
        key, value = _property_text(property_node)
        if key == property_name:
            return value
    return ""


def _node_properties(node: etree._Element) -> dict[str, str]:
    """Return all extension properties on an activity without interpreting them."""
    extension_elements = node.find("bpmn2:extensionElements", namespaces=BPMN_NS)
    if extension_elements is None:
        return {}
    return {
        key: value
        for property_node in extension_elements.findall("ifl:property", namespaces=BPMN_NS)
        for key, value in [_property_text(property_node)]
        if key
    }


def _tag_value(value: str) -> dict[str, Any]:
    return {"value": value, "is_externalized": _is_externalized(value)}


def _parse_enricher_table(value: str) -> list[dict[str, dict[str, Any]]]:
    """Turn CPI's escaped row/cell table XML into JSON-safe rows."""
    if not value:
        return []
    try:
        table = etree.fromstring(f"<table>{value}</table>".encode("utf-8"))
    except etree.XMLSyntaxError:
        return []
    return [
        {
            cell.get("id", ""): _tag_value((cell.text or "").strip())
            for cell in row
            if etree.QName(cell).localname == "cell" and cell.get("id")
        }
        for row in table
        if etree.QName(row).localname == "row"
    ]


def _activity_details(node: etree._Element, activity_type: str) -> dict[str, Any] | None:
    """Interpret only explicitly supported CPI activity types."""
    properties = _node_properties(node)
    if activity_type == "Enricher":
        details: dict[str, Any] = {
            "property_table": _parse_enricher_table(properties.get("propertyTable", "")),
            "header_table": _parse_enricher_table(properties.get("headerTable", "")),
        }
        for key in ("bodyType", "wrapContent"):
            if key in properties:
                details[key] = _tag_value(properties[key])
        return details
    if activity_type == "ProcessCallElement":
        return {"process_id": _tag_value(properties.get("processId", ""))}
    if activity_type == "Multicast":
        # CPI represents Multicast as a parallelGateway.  Preserve every
        # extension property so both known parallel and future sequential
        # variants are fully represented without adapter-specific guessing.
        return {key: _tag_value(value) for key, value in properties.items()}
    if activity_type in {"Splitter", "Gather"}:
        # Verified keys in the supplied examples: splitExprValue, grouping, splitType.
        keys = ("splitExprValue", "grouping", "splitType", "expression", "condition")
        return {key: _tag_value(properties[key]) for key in keys if key in properties}
    if activity_type in {"Filter", "DBstorage"}:
        keys = ("condition", "expression", "query", "tableName", "table", "operation")
        return {key: _tag_value(properties[key]) for key in keys if key in properties}
    if activity_type in {"StartErrorEvent", "ErrorEventSubProcessTemplate", "EndErrorEvent"}:
        # Relationship data is added after the process's scoped graph is read.
        return {"error_event_type": activity_type}
    return None


def _sequence_flow_condition(sequence_flow: etree._Element) -> str | None:
    condition_expression = sequence_flow.find("bpmn2:conditionExpression", namespaces=BPMN_NS)
    if condition_expression is not None and condition_expression.text is not None:
        return condition_expression.text.strip()

    extension_elements = sequence_flow.find("bpmn2:extensionElements", namespaces=BPMN_NS)
    if extension_elements is not None:
        for property_node in extension_elements.findall("ifl:property", namespaces=BPMN_NS):
            key, value = _property_text(property_node)
            if key and value and "condition" in key.lower():
                return value.strip()
    return None


def _extract_message_flow_properties(message_flow: etree._Element) -> dict[str, str]:
    props: dict[str, str] = {}
    extension_elements = message_flow.find("bpmn2:extensionElements", namespaces=BPMN_NS)
    if extension_elements is None:
        return props

    for property_node in extension_elements.findall("ifl:property", namespaces=BPMN_NS):
        key, value = _property_text(property_node)
        if key:
            props[key] = value
    return props


def _parse_process(
    process: etree._Element,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract nodes and sequence flows scoped to one BPMN process element."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for node in process.xpath(
        ".//bpmn2:callActivity | .//bpmn2:serviceTask | .//bpmn2:startEvent | .//bpmn2:endEvent | .//bpmn2:exclusiveGateway | .//bpmn2:parallelGateway | .//bpmn2:subProcess",
        namespaces=BPMN_NS,
    ):
        node_id = node.get("id", "")
        node_name = node.get("name", "")
        bpmn_type = etree.QName(node).localname
        payload: dict[str, Any] = {"id": node_id, "name": node_name, "bpmn_type": bpmn_type}
        activity_type = _node_type(node)
        if bpmn_type == "subProcess" and activity_type != "ErrorEventSubProcessTemplate":
            continue
        if bpmn_type in {"callActivity", "serviceTask"}:
            payload["type"] = activity_type
            payload["resources"] = _node_resources(node)
        details = _activity_details(node, activity_type)
        if details is not None:
            payload["type"] = activity_type
            payload["details"] = details
        nodes.append(payload)

    for sequence_flow in process.xpath(".//bpmn2:sequenceFlow", namespaces=BPMN_NS):
        source_ref = sequence_flow.get("sourceRef", "")
        target_ref = sequence_flow.get("targetRef", "")
        if source_ref or target_ref:
            edge: dict[str, Any] = {"sourceRef": source_ref, "targetRef": target_ref}
            condition = _sequence_flow_condition(sequence_flow)
            if condition is not None:
                edge["condition"] = condition
            edges.append(edge)
    _populate_error_event_details(process, nodes, edges)
    return nodes, edges


def _error_subprocess_owner(node: etree._Element) -> etree._Element | None:
    parent = node.getparent()
    while parent is not None:
        if (
            etree.QName(parent).localname == "subProcess"
            and _node_type(parent) == "ErrorEventSubProcessTemplate"
        ):
            return parent
        parent = parent.getparent()
    return None


def _error_outcome(owner: etree._Element) -> str:
    if any(_node_type(event) == "EndErrorEvent" for event in owner.xpath(".//bpmn2:endEvent", namespaces=BPMN_NS)):
        return "re_raise"
    if any("log" in (element.get("name", "").lower()) for element in owner.xpath(".//bpmn2:callActivity | .//bpmn2:serviceTask", namespaces=BPMN_NS)):
        return "log"
    return "silent_end"


def _populate_error_event_details(
    process: etree._Element, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    """Attach scoped trigger/outcome facts to the three CPI error node types."""
    xml_nodes = {
        node.get("id", ""): node
        for node in process.xpath(".//*[@id]", namespaces=BPMN_NS)
        if node.get("id")
    }
    for payload in nodes:
        activity_type = payload.get("type")
        if activity_type not in {"StartErrorEvent", "ErrorEventSubProcessTemplate", "EndErrorEvent"}:
            continue
        element = xml_nodes.get(payload["id"])
        if element is None:
            continue
        owner = element if activity_type == "ErrorEventSubProcessTemplate" else _error_subprocess_owner(element)
        if owner is None:
            # An EndErrorEvent can sit directly in a process, outside an
            # ErrorEventSubProcessTemplate.  Its incoming flow is still an
            # unambiguous trigger and its BPMN semantics re-raise the error.
            payload["details"] = {
                "trigger": {
                    "incoming_node_ids": [
                        edge["sourceRef"] for edge in edges if edge.get("targetRef") == payload["id"]
                    ],
                    "triggered_by": "process_error_flow",
                },
                "terminal_outcome": "re_raise" if activity_type == "EndErrorEvent" else "silent_end",
            }
            continue
        start_ids = [
            event.get("id", "")
            for event in owner.xpath(".//bpmn2:startEvent", namespaces=BPMN_NS)
            if _node_type(event) == "StartErrorEvent"
        ]
        incoming_ids = [edge["sourceRef"] for edge in edges if edge.get("targetRef") == payload["id"]]
        details: dict[str, Any] = {
            "trigger": {
                "subprocess_id": owner.get("id", ""),
                "subprocess_name": owner.get("name", ""),
                "start_error_event_ids": start_ids,
            },
            "terminal_outcome": _error_outcome(owner),
        }
        if activity_type == "EndErrorEvent":
            details["trigger"]["incoming_node_ids"] = incoming_ids
        elif activity_type == "ErrorEventSubProcessTemplate":
            details["trigger"]["triggered_by"] = "exception_subprocess"
        else:
            details["trigger"]["triggered_by"] = "error_event"
        payload["details"] = details


def _process_is_error_start(process: etree._Element) -> bool:
    """Return whether the process's first BPMN node is an error start event."""
    for child in process:
        if etree.QName(child).localname not in {
            "callActivity", "serviceTask", "startEvent", "endEvent", "exclusiveGateway"
        }:
            continue
        return (
            etree.QName(child).localname == "startEvent"
            and child.find("bpmn2:errorEventDefinition", namespaces=BPMN_NS) is not None
        )
    return False


def _parse_iflw_file(
    iflw_path: Path,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    processes: list[dict[str, Any]],
    message_flows: list[dict[str, Any]],
    systems: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    try:
        tree = etree.parse(str(iflw_path))
    except (etree.XMLSyntaxError, OSError, ValueError) as exc:
        warnings.append(f"Malformed or unreadable IFLW file: {iflw_path.name} ({exc})")
        return

    root = tree.getroot()
    if root is None:
        warnings.append(f"Empty IFLW document: {iflw_path.name}")
        return

    process_elements = root.findall("bpmn2:process", namespaces=BPMN_NS)
    main_process_ids = {
        participant.get("processRef", "")
        for participant in root.xpath(".//bpmn2:participant", namespaces=BPMN_NS)
        if participant.get("id", "") == "Participant_Process_1"
    }
    if len(process_elements) == 1:
        main_process_ids.add(process_elements[0].get("id", ""))

    error_process_ids: set[str] = set()
    for error_subprocess in root.xpath(".//bpmn2:subProcess", namespaces=BPMN_NS):
        if _node_type(error_subprocess) != "ErrorEventSubProcessTemplate":
            continue
        for node in error_subprocess.xpath(
            ".//bpmn2:callActivity | .//bpmn2:serviceTask", namespaces=BPMN_NS
        ):
            if _node_type(node) == "ProcessCallElement":
                process_id = _node_property(node, "processId")
                if process_id:
                    error_process_ids.add(process_id)

    for process in process_elements:
        process_id = process.get("id", "")
        process_nodes, process_edges = _parse_process(process)
        if process_id in main_process_ids:
            classification = "main"
            nodes.extend(process_nodes)
            edges.extend(process_edges)
        elif process_id in error_process_ids or _process_is_error_start(process):
            classification = "error_handling"
        else:
            classification = "local_subprocess"
        processes.append(
            {
                "id": process_id,
                "classification": classification,
                "nodes": process_nodes,
                "edges": process_edges,
            }
        )

    # Error-process callers are represented as ProcessCallElement nodes in the
    # owning process.  Keep the inferred relationship with the process itself.
    for process in processes:
        if process["classification"] != "error_handling":
            continue
        triggers = [
            node["id"]
            for candidate in processes
            for node in candidate["nodes"]
            if node.get("type") == "ProcessCallElement"
            and node.get("details", {}).get("process_id", {}).get("value") == process["id"]
        ]
        terminal_nodes = [node for node in process["nodes"] if node.get("bpmn_type") == "endEvent"]
        terminal_types = [node.get("type", "") for node in terminal_nodes]
        if any(node_type == "EndErrorEvent" for node_type in terminal_types):
            outcome = "re_raise"
        elif any("log" in node.get("name", "").lower() for node in process["nodes"]):
            outcome = "log"
        else:
            outcome = "silent_end"
        process["error_details"] = {"trigger_node_ids": triggers, "terminal_outcome": outcome}

    for message_flow in root.xpath(".//bpmn2:messageFlow", namespaces=BPMN_NS):
        payload: dict[str, Any] = {
            "id": message_flow.get("id", ""),
            "name": message_flow.get("name", ""),
            "sourceRef": message_flow.get("sourceRef", ""),
            "targetRef": message_flow.get("targetRef", ""),
        }
        props = _extract_message_flow_properties(message_flow)
        normalized_props = {key.lower(): value for key, value in props.items()}
        payload["properties"] = {
            key: {"value": value, "is_externalized": _is_externalized(value)}
            for key, value in props.items()
        }
        for key in ("direction", "componenttype", "transportprotocol", "address", "url"):
            if key in normalized_props:
                payload["direction" if key == "direction" else "component_type" if key == "componenttype" else "transport_protocol" if key == "transportprotocol" else "address"] = normalized_props[key]
        if "direction" not in payload and "direction" in normalized_props:
            payload["direction"] = normalized_props["direction"]
        if "component_type" not in payload and "componenttype" in normalized_props:
            payload["component_type"] = normalized_props["componenttype"]
        if "transport_protocol" not in payload and "transportprotocol" in normalized_props:
            payload["transport_protocol"] = normalized_props["transportprotocol"]
        if "address" not in payload and "address" in normalized_props:
            payload["address"] = normalized_props["address"]
        if payload.get("sourceRef") or payload.get("targetRef"):
            message_flows.append(payload)

    for participant in root.xpath(".//bpmn2:participant", namespaces=BPMN_NS):
        participant_id = participant.get("id", "")
        participant_name = participant.get("name", "")
        if participant_id or participant_name:
            systems.append({"id": participant_id, "name": participant_name})


def parse_package(package_path: str) -> IFlowArtifact:
    package_dir = Path(package_path)
    warnings: list[str] = []

    if not package_dir.exists() or not package_dir.is_dir():
        warnings.append(f"Package path does not exist or is not a directory: {package_path}")
        return IFlowArtifact(
            artifact_id=Path(package_path).name or "unknown-package",
            version="",
            nodes=[],
            edges=[],
            resources={"scripts": [], "mappings": [], "schemas": []},
            parse_warnings=warnings,
        )

    artifact_id, version, manifest_warnings = _read_manifest(package_dir)
    warnings.extend(manifest_warnings)
    artifact_id = artifact_id or package_dir.name
    developer_description = _read_developer_description(package_dir)

    script_dir = package_dir / "src" / "main" / "resources" / "script"
    mapping_dir = package_dir / "src" / "main" / "resources" / "mapping"
    xsd_dir = package_dir / "src" / "main" / "resources" / "xsd"
    wsdl_dir = package_dir / "src" / "main" / "resources" / "wsdl"

    scripts = _list_folder_files(script_dir)
    mappings = _list_folder_files(mapping_dir)
    schemas = _list_folder_files(xsd_dir) + _list_folder_files(wsdl_dir)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    processes: list[dict[str, Any]] = []
    message_flows: list[dict[str, Any]] = []
    systems: list[dict[str, Any]] = []

    iflw_paths = sorted(package_dir.rglob("*.iflw"))
    if not iflw_paths:
        warnings.append(f"No .iflw file found under package: {package_dir}")
    else:
        for iflw_path in iflw_paths:
            _parse_iflw_file(iflw_path, nodes, edges, processes, message_flows, systems, warnings)

    resolved_resources: dict[str, dict[str, Any]] = {}
    for resource_name in scripts + mappings + schemas:
        base = script_dir if resource_name.lower().endswith(".groovy") else mapping_dir if resource_name.lower().endswith(".mmap") else xsd_dir if resource_name.lower().endswith(".xsd") else wsdl_dir if resource_name.lower().endswith(".wsdl") else None
        if base is None:
            continue
        resource_path = base / resource_name
        resolved_resources[resource_name] = resolve_resource(str(resource_path))

    parameter_result = resolve_parameters(str(package_dir))
    warnings.extend(parameter_result["parse_warnings"])

    artifact = IFlowArtifact(
        artifact_id=artifact_id,
        version=version,
        developer_description=developer_description,
        nodes=nodes,
        edges=edges,
        processes=processes,
        message_flows=message_flows,
        systems=systems,
        resolved_resources=resolved_resources,
        externalized_parameters=parameter_result["parameters"],
        resources={
            "scripts": scripts,
            "mappings": mappings,
            "schemas": schemas,
        },
        parse_warnings=warnings,
    )
    return artifact


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m src.parser.iflow_parser <package_folder>")

    package_root = Path(sys.argv[1]).resolve()
    artifact = parse_package(str(package_root))
    payload = artifact.model_dump_json(indent=2)
    print(payload)

    output_root = Path(__file__).resolve().parents[2] / "output"
    output_root.mkdir(parents=True, exist_ok=True)
    output_file = output_root / f"{artifact.artifact_id}.json"
    output_file.write_text(payload, encoding="utf-8")
