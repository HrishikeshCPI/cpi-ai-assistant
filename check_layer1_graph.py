from src.graph.neo4j_client import run_query

result = run_query("""
MATCH (r:Resource {filename: "MM_ConvertNorthWindStructuer.mmap"})<-[:USES]-(s:Step)-[:BELONGS_TO]->(:Process)-[:PART_OF]->(i:IFlow)
RETURN i.id, s.name, r.filename
""")
print("Layer 1 - graph query result:")
print(result)