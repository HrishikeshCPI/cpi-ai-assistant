from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from lxml import etree


def resolve_mapping(mmap_path: str) -> dict:
    result: dict[str, Any] = {
        "field_mappings": [],
        "parse_warnings": [],
    }

    path = Path(mmap_path)
    if not path.exists():
        result["parse_warnings"].append(f"Mapping file not found: {mmap_path}")
        return result

    try:
        tree = etree.parse(str(path))
    except (etree.XMLSyntaxError, OSError, ValueError) as exc:
        result["parse_warnings"].append(f"Malformed or unreadable mapping file: {mmap_path} ({exc})")
        return result

    root = tree.getroot()
    if root is None:
        result["parse_warnings"].append(f"Empty mapping document: {mmap_path}")
        return result

    transformation = None
    for element in root.iter():
        if etree.QName(element).localname == "transformation":
            transformation = element
            break

    if transformation is None:
        result["parse_warnings"].append(
            "Transformation block not found in the mmap XML; expected a top-level transformation element with Dst/Src brick mappings."
        )
        return result

    for child in transformation:
        if etree.QName(child).localname != "brick":
            continue
        if child.get("type") != "Dst":
            continue

        target = child.get("path")
        if not target:
            continue

        arg = None
        for subchild in child:
            if etree.QName(subchild).localname == "arg":
                arg = subchild
                break

        if arg is None:
            result["field_mappings"].append({"source": None, "target": target, "function": "complex"})
            result["parse_warnings"].append(f"target {target} uses a non-trivial mapping function, not a direct field copy")
            continue

        src_bricks = [
            item for item in arg if etree.QName(item).localname == "brick" and item.get("type") == "Src"
        ]
        if len(src_bricks) == 1:
            result["field_mappings"].append(
                {
                    "source": src_bricks[0].get("path"),
                    "target": target,
                    "function": None,
                }
            )
        else:
            result["field_mappings"].append({"source": None, "target": target, "function": "complex"})
            result["parse_warnings"].append(f"target {target} uses a non-trivial mapping function, not a direct field copy")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m src.parser.mapping_resolver <mapping_file>")

    result = resolve_mapping(sys.argv[1])
    print(json.dumps(result, indent=2))
