
from services.neo4j_queries import neo4j_query

cypher = "MATCH (c:ContratoRAG) RETURN keys(c) AS properties LIMIT 1"
print(neo4j_query(cypher))
