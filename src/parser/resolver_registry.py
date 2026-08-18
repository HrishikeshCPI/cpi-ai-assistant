from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.parser.groovy_summarizer import resolve_groovy
from src.parser.mapping_resolver import resolve_mapping
from src.parser.wsdl_resolver import resolve_wsdl

RESOLVERS: dict[str, Callable[[str], dict[str, Any]]] = {
    ".wsdl": resolve_wsdl,
    ".mmap": resolve_mapping,
    ".groovy": resolve_groovy,
}


def resolve_resource(filepath: str) -> dict[str, Any]:
    path = Path(filepath)
    suffix = path.suffix.lower()

    resolver = RESOLVERS.get(suffix)
    if resolver is None:
        return {
            "resolved": False,
            "note": "no resolver registered for this file type",
            "filename": path.name,
        }

    result = resolver(str(path))
    result.setdefault("resolved", True)
    return result
