
from services.neo4j_queries import neo4j_query
import json

cypher = """
MATCH (emp:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)
RETURN c.titulo, c.expediente, r.importe_adjudicado
ORDER BY r.importe_adjudicado DESC LIMIT 10
"""
rows = neo4j_query(cypher)
print(json.dumps(rows, indent=2, ensure_ascii=False))
