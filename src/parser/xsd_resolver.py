from __future__ import annotations

from pathlib import Path

from lxml import etree

XSD_NS = "http://www.w3.org/2001/XMLSchema"


def resolve_xsd(xsd_path: str) -> dict:
    result: dict = {"elements": [], "parse_warnings": []}
    path = Path(xsd_path)
    if not path.exists():
        result["parse_warnings"].append(f"XSD file not found: {xsd_path}")
        return result
    try:
        tree = etree.parse(str(path))
    except (etree.XMLSyntaxError, OSError, ValueError) as exc:
        result["parse_warnings"].append(f"Malformed or unreadable XSD file: {xsd_path} ({exc})")
        return result
    result["elements"] = [
        {"name": element.get("name", ""), "type": element.get("type", "")}
        for element in tree.xpath(".//xsd:element", namespaces={"xsd": XSD_NS})
    ]
    return result
