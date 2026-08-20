from __future__ import annotations

import json
import sys
from pathlib import Path

from lxml import etree


def _element_text(element: etree._Element, name: str) -> str:
    """Return a direct child's text, normalized to an empty string when absent."""
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def parse_propdef(propdef_path: str) -> dict[str, dict]:
    """Parse CPI parameter definitions and their adapter attribute references."""
    tree = etree.parse(propdef_path)
    parameters: dict[str, dict] = {}

    for parameter in tree.getroot().iterfind("parameter"):
        name = _element_text(parameter, "name")
        if not name:
            continue
        parameters[name] = {
            "name": name,
            "type": _element_text(parameter, "type"),
            "is_required": _element_text(parameter, "isRequired"),
            "attribute_category": "",
            "attribute_label": name,
        }

    for reference in tree.getroot().iterfind(".//param_references/reference"):
        parameter = parameters.get(reference.get("param_key", ""))
        if parameter is None:
            continue
        parameter["attribute_category"] = reference.get("attribute_category", "")
        parameter["attribute_label"] = reference.get("attribute_uilabel", "") or parameter["name"]

    return parameters


def _first_unescaped_equals(line: str) -> int:
    escaped = False
    for index, character in enumerate(line):
        if character == "=" and not escaped:
            return index
        if character == "\\":
            escaped = not escaped
        else:
            escaped = False
    return -1


def parse_prop_file(prop_path: str) -> dict[str, str]:
    """Parse the subset of Java properties syntax used by CPI parameter files."""
    properties: dict[str, str] = {}
    with Path(prop_path).open(encoding="utf-8") as prop_file:
        for raw_line in prop_file:
            line = raw_line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            delimiter = _first_unescaped_equals(line)
            if delimiter == -1:
                continue
            key = line[:delimiter].replace("\\:", ":").replace("\\=", "=")
            value = line[delimiter + 1 :].replace("\\:", ":").replace("\\=", "=")
            properties[key] = value
    return properties


def resolve_parameters(package_path: str) -> dict:
    """Resolve externalized parameter definitions and values for a package."""
    result = {"parameters": [], "parse_warnings": []}
    package = Path(package_path)
    resources = package / "src" / "main" / "resources"
    prop_path = resources / "parameters.prop"
    propdef_path = resources / "parameters.propdef"

    missing = [str(path) for path in (propdef_path, prop_path) if not path.is_file()]
    if missing:
        result["parse_warnings"].append("Missing parameter file(s): " + ", ".join(missing))
        return result

    try:
        definitions = parse_propdef(str(propdef_path))
        configured_values = parse_prop_file(str(prop_path))
    except (OSError, ValueError, etree.XMLSyntaxError) as exc:
        result["parse_warnings"].append(f"Unable to parse parameter files: {exc}")
        return result

    result["parameters"] = [
        {**parameter, "configured_value": configured_values.get(name, "")}
        for name, parameter in definitions.items()
    ]
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m src.parser.parameters_resolver <package_folder>")

    print(json.dumps(resolve_parameters(sys.argv[1]), indent=2))
