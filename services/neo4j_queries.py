"""
CONSULTAS NEO4J: neo4j_queries.py
DESCRIPCIÓN:
Este archivo contiene las "recetas" (queries Cypher) predefinidas para buscar en el Grafo.
Aquí NO usamos IA para generar el código SQL/Cypher, sino que ya lo tenemos optimizado manualmente.

Funciones principales:
- Búsqueda Vectorial (se busca por significado semántico).
- Búsqueda de Empresas (por nombre o NIF).
- Estadísticas de Adjudicaciones.
"""

import re
from typing import Any, Dict, List, Optional
import config
from clients import driver

# Expresión regular para detectar CIFs (Letra + 8 números)
_CIF_RE = re.compile(r"\b([A-Z]\d{8})\b", re.IGNORECASE)

# --- FUNCIÓN BASE DE EJECUCIÓN ---
def neo4j_query(cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Ejecuta una sentencia Cypher y devuelve la lista de resultados como diccionarios."""
    if params is None:
        params = {}
    
    # LOGGING TO CHAINLIT UI
    try:
        import chainlit as cl
        # Solo logueamos si hay un contexto activo de Chainlit
        if cl.context.emitter:
            async def log_cypher():
                async with cl.Step(name="Cypher", type="tool") as step:
                    step.input = cypher + f"\n\nParams: {params}"
                    # No esperamos output aquí, solo mostramos que se ejecutó
            
            cl.run_sync(log_cypher())
    except Exception:
        # Silencioso si falla el log (ej: fuera de contexto HTTP)
        pass

    with driver.session(database=config.NEO4J_DB) as session:
        res = session.run(cypher, **params)
        return [r.data() for r in res]

# --- UTILIDADES ---
def _clean_q(q: str) -> str:
    """Limpia la consulta de espacios extra y puntuación."""
    q = (q or "").strip()
    q = q.strip(" ?¿!.,;:")
    q = re.sub(r"\s{2,}", " ", q)
    return q

def _looks_like_cif(q: str) -> bool:
    """True si el texto parece un CIF válido."""
    if not q:
        return False
    return bool(_CIF_RE.search(q.strip().upper()))


# -----------------------------
# BÚSQUEDA VECTORIAL (RAG)
# Buscamos nodos que se parezcan semánticamente a la pregunta.
# -----------------------------

def search_contratos(embedding: List[float], k: int = config.K_CONTRATOS) -> List[Dict[str, Any]]:
    """
    Busca contratos relevantes usando el vector de la pregunta.
    Combina coincidencias directas en el contrato, en sus capítulos o en sus extractos.
    """
    if not embedding:
        return []
        
    cypher = """
    // 1. Buscamos en 3 índices diferentes a la vez (Contratos, Capítulos, Extractos)
    CALL {
      // A) Vector search directa sobre nodos Contrato
      CALL db.index.vector.queryNodes('contrato_rag_embedding', $k, $embedding)
      YIELD node, score
      RETURN coalesce(node.contract_id, node.expediente, '') AS contract_id, score

      UNION

      // B) Contratos cuyo Pliego (PPT) tiene capítulos relevantes
      CALL db.index.vector.queryNodes('capitulo_embedding', $k_capitulos, $embedding)
      YIELD node, score
      MATCH (c:ContratoRAG)-[:TIENE_DOC]->(:DocumentoRAG)-[:TIENE_CAPITULO]->(node)
      RETURN coalesce(c.contract_id, c.expediente, '') AS contract_id, score

      UNION

      // C) Contratos con extractos (resúmenes) relevantes de Normativa
      CALL db.index.vector.queryNodes('extracto_embedding', $k_extractos, $embedding)
      YIELD node, score
      MATCH (c:ContratoRAG)-[:TIENE_DOC]->(:DocumentoRAG)-[:TIENE_EXTRACTO]->(node)
      WHERE node.tipo = "normativa"
      RETURN coalesce(c.contract_id, c.expediente, '') AS contract_id, score
    }
    // 2. Agregamos y nos quedamos con la mejor puntuación por contrato
    WITH contract_id, max(score) AS score
    WHERE contract_id <> ''

    // 3. Recuperamos los datos completos del Contrato y su Adjudicataria
    MATCH (c:ContratoRAG)
    WHERE c.contract_id = contract_id OR c.expediente = contract_id
    OPTIONAL MATCH (e:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(c)
    RETURN
      coalesce(c.contract_id, c.expediente, '') AS contract_id,
      coalesce(c.expediente,'')                AS expediente,
      coalesce(c.titulo,'')                    AS titulo,
      coalesce(c.abstract,'')                  AS abstract,
      coalesce(c.estado,'')                    AS estado,
      coalesce(c.cpv_principal,'')             AS cpv_principal,
      coalesce(c.contract_uri,'')              AS link_contrato,
      e.nif                                    AS adjudicataria_nif,
      e.nombre                                 AS adjudicataria_nombre,
      c.presupuesto_sin_iva                    AS presupuesto_sin_iva,
      c.valor_estimado                         AS valor_estimado,
      coalesce(r.importe_adjudicado, 0)        AS importe_adjudicado,
      score
    ORDER BY score DESC
    LIMIT $k
    """
    params = {
        "k": k,
        "k_capitulos": min(k * 2, config.K_CAPITULOS),
        "k_extractos": min(k * 2, config.K_EXTRACTOS),
        "embedding": embedding,
    }
    return neo4j_query(cypher, params)


def search_contract_by_id(contract_id: str) -> List[Dict[str, Any]]:
    """Busca contratos por ID o Expediente exacto / parcial."""
    q = _clean_q(contract_id)
    if not q:
        return []

    cypher = """
    MATCH (c:ContratoRAG)
    WHERE c.contract_id = $q OR c.expediente = $q
       OR c.contract_id CONTAINS $q OR c.expediente CONTAINS $q
    
    OPTIONAL MATCH (e:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(c)
    
    RETURN
      coalesce(c.contract_id, c.expediente, '') AS contract_id,
      coalesce(c.expediente,'')                AS expediente,
      coalesce(c.titulo,'')                    AS titulo,
      coalesce(c.abstract,'')                  AS abstract,
      coalesce(c.estado,'')                    AS estado,
      coalesce(c.cpv_principal,'')             AS cpv_principal,
      coalesce(c.contract_uri,'')              AS link_contrato,
      e.nif                                    AS adjudicataria_nif,
      e.nombre                                 AS adjudicataria_nombre,
      c.presupuesto_sin_iva                    AS presupuesto_sin_iva,
      c.valor_estimado                         AS valor_estimado,
      coalesce(r.importe_adjudicado, 0)        AS importe_adjudicado,
      1.0 as score
    LIMIT 5
    """
    return neo4j_query(cypher, {"q": q})


def search_contracts_by_nif(nif: str) -> List[Dict[str, Any]]:
    """Busca todos los contratos adjudicados a un NIF específico."""
    q = _clean_q(nif).upper()
    if not q:
        return []

    cypher = """
    MATCH (e:EmpresaRAG)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)
    WHERE e.nif = $q
    
    RETURN
      coalesce(c.contract_id, c.expediente, '') AS contract_id,
      coalesce(c.expediente,'')                AS expediente,
      coalesce(c.titulo,'')                    AS titulo,
      coalesce(c.abstract,'')                  AS abstract,
      coalesce(c.estado,'')                    AS estado,
      coalesce(c.cpv_principal,'')             AS cpv_principal,
      coalesce(c.contract_uri,'')              AS link_contrato,
      e.nif                                    AS adjudicataria_nif,
      e.nombre                                 AS adjudicataria_nombre,
      c.presupuesto_sin_iva                    AS presupuesto_sin_iva,
      c.valor_estimado                         AS valor_estimado,
      coalesce(r.importe_adjudicado, 0)        AS importe_adjudicado,
      1.0 as score
    ORDER BY importe_adjudicado DESC
    LIMIT 20
    """
    return neo4j_query(cypher, {"q": q})


def search_capitulos(
    embedding: List[float],
    k: int = config.K_CAPITULOS,
    doc_tipo: Optional[str] = None,
    expedientes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Busca capítulos específicos dentro de los documentos (PPT, PCAP)."""
    if not embedding:
        return []

    # Si filtramos por expediente, traemos más candidatos iniciales para no quedarnos cortos al filtrar
    k_query = k if not expedientes else max(k * 25, 200)

    cypher = """
    CALL db.index.vector.queryNodes('capitulo_embedding', $k_query, $embedding)
    YIELD node, score
    MATCH (c:ContratoRAG)-[td:TIENE_DOC]->(d:DocumentoRAG)-[:TIENE_CAPITULO]->(node)
    
    // Filtros opcionales (Tipo de doc y Expediente específico)
    WHERE ($doc_tipo IS NULL OR td.tipo_doc = $doc_tipo)
      AND ($expedientes IS NULL OR c.expediente IN $expedientes)
      
    RETURN
      node.cap_id                   AS cap_id,
      coalesce(node.heading,'')     AS heading,
      coalesce(node.texto,'')       AS texto,
      coalesce(node.fuente_doc,'')  AS fuente_doc,
      coalesce(c.contract_id, c.expediente, '') AS contract_id,
      coalesce(c.expediente,'')     AS expediente,
      coalesce(c.titulo,'')         AS contrato_titulo,
      score
    ORDER BY score DESC
    LIMIT $k
    """
    return neo4j_query(
        cypher,
        {"k_query": k_query, "k": k, "embedding": embedding, "doc_tipo": doc_tipo, "expedientes": expedientes},
    )


def search_extractos(
    embedding: List[float],
    k: int = config.K_EXTRACTOS,
    tipos: Optional[List[str]] = None,
    doc_tipo: Optional[str] = None,
    expedientes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Busca fragmentos específicos clasificados (ej: Solvencia técnica, Criterios de adjudicación)."""
    if not embedding:
        return []

    k_query = k if not expedientes else max(k * 25, 200)

    cypher = """
    CALL db.index.vector.queryNodes('extracto_embedding', $k_query, $embedding)
    YIELD node, score
    WITH node, score
    // Filtro por tipo de extracto (ej: 'solvencia')
    WHERE ($tipos IS NULL OR size($tipos)=0 OR node.tipo IN $tipos)
    
    MATCH (c:ContratoRAG)-[td:TIENE_DOC]->(d:DocumentoRAG)-[:TIENE_EXTRACTO]->(node)
    WHERE ($doc_tipo IS NULL OR td.tipo_doc = $doc_tipo)
      AND ($expedientes IS NULL OR c.expediente IN $expedientes)
      
    RETURN
      node.extracto_id               AS extracto_id,
      coalesce(node.tipo,'')         AS tipo,
      coalesce(node.texto,'')        AS texto,
      coalesce(node.fuente_doc,'')   AS fuente_doc,
      coalesce(c.contract_id, c.expediente, '') AS contract_id,
      coalesce(c.expediente,'')      AS expediente,
      coalesce(c.titulo,'')          AS contrato_titulo,
      score
    ORDER BY score DESC
    LIMIT $k
    """
    return neo4j_query(
        cypher,
        {
            "k_query": k_query,
            "k": k,
            "embedding": embedding,
            "tipos": tipos or [],
            "doc_tipo": doc_tipo,
            "expedientes": expedientes,
        },
    )


def search_extractos_by_expediente(expediente: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Busca extractos asociados a un contrato por su expediente."""
    if not expediente:
        return []
    
    cypher = """
    MATCH (c:ContratoRAG)-[:TIENE_DOC]->(d:DocumentoRAG)-[:TIENE_EXTRACTO]->(e:ExtractoRAG)
    WHERE c.expediente = $expediente OR c.contract_id = $expediente
    RETURN
      coalesce(e.tipo, 'general') AS tipo,
      coalesce(e.texto, '') AS texto,
      coalesce(e.fuente_doc, '') AS fuente_doc
    ORDER BY e.tipo
    LIMIT $limit
    """
    return neo4j_query(cypher, {"expediente": expediente, "limit": limit})


def search_relevant_extracts_rag(embedding: List[float], k: int = 10) -> List[Dict[str, Any]]:
    """
    Busca extractos específicos (normativa, solvencia, requerimientos) similares al embedding.
    Devuelve el extracto Y el contrato asociado.
    Útil para preguntas como 'contratos con requisitos ambientales'.
    """
    cypher = """
    CALL db.index.vector.queryNodes('extracto_embedding', $k, $embedding)
    YIELD node, score
    MATCH (c:ContratoRAG)-[:TIENE_DOC]->(:DocumentoRAG)-[:TIENE_EXTRACTO]->(node)
    
    // Recuperar info básica del contrato
    OPTIONAL MATCH (e:EmpresaRAG)-[:ADJUDICATARIA_RAG]->(c)
    
    RETURN
        coalesce(c.contract_id, c.expediente, '') AS contract_id,
        coalesce(c.expediente, '') AS expediente,
        coalesce(c.titulo, '') AS titulo,
        coalesce(e.nombre, 'Desconocido') AS adjudicataria,
        node.tipo AS extracto_tipo,
        node.texto AS extracto_texto,
        score
    ORDER BY score DESC
    """
    return neo4j_query(cypher, {"k": k, "embedding": embedding})


# -----------------------------
# BÚSQUEDA DE EMPRESAS (Full Text + Exact match)
# -----------------------------

def search_empresas(query: str, k_empresas: int = 5, max_adjudicaciones: int = 12) -> List[Dict[str, Any]]:
    """
    Busca empresas por nombre o NIF.
    Prioriza coincidencias exactas y luego parciales.
    Devuelve también una lista breve de sus adjudicaciones manuales.
    """
    q = _clean_q(query)
    if not q:
        return []

    q_upper = q.upper()
    q_lower = q.lower()
    has_cif = _looks_like_cif(q_upper)

    cypher = """
    MATCH (e:EmpresaRAG)
    WHERE
      toLower(e.nombre) CONTAINS toLower($q)
      OR ($has_cif = true AND e.nif = $q_upper)

    // Calculamos un ranking de relevancia manual
    WITH e,
      CASE
        WHEN $has_cif = true AND e.nif = $q_upper THEN 0
        WHEN toLower(e.nombre) = toLower($q) THEN 1
        WHEN toLower(e.nombre) STARTS WITH toLower($q) THEN 2
        ELSE 3
      END AS match_rank
    ORDER BY match_rank ASC, size(coalesce(e.nombre,'')) ASC
    LIMIT $k_empresas

    // Traemos adjudicaciones para enriquecer el resultado
    OPTIONAL MATCH (e)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)
    WITH e, match_rank, r, c,
         coalesce(r.importe_adjudicado, 0) AS importe
    ORDER BY match_rank ASC, importe DESC

    // Agregamos todo en una lista dentro del objeto empresa
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
            "has_cif": has_cif,
            "k_empresas": k_empresas,
            "max_adj": max_adjudicaciones,
        },
    )


def search_contratos_by_empresa(query: str, k_empresas: int = 3, k_contratos: int = 25) -> List[Dict[str, Any]]:
    """Devuelve la lista plana de contratos ganados por la empresa (sin agrupar en objeto empresa)."""
    q = _clean_q(query)
    if not q:
        return []

    q_upper = q.upper()
    q_lower = q.lower()
    has_cif = _looks_like_cif(q_upper)

    cypher = """
    // 1. Encontrar la empresa
    MATCH (e:EmpresaRAG)
    WHERE
      (
        e.nombre CONTAINS $q OR e.nombre CONTAINS $q_upper OR e.nombre CONTAINS $q_lower
        OR e.nombre STARTS WITH $q OR e.nombre STARTS WITH $q_upper OR e.nombre STARTS WITH $q_lower
        OR e.nombre = $q OR e.nombre = $q_upper OR e.nombre = $q_lower
      )
      OR ($has_cif = true AND (e.nif = $q_upper OR e.nif = $q))

    WITH e,
      CASE
        WHEN $has_cif = true AND (e.nif = $q_upper OR e.nif = $q) THEN 0
        WHEN e.nombre = $q OR e.nombre = $q_upper OR e.nombre = $q_lower THEN 1
        WHEN e.nombre STARTS WITH $q OR e.nombre STARTS WITH $q_upper OR e.nombre STARTS WITH $q_lower THEN 2
        ELSE 3
      END AS empresa_match_rank
    ORDER BY empresa_match_rank ASC, size(coalesce(e.nombre,'')) ASC
    LIMIT $k_empresas

    // 2. Buscar sus contratos
    MATCH (e)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)
    WITH e, r, c, empresa_match_rank,
         coalesce(r.importe_adjudicado, 0) AS importe_adj
    RETURN
      coalesce(c.expediente, '') AS contract_id,
      coalesce(c.expediente, '') AS expediente,
      coalesce(c.titulo,'')   AS titulo,
      coalesce(c.abstract,'') AS abstract,
      coalesce(c.estado,'')   AS estado,
      coalesce(c.cpv_principal,'') AS cpv_principal,
      coalesce(c.contract_uri,'')   AS link_contrato,   
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
            "has_cif": has_cif,
            "k_empresas": k_empresas,
            "k_contratos": k_contratos,
        },
    )


def empresa_awards_stats(query: str, k_empresas: int = 3) -> Optional[Dict[str, Any]]:
    """Calcula totales (Count y Suma Importe) para una empresa dada."""
    q = _clean_q(query)
    if not q:
        return None

    q_upper = q.upper()
    q_lower = q.lower()
    has_cif = _looks_like_cif(q_upper)

    cypher = """
    MATCH (e:EmpresaRAG)
    WHERE
      (
        e.nombre CONTAINS $q OR e.nombre CONTAINS $q_upper OR e.nombre CONTAINS $q_lower
        OR e.nombre STARTS WITH $q OR e.nombre STARTS WITH $q_upper OR e.nombre STARTS WITH $q_lower
        OR e.nombre = $q OR e.nombre = $q_upper OR e.nombre = $q_lower
      )
      OR ($has_cif = true AND (e.nif = $q_upper OR e.nif = $q))

    WITH e,
      CASE
        WHEN $has_cif = true AND (e.nif = $q_upper OR e.nif = $q) THEN 0
        WHEN e.nombre = $q OR e.nombre = $q_upper OR e.nombre = $q_lower THEN 1
        WHEN e.nombre STARTS WITH $q OR e.nombre STARTS WITH $q_upper OR e.nombre STARTS WITH $q_lower THEN 2
        ELSE 3
      END AS match_rank
    ORDER BY match_rank ASC, size(coalesce(e.nombre,'')) ASC
    LIMIT $k_empresas

    OPTIONAL MATCH (e)-[r:ADJUDICATARIA_RAG]->(c:ContratoRAG)
    WITH e, match_rank,
         count(DISTINCT c) AS contratos_ganados,
         sum(coalesce(r.importe_adjudicado, 0)) AS importe_total
    RETURN
      coalesce(e.nombre,'') AS nombre,
      coalesce(e.nif,'')    AS nif,
      match_rank,
      contratos_ganados,
      importe_total
    ORDER BY match_rank ASC, contratos_ganados DESC, importe_total DESC
    LIMIT 1
    """
    rows = neo4j_query(
        cypher,
        {
            "q": q,
            "q_upper": q_upper,
            "q_lower": q_lower,
            "has_cif": has_cif,
            "k_empresas": k_empresas,
        },
    )
    return rows[0] if rows else None
