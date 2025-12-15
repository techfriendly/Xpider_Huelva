"""Router de intención LLM para decidir flujo (RAG, Cypher o PPT).

Extensión:
- Detecta si la pregunta está centrada en "EMPRESA" o "CONTRATO".
- Extrae un posible NIF/CIF (empresa_nif) y una cadena de búsqueda (empresa_query).
- Mantiene los campos originales para no romper la integración actual.
"""
import re
from typing import Any, Dict, List, Optional

import config
from clients import llm_client
from chat_utils.json_utils import safe_json_loads


# CIF típico (empresa): letra + 8 dígitos. Ej: B80519267
_CIF_RE = re.compile(r"\b([A-Z]\d{8})\b", re.IGNORECASE)


def _normalize_extracto_types(tipos: Any) -> Optional[List[str]]:
    if not isinstance(tipos, list):
        return None
    tipos_filtrados = [t for t in tipos if t in config.KNOWN_EXTRACTO_TYPES]
    return tipos_filtrados or None


def _norm_str(val: Any, max_len: int = 180) -> Optional[str]:
    if not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    if len(s) > max_len:
        s = s[:max_len].strip()
    return s or None


def _normalize_focus(val: Any) -> str:
    s = (str(val or "")).strip().upper()
    if s in ("EMPRESA", "COMPANY", "ADJUDICATARIA", "PROVEEDOR", "PROVEEDORA"):
        return "EMPRESA"
    if s in ("CONTRATO", "CONTRACT"):
        return "CONTRATO"
    return "CONTRATO"


def _normalize_cif(val: Any) -> Optional[str]:
    s = _norm_str(val, max_len=32)
    if not s:
        return None
    s = s.upper()
    m = _CIF_RE.search(s)
    if m:
        return m.group(1).upper()
    return None


def _extract_cif_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    m = _CIF_RE.search(text.upper())
    return m.group(1).upper() if m else None


def detect_intent(question: str) -> Dict[str, Any]:
    prompt = f"""
Fecha actual: {config.TODAY_STR}

Eres un enrutador de intención para un asistente de contratación pública con Neo4j GraphRAG.
Devuelve SOLO JSON válido con este esquema:

{{
  "intent": "RAG_QA" | "CYPHER_QA" | "GENERATE_PPT",
  "doc_tipo": null | "PPT" | "PCAP",
  "extracto_tipos": null | ["normativas","solvencia_tecnica"],
  "needs_aggregation": true | false,

  "focus": "CONTRATO" | "EMPRESA",
  "empresa_query": null | "texto de búsqueda (nombre de empresa, razón social, etc.)",
  "empresa_nif": null | "CIF/NIF de empresa (ej: B80519267)"
}}

Reglas:
- Si pide contar/sumar/ranking/top/veces/estadísticas => intent="CYPHER_QA" y needs_aggregation=true.
- Si pide redactar/generar/elaborar un PPT => intent="GENERATE_PPT".
- En otro caso => intent="RAG_QA".
- Si menciona normativa/solvencia/garantías/criterios/ubicaciones/presupuesto/duración => extracto_tipos relevante.
- Si menciona explícitamente PPT o PCAP => doc_tipo.
- Si la pregunta es sobre una empresa/adjudicataria (p.ej. "SANITRADE", "B80519267", "adjudicaciones de X", "empresa X") => focus="EMPRESA"
  y rellena empresa_query (y empresa_nif si aparece).

Tipos extracto conocidos:
{config.KNOWN_EXTRACTO_TYPES}

Pregunta:
\"\"\"{question}\"\"\"
"""
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": "Devuelve SOLO JSON válido."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=320,
    )

    data = safe_json_loads(resp.choices[0].message.content or "") or {}
    if not isinstance(data, dict):
        data = {}

    intent = data.get("intent", "RAG_QA")
    if intent not in ("RAG_QA", "CYPHER_QA", "GENERATE_PPT"):
        intent = "RAG_QA"

    doc_tipo = data.get("doc_tipo")
    if doc_tipo not in (None, "PPT", "PCAP"):
        doc_tipo = None

    tipos = _normalize_extracto_types(data.get("extracto_tipos"))
    needs_aggregation = bool(data.get("needs_aggregation", intent == "CYPHER_QA"))

    focus = _normalize_focus(data.get("focus"))

    empresa_query = _norm_str(data.get("empresa_query"))
    empresa_nif = _normalize_cif(data.get("empresa_nif")) or _extract_cif_from_text(question)

    # Si el router marca focus=EMPRESA pero no devuelve query, usamos el NIF si existe
    if focus == "EMPRESA" and not empresa_query and empresa_nif:
        empresa_query = empresa_nif

    return {
        "intent": intent,
        "doc_tipo": doc_tipo,
        "extracto_tipos": tipos,
        "needs_aggregation": needs_aggregation,
        "focus": focus,  # NUEVO
        "empresa_query": empresa_query,  # NUEVO
        "empresa_nif": empresa_nif,  # NUEVO
    }
