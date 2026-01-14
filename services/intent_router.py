"""
CLASIFICADOR DE INTENCIÓN: intent_router.py
DESCRIPCIÓN:
Componente crítico que analiza la frase del usuario y decide:
1. Qué quiere hacer (Buscar información, una estadística rápida, un PPT, saludar...).
2. Si está hablando de una empresa específica o de contratación en general.
3. Si es una continuación ("follow-up") de la pregunta anterior.

Combina "Reglas Fijas" (Expresiones Regulares) rápidas con un "Cerebro" (LLM) para dudas complejas.
"""

import re
from typing import Any, Dict, List, Optional

import config
from clients import llm_client
from chat_utils.json_utils import safe_json_loads
from chat_utils.prompt_loader import load_prompt


# --- EXPRESIONES REGULARES (Reglas rápidas) ---
# Sirven para detectar patrones obvios sin tener que "pensar" demasiado (ahorra tiempo y costes)

# Detectar un CIF (Código de Identificación Fiscal: Letra + 8 dígitos)
_CIF_RE = re.compile(r"\b([A-Z]\d{8})\b", re.IGNORECASE)

# Detectar Saludos comunes
_GREET_RE = re.compile(
    r"^\s*(hola|gracias|adios|buenas|buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|hey|hello|hi|qué\s+tal|que\s+tal)\s*[!.?,]*\s*$",
    re.IGNORECASE,
)

# Patrones para saber si buscamos información de una Empresa (RAG)
_RE_BUSCA_INFO = re.compile(r"\b(busca|buscas|buscar)\s+(info|informaci[oó]n)\s+(sobre|de)\s+(.+)$", re.IGNORECASE)
_RE_ADJUDICACIONES = re.compile(r"\b(adjudicaciones|contratos)\s+(de|del)\s+(.+)$", re.IGNORECASE)
_RE_QUE_HA_GANADO = re.compile(r"\b(qu[eé])\s+(contratos?)\s+(ha\s+)?ganado\s+(.+)$", re.IGNORECASE)
_RE_HA_GANADO_CORTO = re.compile(r"\b(ha\s+)?ganado\s+(contratos?\s+)?(.+)$", re.IGNORECASE)

# Patrones para saber si queremos contar o sumar (Cypher)
_RE_CUANTOS_CONTRATOS = re.compile(r"\bcu[aá]ntos?\s+contratos?\s+ha\s+ganado\s+(.+)$", re.IGNORECASE)
_RE_IMPORTE_TOTAL = re.compile(
    r"\b(importe\s+total|total\s+adjudicado|cu[aá]nto\s+(dinero|importe))\b.*\b(ha\s+ganado|adjudicado|a)\s+(.+)$",
    re.IGNORECASE,
)

# Detectar preguntas "Follow-up" (continuación)
# Ejemplo Simple: "y Vodafone?" (Elipsis)
_RE_Y_SIMPLE = re.compile(r"^\s*y\s+(.+?)(?:\s+ha\s+ganado.*)?\s*[?¿!]*\s*$", re.IGNORECASE)

# Ejemplo Referencial: "sobre el contrato anterior", "de esa empresa" (Anáfora)
_RE_PREV_REF = re.compile(
    r"\b(ese|este|esa|esta|dicho|anterior|previo|último|ultimo|primer|primero|segundo|tercer|cuarto|quinto)\s+(contrato|expediente|pliego|texto|caso|opción|opcion|tabla)\b"
    r"|\b(en|sobre|respecto\s+a|acerca\s+de|del|de\s+la)\s+"
    r"(ese|este|esa|esta|dicho|anterior|previo|último|ultimo|primer|primero|segundo|tercer|cuarto|quinto)\s+(contrato|expediente|pliego|texto|caso|opción|opcion|tabla)\b",
    re.IGNORECASE,
)

# Palabras clave que sugieren que pedimos más detalles sobre lo mismo
_RE_FOLLOWUP_HINT = re.compile(r"^\s*(y|adem[aá]s|ademas|tamb[ií]en|otra\s+cosa)\b", re.IGNORECASE)
_RE_FOLLOWUP_KEYWORDS = re.compile(
    r"\b(importe|presupuesto|duraci[oó]n|plazo|fecha|cuando|qu[ií]en|c[uú]al(es)?|detalles?"
    r"|normativa|ley|lcsp|rglcap|ens|protecci[oó]n\s+de\s+datos|rgpd|qu[eé]\s+va|qu[eé]\s+pasa|objetivo|objeto|descripci[oó]n|descripcion)\b",
    re.IGNORECASE,
)

# --- FUNCIONES AUXILIARES DE LIMPIEZA ---

def _normalize_extracto_types(tipos: Any) -> Optional[List[str]]:
    """Filtra tipos de documentos conocidos (ej: normativa, solvencia) para evitar basura."""
    if not isinstance(tipos, list):
        return None
    tipos_filtrados = [t for t in tipos if t in config.KNOWN_EXTRACTO_TYPES]
    return tipos_filtrados or None


def _clean_empresa(s: str) -> Optional[str]:
    """Limpia el nombre de la empresa detectado para quitar ruido (ej: 'contratos de Vodafone' -> 'Vodafone')."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    t = re.sub(r"[\n\r\t]+", " ", t)       # Quitar saltos de línea
    t = re.sub(r"\s{2,}", " ", t)          # Quitar espacios dobles
    t = t.strip(" ?¿!.,;:")                # Quitar puntuación
    t = t.strip()
    if not t:
        return None
    
    # Limpieza específica para mejorar la detección
    low = t.lower()
    low = re.sub(r"^(contratos\s+de\s+|contrato\s+de\s+|de\s+|del\s+|sobre\s+|acerca\s+de\s+)", "", low)
    low = re.sub(r"(\s+ha\s+ganado.*|\s+ganados?.*|\s+contratos?.*)$", "", low)
    t = t[len(t)-len(low):].strip() if len(t) > len(low) else t.strip() # Recortar original preservando mayúsculas

    # Evitamos pronombres o fechas que se cuelan como nombres de empresa
    if low in {"eso", "esa", "ese", "ella", "ello", "esto", "esta", "este", "aquí", "ahí", "aqui", "ahi"}:
        return None
    if re.fullmatch(r"\d{4}", t):  # Años (2024)
        return None
    if low.startswith("en "):  # "en 2024"
        return None
    return t


def _extract_cif(text: str) -> Optional[str]:
    """Busca un patrón tipo NIF/CIF en el texto."""
    if not text:
        return None
    m = _CIF_RE.search(text.upper())
    return m.group(1).upper() if m else None


def _is_contextual_followup(q: str, history: Optional[List[Dict[str, str]]], last_state: Dict[str, Any]) -> bool:
    """Intenta adivinar (sin IA) si la pregunta depende de la anterior."""
    if not history or not last_state:
        return False
    if len(q) > 160: # Si es muy larga, probablemente es una pregunta nueva con contexto propio
        return False

    empresa_candidate = _clean_empresa(q)
    # Si detectamos una empresa nueva y es corta (ej: "y Vodafone?"), puede ser follow-up de cambio de entidad.
    if empresa_candidate and len(empresa_candidate.split()) <= 6 and not _RE_FOLLOWUP_KEYWORDS.search(q.lower()):
        return False  # Nueva entidad -> Nueva búsqueda (probablemente)

    low = q.lower()
    if _RE_FOLLOWUP_HINT.match(q): # Empieza por "y...", "además..."
        return True
    if "?" in q and _RE_FOLLOWUP_KEYWORDS.search(low): # Pregunta con palabras clave de detalle
        return True
    if len(q.split()) <= 8 and _RE_FOLLOWUP_KEYWORDS.search(low): # Frase corta con palabras clave
        return True

    return False

# --- FUNCIÓN PRINCIPAL DE DETECCIÓN INTELIGENTE ---
def detect_intent(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    last_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Usa un LLM (modelo de lenguaje) para clasificar la intención del usuario.
    Devuelve un diccionario JSON con la decisión: qué hacer, qué buscar, etc.
    """
    q = (question or "").strip()
    last_state = last_state or {}
    
    # Check rápido de Saludo (para no gastar tokens de LLM en un "Hola")
    if _GREET_RE.match(q):
        return {
            "intent": "GREETING",
            "doc_tipo": None,
            "extracto_tipos": None,
            "needs_aggregation": False,
            "is_greeting": True,
            "is_followup": False,
            "focus": "GENERAL",
            "empresa_query": None,
            "empresa_nif": None,
        }

    # Preparamos el historial para dárselo al LLM (últimos turnos)
    history_str = ""
    if history:
        for turn in history[-4:]:
            role = "Usuario" if turn["role"] == "user" else "Asistente"
            content = turn["content"]
            if len(content) > 300: # Recortamos respuestas largas
                content = content[:300] + "..."
            history_str += f"{role}: {content}\n"
    
    # Inyectamos el "estado mental" previo del bot (qué estaba buscando antes)
    if last_state:
        last_intent = last_state.get("last_intent")
        last_focus = last_state.get("last_focus")
        if last_intent or last_focus:
            history_str += f"\n(Estado actual del sistema: Intención={last_intent}, Foco={last_focus})\n"
    
    if not history_str:
        history_str = "(Sin historial previo)"

    # Cargamos la plantilla de prompt (la 'receta' para el LLM)
    prompt = load_prompt(
        "intent_router",
        today=config.TODAY_STR,
        extracto_types=config.KNOWN_EXTRACTO_TYPES,
        history=history_str,
        question=q
    )
    
    # Llamamos al modelo (con temperatura 0.0 para ser muy determinista y preciso)
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Devuelve SOLO JSON válido."}, {"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=300,
    )
    
    # Convertimos la respuesta de texto del LLM a un objeto Python (Diccionario)
    data = safe_json_loads(resp.choices[0].message.content or "") or {}

    # Validamos y saneamos campos críticos
    intent = data.get("intent", "RAG_QA")
    if intent not in ("RAG_QA", "CYPHER_QA", "GENERATE_PPT", "GREETING", "SIMPLE_CHAT"):
        intent = "RAG_QA" # Por defecto buscamos en documentos

    doc_tipo = data.get("doc_tipo")
    if doc_tipo not in (None, "PPT", "PCAP"):
        doc_tipo = None

    tipos = _normalize_extracto_types(data.get("extracto_tipos"))
    needs_aggregation = bool(data.get("needs_aggregation", intent == "CYPHER_QA"))

    focus = (data.get("focus") or "CONTRATO").strip().upper()
    if focus not in ("CONTRATO", "EMPRESA", "GENERAL"):
        focus = "CONTRATO"

    empresa_query = _clean_empresa(data.get("empresa_query") or "")
    empresa_nif = _extract_cif(data.get("empresa_nif") or "") or _extract_cif(q)
    is_followup = bool(data.get("is_followup"))
    rewritten = data.get("rewritten_query")

    return {
        "intent": intent,
        "doc_tipo": doc_tipo,
        "extracto_tipos": tipos,
        "needs_aggregation": needs_aggregation,
        "is_greeting": (intent == "GREETING"),
        "is_followup": is_followup,
        "focus": focus,
        "empresa_query": empresa_query,
        "empresa_nif": empresa_nif,
        "rewritten_query": rewritten
    }
