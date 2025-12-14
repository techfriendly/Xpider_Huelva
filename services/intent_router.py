"""Router de intención LLM para decidir flujo (RAG, Cypher o PPT)."""
from typing import Any, Dict, List, Optional

import config
from clients import llm_client
from utils.json_utils import safe_json_loads


def _normalize_extracto_types(tipos: Any) -> Optional[List[str]]:
    if not isinstance(tipos, list):
        return None
    tipos_filtrados = [t for t in tipos if t in config.KNOWN_EXTRACTO_TYPES]
    return tipos_filtrados or None


def detect_intent(question: str) -> Dict[str, Any]:
    prompt = f"""
Fecha actual: {config.TODAY_STR}

Eres un enrutador de intención para un asistente de contratación pública con Neo4j GraphRAG.
Devuelve SOLO JSON válido:

{{
  "intent": "RAG_QA" | "CYPHER_QA" | "GENERATE_PPT",
  "doc_tipo": null | "PPT" | "PCAP",
  "extracto_tipos": null | ["normativas","solvencia_tecnica"],
  "needs_aggregation": true | false
}}

Reglas:
- Si pide contar/sumar/ranking/top/veces/estadísticas => CYPHER_QA.
- Si pide redactar/generar/elaborar un PPT => GENERATE_PPT.
- En otro caso => RAG_QA.
- Si menciona normativa/solvencia/garantías/criterios/ubicaciones/presupuesto/duración => extracto_tipos relevante.
- Si menciona explícitamente PPT o PCAP => doc_tipo.

Tipos extracto conocidos:
{config.KNOWN_EXTRACTO_TYPES}

Pregunta:
\"\"\"{question}\"\"\"
"""
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Devuelve SOLO JSON válido."}, {"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=220,
    )
    data = safe_json_loads(resp.choices[0].message.content or "") or {}

    intent = data.get("intent", "RAG_QA")
    if intent not in ("RAG_QA", "CYPHER_QA", "GENERATE_PPT"):
        intent = "RAG_QA"

    doc_tipo = data.get("doc_tipo")
    if doc_tipo not in (None, "PPT", "PCAP"):
        doc_tipo = None

    tipos = _normalize_extracto_types(data.get("extracto_tipos"))
    needs_aggregation = bool(data.get("needs_aggregation", intent == "CYPHER_QA"))

    return {
        "intent": intent,
        "doc_tipo": doc_tipo,
        "extracto_tipos": tipos,
        "needs_aggregation": needs_aggregation,
    }
