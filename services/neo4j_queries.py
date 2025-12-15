"""Consultas y búsquedas vectoriales sobre Neo4j."""
from typing import Any, Dict, List, Optional

import config
from clients import driver


def neo4j_query(cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if params is None:
        params = {}
    with driver.session(database=config.NEO4J_DB) as session:
        res = session.run(cypher, **params)
        return [r.data() for r in res]


def search_contratos(embedding: List[float], k: int = config.K_CONTRATOS) -> List[Dict[str, Any]]:
    if not embedding:
        return []
    cypher = """
    CALL db.index.vector.queryNodes('contrato_rag_embedding', $k, $embedding)
    YIELD node, score
    OPTIONAL MATCH (e:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(node)
    RETURN
      coalesce(node.expediente,'')     AS contract_id,
      coalesce(node.expediente,'')     AS expediente,
      coalesce(node.titulo,'')         AS titulo,
      coalesce(node.abstract,'')       AS abstract,
      coalesce(node.estado,'')         AS estado,
      coalesce(node.cpv_principal,'')  AS cpv_principal,
      e.nif                            AS adjudicataria_nif,
      e.nombre                         AS adjudicataria_nombre,
      node.presupuesto_sin_iva         AS presupuesto_sin_iva,
      node.valor_estimado              AS valor_estimado,
      coalesce(r.importe_adjudicado, r.importe, node.importe_adjudicado) AS importe_adjudicado,
      score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding})


def search_capitulos(embedding: List[float], k: int = config.K_CAPITULOS, doc_tipo: Optional[str] = None) -> List[Dict[str, Any]]:
    if not embedding:
        return []
    cypher = """
    CALL db.index.vector.queryNodes('capitulo_embedding', $k, $embedding)
    YIELD node, score
    MATCH (c:ContratoRAG)-[td:TIENE_DOC]->(d:DocumentoRAG)-[:TIENE_CAPITULO]->(node)
    WHERE ($doc_tipo IS NULL OR td.tipo_doc = $doc_tipo)
    RETURN
      node.cap_id                   AS cap_id,
      coalesce(node.heading,'')     AS heading,
      coalesce(node.texto,'')       AS texto,
      coalesce(node.fuente_doc,'')  AS fuente_doc,
      c.contract_id                 AS contract_id,
      coalesce(c.expediente,'')     AS expediente,
      coalesce(c.titulo,'')         AS contrato_titulo,
      score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding, "doc_tipo": doc_tipo})


def search_extractos(
    embedding: List[float],
    k: int = config.K_EXTRACTOS,
    tipos: Optional[List[str]] = None,
    doc_tipo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not embedding:
        return []
    cypher = """
    CALL db.index.vector.queryNodes('extracto_embedding', $k, $embedding)
    YIELD node, score
    WITH node, score
    WHERE ($tipos IS NULL OR size($tipos)=0 OR node.tipo IN $tipos)
    MATCH (c:ContratoRAG)-[td:TIENE_DOC]->(d:DocumentoRAG)-[:TIENE_EXTRACTO]->(node)
    WHERE ($doc_tipo IS NULL OR td.tipo_doc = $doc_tipo)
    RETURN
      coalesce(node.expediente,'')   AS extracto_id,
      coalesce(node.tipo,'')         AS tipo,
      coalesce(node.texto,'')        AS texto,
      coalesce(node.fuente_doc,'')   AS fuente_doc,
      coalesce(c.expediente,'')      AS contract_id,
      coalesce(c.expediente,'')      AS expediente,
      coalesce(c.titulo,'')          AS contrato_titulo,
      score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding, "tipos": tipos or [], "doc_tipo": doc_tipo})
