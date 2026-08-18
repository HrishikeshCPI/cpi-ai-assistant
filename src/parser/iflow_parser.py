from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from lxml import etree

from src.models.schema import IFlowArtifact
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
        return ""

    for property_node in extension_elements.findall("ifl:property", namespaces=BPMN_NS):
        key, value = _property_text(property_node)
        if key.lower() == "activitytype":
            return value
    return ""


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
        if key and value:
            props[key.lower()] = value.strip()
    return props


def _parse_iflw_file(
    iflw_path: Path,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
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

    for node in root.xpath(
        ".//bpmn2:callActivity | .//bpmn2:serviceTask | .//bpmn2:startEvent | .//bpmn2:endEvent | .//bpmn2:exclusiveGateway",
        namespaces=BPMN_NS,
    ):
        node_id = node.get("id", "")
        node_name = node.get("name", "")
        bpmn_type = etree.QName(node).localname
        payload: dict[str, Any] = {"id": node_id, "name": node_name, "bpmn_type": bpmn_type}
        if bpmn_type in {"callActivity", "serviceTask"}:
            payload["type"] = _node_type(node)
            payload["resources"] = _node_resources(node)
        nodes.append(payload)

    for sequence_flow in root.xpath(".//bpmn2:sequenceFlow", namespaces=BPMN_NS):
        source_ref = sequence_flow.get("sourceRef", "")
        target_ref = sequence_flow.get("targetRef", "")
        if source_ref or target_ref:
            edge: dict[str, Any] = {"sourceRef": source_ref, "targetRef": target_ref}
            condition = _sequence_flow_condition(sequence_flow)
            if condition is not None:
                edge["condition"] = condition
            edges.append(edge)

    for message_flow in root.xpath(".//bpmn2:messageFlow", namespaces=BPMN_NS):
        payload: dict[str, Any] = {
            "id": message_flow.get("id", ""),
            "name": message_flow.get("name", ""),
            "sourceRef": message_flow.get("sourceRef", ""),
            "targetRef": message_flow.get("targetRef", ""),
        }
        props = _extract_message_flow_properties(message_flow)
        for key in ("direction", "componenttype", "transportprotocol", "address", "url"):
            if key in props:
                payload["direction" if key == "direction" else "component_type" if key == "componenttype" else "transport_protocol" if key == "transportprotocol" else "address"] = props[key]
        if "direction" not in payload and "direction" in props:
            payload["direction"] = props["direction"]
        if "component_type" not in payload and "componenttype" in props:
            payload["component_type"] = props["componenttype"]
        if "transport_protocol" not in payload and "transportprotocol" in props:
            payload["transport_protocol"] = props["transportprotocol"]
        if "address" not in payload and "address" in props:
            payload["address"] = props["address"]
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

    script_dir = package_dir / "src" / "main" / "resources" / "script"
    mapping_dir = package_dir / "src" / "main" / "resources" / "mapping"
    xsd_dir = package_dir / "src" / "main" / "resources" / "xsd"
    wsdl_dir = package_dir / "src" / "main" / "resources" / "wsdl"

    scripts = _list_folder_files(script_dir)
    mappings = _list_folder_files(mapping_dir)
    schemas = _list_folder_files(xsd_dir) + _list_folder_files(wsdl_dir)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    message_flows: list[dict[str, Any]] = []
    systems: list[dict[str, Any]] = []

    iflw_paths = sorted(package_dir.rglob("*.iflw"))
    if not iflw_paths:
        warnings.append(f"No .iflw file found under package: {package_dir}")
    else:
        for iflw_path in iflw_paths:
            _parse_iflw_file(iflw_path, nodes, edges, message_flows, systems, warnings)

    resolved_resources: dict[str, dict[str, Any]] = {}
    for resource_name in scripts + mappings + schemas:
        base = script_dir if resource_name.lower().endswith(".groovy") else mapping_dir if resource_name.lower().endswith(".mmap") else xsd_dir if resource_name.lower().endswith(".xsd") else wsdl_dir if resource_name.lower().endswith(".wsdl") else None
        if base is None:
            continue
        resource_path = base / resource_name
        resolved_resources[resource_name] = resolve_resource(str(resource_path))

    artifact = IFlowArtifact(
        artifact_id=artifact_id,
        version=version,
        nodes=nodes,
        edges=edges,
        message_flows=message_flows,
        systems=systems,
        resolved_resources=resolved_resources,
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
