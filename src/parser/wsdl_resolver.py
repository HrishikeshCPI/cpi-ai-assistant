from __future__ import annotations

import json
import sys
from pathlib import Path

from lxml import etree

WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
SOAP_NS = "http://schemas.xmlsoap.org/wsdl/soap/"


def resolve_wsdl(wsdl_path: str) -> dict:
    result: dict = {
        "messages": [],
        "operations": [],
        "soap_address": None,
        "target_namespace": None,
        "parse_warnings": [],
    }

    path = Path(wsdl_path)
    if not path.exists():
        result["parse_warnings"].append(f"WSDL file not found: {wsdl_path}")
        return result

    try:
        tree = etree.parse(str(path))
    except (etree.XMLSyntaxError, OSError, ValueError) as exc:
        result["parse_warnings"].append(f"Malformed or unreadable WSDL file: {wsdl_path} ({exc})")
        return result

    root = tree.getroot()
    if root is None:
        result["parse_warnings"].append(f"Empty WSDL document: {wsdl_path}")
        return result

    target_ns = root.get("targetNamespace")
    if target_ns:
        result["target_namespace"] = target_ns

    for message in root.findall("wsdl:message", namespaces={"wsdl": WSDL_NS}):
        message_name = message.get("name") or ""
        parts: list[dict[str, str | None]] = []
        for part in message.findall("wsdl:part", namespaces={"wsdl": WSDL_NS}):
            part_name = part.get("name") or ""
            part_ref = part.get("element") or part.get("type")
            parts.append({"name": part_name, "type": part_ref})
        result["messages"].append({"name": message_name, "parts": parts})

    port_type = root.find("wsdl:portType", namespaces={"wsdl": WSDL_NS})
    if port_type is not None:
        for operation in port_type.findall("wsdl:operation", namespaces={"wsdl": WSDL_NS}):
            operation_name = operation.get("name")
            if operation_name is None:
                operation_name = ""
            input_message = None
            output_message = None

            input_node = operation.find("wsdl:input", namespaces={"wsdl": WSDL_NS})
            if input_node is not None and input_node.get("message"):
                raw_input = input_node.get("message")
                input_message = raw_input.split(":", 1)[1] if raw_input.startswith("tns:") else raw_input

            output_node = operation.find("wsdl:output", namespaces={"wsdl": WSDL_NS})
            if output_node is not None and output_node.get("message"):
                raw_output = output_node.get("message")
                output_message = raw_output.split(":", 1)[1] if raw_output.startswith("tns:") else raw_output

            result["operations"].append(
                {
                    "name": operation_name,
                    "input_message": input_message,
                    "output_message": output_message,
                }
            )

    service = root.find("wsdl:service", namespaces={"wsdl": WSDL_NS})
    if service is not None:
        port = service.find("wsdl:port", namespaces={"wsdl": WSDL_NS})
        if port is not None:
            address = port.find("soap:address", namespaces={"soap": SOAP_NS})
            if address is not None:
                result["soap_address"] = address.get("location")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m src.parser.wsdl_resolver <wsdl_file>")

    result = resolve_wsdl(sys.argv[1])
    print(json.dumps(result, indent=2))
