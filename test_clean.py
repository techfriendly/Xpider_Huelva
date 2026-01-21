
from services.neo4j_queries import neo4j_query
from services.cypher import clean_keys
import json

cypher = """
MATCH (emp:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)
RETURN c.titulo, c.expediente, r.importe_adjudicado
ORDER BY r.importe_adjudicado DESC LIMIT 5
"""

rows = neo4j_query(cypher)
print("=== ANTES de clean_keys ===")
print(json.dumps(rows, indent=2, ensure_ascii=False)[:1000])

cleaned = clean_keys(rows)
print("\n=== DESPUÉS de clean_keys ===")
print(json.dumps(cleaned, indent=2, ensure_ascii=False)[:1000])
