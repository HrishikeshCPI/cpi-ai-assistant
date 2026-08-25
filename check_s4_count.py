from src.graph.neo4j_client import run_query

print("Systems named exactly 'S4':")
print(run_query("MATCH (s:System {name: 'S4'}) RETURN s.name"))

print("\nDistinct IFlows connected to System 'S4' via CALLS:")
result = run_query("""
MATCH (i:IFlow)<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(:Step)-[:CALLS]->(s:System {name: 'S4'})
RETURN DISTINCT i.id AS artifact_id
ORDER BY i.id
""")
print(result)
print(f"\nCount: {len(result)}")

print("\nAny systems with names containing 'S4' (case-insensitive) that might be separate nodes:")
print(run_query("MATCH (s:System) WHERE toLower(s.name) CONTAINS 's4' RETURN s.name"))