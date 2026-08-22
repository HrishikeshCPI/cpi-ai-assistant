from __future__ import annotations

import base64
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree


def _local(element: etree._Element) -> str:
    return etree.QName(element).localname


def _raw_structure(element: etree._Element) -> dict[str, Any]:
    return {"element": _local(element), "attributes": dict(element.attrib), "text": (element.text or "").strip() or None, "children": [_raw_structure(child) for child in element]}


def _unwrap_source_code(blob_text: str) -> str:
    content = base64.b64decode(blob_text.removeprefix("!zip!"))
    for _ in range(2):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.namelist() != ["value"]:
                raise ValueError(f"expected nested zip entry 'value', found {archive.namelist()}")
            content = archive.read("value")
    return content.decode("utf-8", errors="replace")


def _blob_mappings(source: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    source_pattern = re.compile(r"//Src\[(?P<source>[^\]]+)\].{0,2000}?AStructureNode\.createNode\([^\n]*?[\"'](?P<target>[^\"']+)[\"']", re.DOTALL)
    for match in source_pattern.finditer(source):
        results.append({"source": match.group("source"), "target": match.group("target"), "function": None})
    constant_pattern = re.compile(r"new\s+com\.sap\.aii\.mappingtool\.flib7\.Constant\(this\).*?\.setParameter\(\s*[\"']value[\"']\s*,\s*[\"'](?P<value>[^\"']*)[\"']\s*\).*?AStructureNode\.createNode\([^\n]*?[\"'](?P<target>[^\"']+)[\"']", re.DOTALL)
    for match in constant_pattern.finditer(source):
        results.append({"source": None, "target": match.group("target"), "function": "constant", "value": {"value": match.group("value"), "is_externalized": False}, "is_static": True})
    return results


def _metadata(root: etree._Element, result: dict[str, Any]) -> None:
    schemas: dict[str, dict[str, str]] = {}
    for role in root.iter():
        if _local(role) != "lnkRole":
            continue
        values = [((element.text or "").strip()) for element in role.iter() if _local(element) == "elem"]
        if role.get("role") and values:
            schemas[role.get("role", "")] = {"schema": values[0], "root_element": values[2] if len(values) > 2 else ""}
    if schemas:
        result["schemas"] = schemas
    multiplicity = next((e.text.strip() for e in root.iter() if _local(e) == "Multiplicity" and e.text), None)
    if multiplicity is not None:
        result["multiplicity"] = multiplicity
    for element_name, result_name in (("SourceParameters", "source_parameters"), ("TargetParameters", "target_parameters")):
        element = next((e for e in root.iter() if _local(e) == element_name), None)
        if element is not None:
            result[result_name] = [{"name": p.get("name", ""), "occurrence": p.get("occurrence", "")} for p in element.iter() if _local(p) == "Parameter"]


def resolve_mapping(mmap_path: str) -> dict:
    result: dict[str, Any] = {"field_mappings": [], "parse_warnings": []}
    path = Path(mmap_path)
    if not path.exists():
        result["parse_warnings"].append(f"Mapping file not found: {mmap_path}")
        return result
    try:
        root = etree.parse(str(path)).getroot()
    except (etree.XMLSyntaxError, OSError, ValueError) as exc:
        result["parse_warnings"].append(f"Malformed or unreadable mapping file: {mmap_path} ({exc})")
        return result
    if root is None:
        result["parse_warnings"].append(f"Empty mapping document: {mmap_path}")
        return result
    _metadata(root, result)
    source_structure = next((e for e in root.iter() if _local(e) == "SourceStructure"), None)
    target_structure = next((e for e in root.iter() if _local(e) == "TargetStructure"), None)
    source_code = next((e for e in root.iter() if _local(e) == "SourceCode"), None)
    blob = next((e for e in source_code.iter() if _local(e) == "blob"), None) if source_code is not None else None
    if source_structure is not None and target_structure is not None and len(source_structure) == len(target_structure) == 0 and blob is not None and (blob.text or "").strip():
        try:
            result["format"] = "java_operation_mapping"
            result["field_mappings"] = _blob_mappings(_unwrap_source_code((blob.text or "").strip()))
        except (ValueError, OSError, zipfile.BadZipFile, base64.binascii.Error) as exc:
            result["parse_warnings"].append(f"Could not decode Java operation mapping source: {exc}")
        return result
    transformation = next((element for element in root.iter() if _local(element) == "transformation"), None)
    if transformation is None:
        result["parse_warnings"].append("Transformation block not found and no supported Java Operation Mapping blob was detected.")
        return result
    result["format"] = "xitrafo"
    for child in transformation:
        if _local(child) != "brick" or child.get("type") != "Dst" or not child.get("path"):
            continue
        target = child.get("path")
        arg = next((subchild for subchild in child if _local(subchild) == "arg"), None)
        src_bricks = [item for item in arg if _local(item) == "brick" and item.get("type") == "Src"] if arg is not None else []
        if len(src_bricks) == 1 and len(arg) == 1:
            result["field_mappings"].append({"source": src_bricks[0].get("path"), "target": target, "function": None})
        else:
            mapping: dict[str, Any] = {"source": None, "target": target, "function": "complex"}
            if arg is not None:
                mapping["raw_structure"] = _raw_structure(arg)
            result["field_mappings"].append(mapping)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m src.parser.mapping_resolver <mapping_file>")
    print(json.dumps(resolve_mapping(sys.argv[1]), indent=2))
