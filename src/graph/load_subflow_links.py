from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from src.graph.neo4j_client import run_query


def load_subflow_links(json_path: str = "output/subflow_links.json") -> dict[str, int]:
    """Load resolved iFlow-to-iFlow subflow links after artifact loading.

    Both endpoints are matched before the relationship is merged, so a stale
    link file cannot create placeholder IFlow nodes.
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Subflow links JSON not found: {json_path}")

    with path.open(encoding="utf-8") as file:
        links: list[dict[str, Any]] = json.load(file)

    loaded = 0
    skipped = 0
    link_query = """
    MATCH (caller:IFlow {id: $caller})
    MATCH (callee:IFlow {id: $callee})
    MERGE (caller)-[:CALLS_SUBFLOW {address: $address}]->(callee)
    RETURN caller.id AS caller, callee.id AS callee
    """

    for link in links:
        caller = link.get("caller", "")
        callee = link.get("callee", "")
        address = link.get("address", "")
        if not caller or not callee:
            print(f"[WARNING] Skipping malformed subflow link: {link}")
            skipped += 1
            continue

        result = run_query(
            link_query,
            {"caller": caller, "callee": callee, "address": address},
        )
        if not result:
            print(
                "[WARNING] Skipped subflow link because an IFlow endpoint is missing: "
                f"{caller} -> {callee}"
            )
            skipped += 1
            continue
        loaded += 1

    return {"loaded": loaded, "skipped": skipped}


if __name__ == "__main__":
    links_path = sys.argv[1] if len(sys.argv) > 1 else "output/subflow_links.json"
    print(load_subflow_links(links_path))
