import json
from collections import defaultdict
from pathlib import Path

from src.graph.neo4j_client import run_query

# Step 1: ground truth from parser output - which filenames are declared
# by more than one distinct artifact?
filename_to_artifacts = defaultdict(set)

for f in Path("output").glob("*.json"):
    if f.name == "subflow_links.json":
        continue
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue
    artifact_id = data.get("artifact_id", f.stem)
    resources = data.get("resources", {})
    for category in ("scripts", "mappings", "schemas"):
        for filename in resources.get(category, []):
            filename_to_artifacts[filename].add(artifact_id)

collisions = {fn: artifacts for fn, artifacts in filename_to_artifacts.items() if len(artifacts) > 1}

print(f"Total distinct filenames across corpus: {len(filename_to_artifacts)}")
print(f"Filenames declared by MORE THAN ONE artifact (potential collision risk): {len(collisions)}\n")

for fn, artifacts in sorted(collisions.items()):
    print(f"  {fn}: declared by {len(artifacts)} artifacts -> {sorted(artifacts)}")

# Step 2: for a couple of the worst offenders, check what the GRAPH actually
# shows - one shared node, or correctly separate ones?
print("\n=== Graph reality check for a few colliding filenames ===\n")

sample = list(collisions.keys())[:5] if collisions else []
for fn in sample:
    print(f"--- {fn} ---")
    result = run_query(
        "MATCH (r:Resource {filename: $fn}) RETURN r.filename, elementId(r) AS node_id",
        {"fn": fn},
    )
    print(f"  Resource node(s) in graph: {len(result)} -> {result}")

    linked = run_query(
        """
        MATCH (i:IFlow)<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(s:Step)-[:USES]->(r:Resource {filename: $fn})
        RETURN DISTINCT i.id AS artifact_id
        ORDER BY i.id
        """,
        {"fn": fn},
    )
    print(f"  IFlows actually linked to this filename's Resource node(s) in the graph: {linked}\n")