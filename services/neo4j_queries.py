"""Consultas y búsquedas sobre Neo4j (vector y texto)."""
from typing import Any, Dict, List, Optional

import config
from clients import driver


def neo4j_query(cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if params is None:
        params = {}
    with driver.session(database=config.NEO4J_DB) as session:
        res = session.run(cypher, **params)
        return [r.data() for r in res]


# -----------------------------
# Vector search (actual)
# -----------------------------
def search_contratos(embedding: List[float], k: int = config.K_CONTRATOS) -> List[Dict[str, Any]]:
    """Busca contratos relevantes por embedding (vector index)."""
    if not embedding:
        return []
    cypher = """
    CALL db.index.vector.queryNodes('contrato_rag_embedding', $k, $embedding)
    YIELD node, score
    OPTIONAL MATCH (e:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(node)
    RETURN
      coalesce(node.contract_id, node.expediente, '') AS contract_id,
      coalesce(node.expediente, node.contract_id, '') AS expediente,
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


def search_capitulos(
    embedding: List[float], k: int = config.K_CAPITULOS, doc_tipo: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Busca capítulos relevantes por embedding."""
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
      coalesce(c.contract_id, c.expediente, '') AS contract_id,
      coalesce(c.expediente, c.contract_id, '') AS expediente,
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
    """Busca extractos relevantes por embedding."""
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
      coalesce(node.extracto_id, node.expediente, '') AS extracto_id,
      coalesce(node.tipo,'')         AS tipo,
      coalesce(node.texto,'')        AS texto,
      coalesce(node.fuente_doc,'')   AS fuente_doc,
      coalesce(c.contract_id, c.expediente, '') AS contract_id,
      coalesce(c.expediente, c.contract_id, '') AS expediente,
      coalesce(c.titulo,'')          AS contrato_titulo,
      score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding, "tipos": tipos or [], "doc_tipo": doc_tipo})


# -----------------------------
# NUEVO: Búsqueda de empresas + adjudicaciones
# -----------------------------
def search_empresas(query: str, k_empresas: int = 5, max_adjudicaciones: int = 12) -> List[Dict[str, Any]]:
    """Busca empresas por nombre/NIF y trae métricas + top adjudicaciones.

    Nota sobre rendimiento:
    - Si tienes TEXT INDEX sobre (e:EmpresaRAG {nombre}), consultas con CONTAINS/STARTS WITH pueden beneficiarse.
    """
    q = (query or "").strip()
    if not q:
        return []

    q_upper = q.upper()
    q_lower = q.lower()

    cypher = """
    MATCH (e:EmpresaRAG)
    WHERE
      e.nif = $q_upper
      OR e.nif = $q
      OR e.nombre CONTAINS $q
      OR e.nombre CONTAINS $q_upper
      OR e.nombre CONTAINS $q_lower
      OR e.nombre = $q
      OR e.nombre = $q_upper
      OR e.nombre = $q_lower
      OR e.nombre STARTS WITH $q
      OR e.nombre STARTS WITH $q_upper
      OR e.nombre STARTS WITH $q_lower

    WITH e,
      CASE
        WHEN e.nif = $q_upper THEN 0
        WHEN e.nombre = $q OR e.nombre = $q_upper OR e.nombre = $q_lower THEN 1
        WHEN e.nombre STARTS WITH $q OR e.nombre STARTS WITH $q_upper OR e.nombre STARTS WITH $q_lower THEN 2
        ELSE 3
      END AS match_rank
    ORDER BY match_rank ASC, size(coalesce(e.nombre,'')) ASC
    LIMIT $k_empresas

    OPTIONAL MATCH (e)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)
    WITH e, match_rank, r, c,
         coalesce(r.importe_adjudicado, r.importe, c.importe_adjudicado, 0) AS importe
    ORDER BY match_rank ASC, importe DESC

    WITH
      e,
      match_rank,
      count(c) AS adjudicaciones_count,
      sum(importe) AS adjudicaciones_total,
      collect(
        CASE WHEN c IS NULL THEN NULL ELSE {
          contract_id: coalesce(c.contract_id, c.expediente, ''),
          expediente: coalesce(c.expediente, c.contract_id, ''),
          titulo: coalesce(c.titulo,''),
          estado: coalesce(c.estado,''),
          abstract: coalesce(c.abstract,''),
          cpv_principal: coalesce(c.cpv_principal,''),
          presupuesto_sin_iva: c.presupuesto_sin_iva,
          valor_estimado: c.valor_estimado,
          importe_adjudicado: importe
        } END
      ) AS adjud_raw

    WITH
      e,
      match_rank,
      adjudicaciones_count,
      adjudicaciones_total,
      [a IN adjud_raw WHERE a IS NOT NULL][0..$max_adj] AS adjudicaciones

    RETURN
      coalesce(e.id, id(e)) AS empresa_id,
      elementId(e)          AS empresa_element_id,
      coalesce(e.nif,'')    AS nif,
      coalesce(e.nombre,'') AS nombre,
      match_rank,
      adjudicaciones_count,
      adjudicaciones_total,
      adjudicaciones
    ORDER BY match_rank ASC, adjudicaciones_count DESC, adjudicaciones_total DESC
    """

    return neo4j_query(
        cypher,
        {
            "q": q,
            "q_upper": q_upper,
            "q_lower": q_lower,
            "k_empresas": k_empresas,
            "max_adj": max_adjudicaciones,
        },
    )


def search_contratos_by_empresa(query: str, k_empresas: int = 3, k_contratos: int = 25) -> List[Dict[str, Any]]:
    """Devuelve contratos adjudicados a una empresa (por NIF o por nombre),
    en el MISMO formato que `search_contratos` para que puedas reutilizar `build_context`.
    """
    q = (query or "").strip()
    if not q:
        return []

    q_upper = q.upper()
    q_lower = q.lower()

    cypher = """
    MATCH (e:EmpresaRAG)
    WHERE
      e.nif = $q_upper
      OR e.nif = $q
      OR e.nombre CONTAINS $q
      OR e.nombre CONTAINS $q_upper
      OR e.nombre CONTAINS $q_lower
      OR e.nombre = $q
      OR e.nombre = $q_upper
      OR e.nombre = $q_lower
      OR e.nombre STARTS WITH $q
      OR e.nombre STARTS WITH $q_upper
      OR e.nombre STARTS WITH $q_lower

    WITH e,
      CASE
        WHEN e.nif = $q_upper THEN 0
        WHEN e.nombre = $q OR e.nombre = $q_upper OR e.nombre = $q_lower THEN 1
        WHEN e.nombre STARTS WITH $q OR e.nombre STARTS WITH $q_upper OR e.nombre STARTS WITH $q_lower THEN 2
        ELSE 3
      END AS empresa_match_rank
    ORDER BY empresa_match_rank ASC, size(coalesce(e.nombre,'')) ASC
    LIMIT $k_empresas

    MATCH (e)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)
    WITH e, r, c, empresa_match_rank,
         coalesce(r.importe_adjudicado, r.importe, c.importe_adjudicado) AS importe_adj
    RETURN
      coalesce(c.contract_id, c.expediente, '') AS contract_id,
      coalesce(c.expediente, c.contract_id, '') AS expediente,
      coalesce(c.titulo,'')   AS titulo,
      coalesce(c.abstract,'') AS abstract,
      coalesce(c.estado,'')   AS estado,
      coalesce(c.cpv_principal,'') AS cpv_principal,
      e.nif    AS adjudicataria_nif,
      e.nombre AS adjudicataria_nombre,
      c.presupuesto_sin_iva AS presupuesto_sin_iva,
      c.valor_estimado      AS valor_estimado,
      importe_adj           AS importe_adjudicado,
      empresa_match_rank    AS empresa_match_rank
    ORDER BY empresa_match_rank ASC, importe_adjudicado DESC
    LIMIT $k_contratos
    """

    return neo4j_query(
        cypher,
        {
            "q": q,
            "q_upper": q_upper,
            "q_lower": q_lower,
            "k_empresas": k_empresas,
            "k_contratos": k_contratos,
        },
    )
