from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _cache_dir() -> Path:
    cache_dir = Path("output/.groovy_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def resolve_groovy(groovy_path: str) -> dict[str, Any]:
    path = Path(groovy_path)
    _cache_dir()

    if not path.exists():
        return {"resolved": False, "note": "Groovy file not found", "filename": path.name}

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_bytes().decode("utf-8", errors="replace")

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    cache_path = _cache_dir() / f"{content_hash}.json"
    expected_cache_path = str(Path("output/.groovy_cache") / f"{content_hash}.json")

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                cached["resolved"] = True
                cached["source"] = "cache"
                return cached
        except json.JSONDecodeError:
            pass

    return {
        "resolved": False,
        "note": "no cached summary found - generate one manually and save to output/.groovy_cache/<hash>.json",
        "filename": path.name,
        "expected_cache_path": expected_cache_path,
        "hash": content_hash,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m src.parser.groovy_summarizer <groovy_file>")

    result = resolve_groovy(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result.get("resolved"):
        if "hash" in result:
            print(f"Hash: {result['hash']}")
        if "expected_cache_path" in result:
            print(f"Expected cache path: {result['expected_cache_path']}")
