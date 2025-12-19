"""Router de intención (heurísticas + LLM) para decidir flujo (RAG, Cypher o PPT).

Extiende el router original con:
- is_greeting: saludos / smalltalk
- is_followup: elipsis tipo "y Vodafone?"
- focus: "CONTRATO" | "EMPRESA"
- empresa_query: preferimos nombre/razón social (no CIF), aunque CIF puede venir.
"""
import re
from typing import Any, Dict, List, Optional

import config
from clients import llm_client
from chat_utils.json_utils import safe_json_loads


_CIF_RE = re.compile(r"\b([A-Z]\d{8})\b", re.IGNORECASE)

_GREET_RE = re.compile(
    r"^\s*(hola|gracias|adios|buenas|buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|hey|hello|hi|qué\s+tal|que\s+tal)\s*[!.?,]*\s*$",
    re.IGNORECASE,
)

# Patrones empresa (RAG)
_RE_BUSCA_INFO = re.compile(r"\b(busca|buscas|buscar)\s+(info|informaci[oó]n)\s+(sobre|de)\s+(.+)$", re.IGNORECASE)
_RE_ADJUDICACIONES = re.compile(r"\b(adjudicaciones|contratos)\s+(de|del)\s+(.+)$", re.IGNORECASE)
_RE_QUE_HA_GANADO = re.compile(r"\b(qu[eé])\s+(contratos?)\s+ha\s+ganado\s+(.+)$", re.IGNORECASE)
_RE_HA_GANADO_CORTO = re.compile(r"\bha\s+ganado\s+(.+)$", re.IGNORECASE)

# Patrones empresa (CYPHER agregación)
_RE_CUANTOS_CONTRATOS = re.compile(r"\bcu[aá]ntos?\s+contratos?\s+ha\s+ganado\s+(.+)$", re.IGNORECASE)
_RE_IMPORTE_TOTAL = re.compile(
    r"\b(importe\s+total|total\s+adjudicado|cu[aá]nto\s+(dinero|importe))\b.*\b(ha\s+ganado|adjudicado|a)\s+(.+)$",
    re.IGNORECASE,
)

# Follow-up elíptico: "y Vodafone?"
_RE_Y_SIMPLE = re.compile(r"^\s*y\s+(.+?)\s*[?¿!]*\s*$", re.IGNORECASE)

# Follow-up anafórico: "sobre el texto anterior / ese contrato"
_RE_PREV_REF = re.compile(
    r"\b(ese|este|esa|esta|dicho|anterior|previo|último|ultimo)\s+(contrato|expediente|pliego|texto)\b"
    r"|\b(en|sobre|respecto\s+a|acerca\s+de|del|de\s+la)\s+"
    r"(ese|este|esa|esta|dicho|anterior|previo|último|ultimo)\s+(contrato|expediente|pliego|texto)\b",
    re.IGNORECASE,
)

_RE_FOLLOWUP_HINT = re.compile(r"^\s*(y|adem[aá]s|ademas|tamb[ií]en|otra\s+cosa)\b", re.IGNORECASE)
_RE_FOLLOWUP_KEYWORDS = re.compile(
    r"\b(importe|presupuesto|duraci[oó]n|plazo|fecha|cuando|qu[ií]en|c[uú]al(es)?|detalles?"
    r"|normativa|ley|lcsp|rglcap|ens|protecci[oó]n\s+de\s+datos|rgpd)\b",
    re.IGNORECASE,
)

def _normalize_extracto_types(tipos: Any) -> Optional[List[str]]:
    if not isinstance(tipos, list):
        return None
    tipos_filtrados = [t for t in tipos if t in config.KNOWN_EXTRACTO_TYPES]
    return tipos_filtrados or None


def _clean_empresa(s: str) -> Optional[str]:
    if not isinstance(s, str):
        return None
    t = s.strip()
    t = re.sub(r"[\n\r\t]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = t.strip(" ?¿!.,;:")
    t = t.strip()
    if not t:
        return None
    # Evita capturar cosas que no son empresa en follow-ups
    low = t.lower()
    if low in {"eso", "esa", "ese", "ella", "ello", "esto", "esta", "este", "aquí", "ahí", "aqui", "ahi"}:
        return None
    if re.fullmatch(r"\d{4}", t):  # "2024"
        return None
    if low.startswith("en "):  # "en 2024"
        return None
    return t


def _extract_cif(text: str) -> Optional[str]:
    if not text:
        return None
    m = _CIF_RE.search(text.upper())
    return m.group(1).upper() if m else None


def _is_contextual_followup(q: str, history: Optional[List[Dict[str, str]]], last_state: Dict[str, Any]) -> bool:
    """Heurística para detectar preguntas dependientes del contexto previo."""
    if not history or not last_state:
        return False
    if len(q) > 160:
        return False

    empresa_candidate = _clean_empresa(q)
    # Solo lo tratamos como nueva entidad si parece una mención directa y breve (p.ej. "y Vodafone?")
    if empresa_candidate and len(empresa_candidate.split()) <= 6 and not _RE_FOLLOWUP_KEYWORDS.search(q.lower()):
        return False  # Parece una nueva entidad, mejor no forzar follow-up.

    low = q.lower()
    if _RE_FOLLOWUP_HINT.match(q):
        return True
    if "?" in q and _RE_FOLLOWUP_KEYWORDS.search(low):
        return True
    if len(q.split()) <= 8 and _RE_FOLLOWUP_KEYWORDS.search(low):
        return True

    return False


def detect_intent(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    last_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    q = (question or "").strip()
    last_state = last_state or {}
    last_focus = (last_state.get("last_focus") or "").upper()

    # 1) Saludo
    if _GREET_RE.match(q):
        return {
            "intent": "RAG_QA",
            "doc_tipo": None,
            "extracto_tipos": None,
            "needs_aggregation": False,
            "is_greeting": True,
            "is_followup": False,
            "focus": "CONTRATO",
            "empresa_query": None,
            "empresa_nif": None,
        }

    # 2) Agregación por empresa: "cuántos contratos ha ganado X"
    m = _RE_CUANTOS_CONTRATOS.search(q)
    if m:
        empresa = _clean_empresa(m.group(1))
        return {
            "intent": "CYPHER_QA",
            "doc_tipo": None,
            "extracto_tipos": None,
            "needs_aggregation": True,
            "is_greeting": False,
            "is_followup": False,
            "focus": "EMPRESA" if empresa else "CONTRATO",
            "empresa_query": empresa,
            "empresa_nif": _extract_cif(q),
        }

    # 3) Agregación por empresa: "importe total adjudicado a X"
    m = _RE_IMPORTE_TOTAL.search(q)
    if m:
        empresa = _clean_empresa(m.group(4))
        return {
            "intent": "CYPHER_QA",
            "doc_tipo": None,
            "extracto_tipos": None,
            "needs_aggregation": True,
            "is_greeting": False,
            "is_followup": False,
            "focus": "EMPRESA" if empresa else "CONTRATO",
            "empresa_query": empresa,
            "empresa_nif": _extract_cif(q),
        }

    # 4) Follow-up corto: "y Vodafone?"
    m = _RE_Y_SIMPLE.match(q)
    if m and last_focus == "EMPRESA":
        empresa = _clean_empresa(m.group(1))
        if empresa:
            return {
                "intent": "RAG_QA",
                "doc_tipo": None,
                "extracto_tipos": None,
                "needs_aggregation": False,
                "is_greeting": False,
                "is_followup": True,
                "focus": "EMPRESA",
                "empresa_query": empresa,
                "empresa_nif": _extract_cif(q),
            }

    # 5) Follow-up anafórico: "sobre el texto anterior / ese contrato"
    if _RE_PREV_REF.search(q) and last_state.get("last_contratos"):
        return {
            "intent": "RAG_QA",
            "doc_tipo": last_state.get("last_doc_tipo"),
            "extracto_tipos": last_state.get("last_extracto_tipos"),
            "needs_aggregation": False,
            "is_greeting": False,
            "is_followup": True,
            "focus": last_focus or "CONTRATO",
            "empresa_query": last_state.get("last_empresa_query"),
            "empresa_nif": last_state.get("last_empresa_nif"),
        }

    # 6) Empresa (RAG): "buscas info sobre X"
    m = _RE_BUSCA_INFO.search(q)
    if m:
        empresa = _clean_empresa(m.group(4))
        if empresa:
            return {
                "intent": "RAG_QA",
                "doc_tipo": None,
                "extracto_tipos": None,
                "needs_aggregation": False,
                "is_greeting": False,
                "is_followup": False,
                "focus": "EMPRESA",
                "empresa_query": empresa,
                "empresa_nif": _extract_cif(q),
            }

    # 7) Empresa (RAG): "adjudicaciones/contratos de X"
    m = _RE_ADJUDICACIONES.search(q)
    if m:
        empresa = _clean_empresa(m.group(3))
        if empresa:
            return {
                "intent": "RAG_QA",
                "doc_tipo": None,
                "extracto_tipos": None,
                "needs_aggregation": False,
                "is_greeting": False,
                "is_followup": False,
                "focus": "EMPRESA",
                "empresa_query": empresa,
                "empresa_nif": _extract_cif(q),
            }

    # 8) Empresa (RAG): "qué contratos ha ganado X"
    m = _RE_QUE_HA_GANADO.search(q)
    if m:
        empresa = _clean_empresa(m.group(3))
        if empresa:
            return {
                "intent": "RAG_QA",
                "doc_tipo": None,
                "extracto_tipos": None,
                "needs_aggregation": False,
                "is_greeting": False,
                "is_followup": False,
                "focus": "EMPRESA",
                "empresa_query": empresa,
                "empresa_nif": _extract_cif(q),
            }

    # 9) Empresa (RAG) corto: "... ha ganado X"
    m = _RE_HA_GANADO_CORTO.search(q)
    if m:
        empresa = _clean_empresa(m.group(1))
        if empresa:
            return {
                "intent": "RAG_QA",
                "doc_tipo": None,
                "extracto_tipos": None,
                "needs_aggregation": False,
                "is_greeting": False,
                "is_followup": False,
                "focus": "EMPRESA",
                "empresa_query": empresa,
                "empresa_nif": _extract_cif(q),
            }

    # 10) Follow-up contextual (preguntas cortas sobre la respuesta previa)
    if _is_contextual_followup(q, history, last_state):
        return {
            "intent": "RAG_QA",
            "doc_tipo": last_state.get("last_doc_tipo"),
            "extracto_tipos": last_state.get("last_extracto_tipos"),
            "needs_aggregation": False,
            "is_greeting": False,
            "is_followup": True,
            "focus": last_focus or "CONTRATO",
            "empresa_query": last_state.get("last_empresa_query"),
            "empresa_nif": last_state.get("last_empresa_nif"),
        }

    # 11) Fallback LLM router (tu lógica original ampliada)
    prompt = f"""
Fecha actual: {config.TODAY_STR}

Devuelve SOLO JSON válido:

{{
  "intent": "RAG_QA" | "CYPHER_QA" | "GENERATE_PPT",
  "doc_tipo": null | "PPT" | "PCAP",
  "extracto_tipos": null | ["normativas","solvencia_tecnica"],
  "needs_aggregation": true | false,
  "is_followup": true | false,

  "focus": "CONTRATO" | "EMPRESA",
  "empresa_query": null | "nombre/razón social (preferible al CIF)",
  "empresa_nif": null | "CIF/NIF si aparece"
}}

Reglas:
- Si pide contar/sumar/ranking/top => CYPHER_QA.
- Si pide PPT o pliego de prescripciones técnicas / pliego téncico => GENERATE_PPT.
- En otro caso => RAG_QA.
- Si habla de adjudicataria/empresa/ganados/adjudicaciones => focus="EMPRESA" y rellena empresa_query.
- CIF/NIF solo si aparece (no depender solo de CIF).
- doc_tipo y extracto_tipos como antes.

Tipos extracto conocidos:
{config.KNOWN_EXTRACTO_TYPES}

Pregunta:
\"\"\"{q}\"\"\"
"""
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Devuelve SOLO JSON válido."}, {"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=260,
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

    focus = (data.get("focus") or "CONTRATO").strip().upper()
    if focus not in ("CONTRATO", "EMPRESA"):
        focus = "CONTRATO"

    empresa_query = _clean_empresa(data.get("empresa_query") or "")
    empresa_nif = _extract_cif(data.get("empresa_nif") or "") or _extract_cif(q)
    is_followup = bool(data.get("is_followup"))

    return {
        "intent": intent,
        "doc_tipo": doc_tipo,
        "extracto_tipos": tipos,
        "needs_aggregation": needs_aggregation,
        "is_greeting": False,
        "is_followup": is_followup,
        "focus": focus,
        "empresa_query": empresa_query,
        "empresa_nif": empresa_nif,
    }
