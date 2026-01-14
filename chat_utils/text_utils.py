"""
UTILIDADES DE TEXTO: text_utils.py
DESCRIPCIÓN:
Funciones auxiliares para trabajar con cadenas de texto (Strings).
Principalmente calculan costes (tokens) y recortan textos para que quepan en la memoria del modelo.
"""

from typing import Dict, List
import config

def clip(s: str, max_chars: int) -> str:
    """Corta una string si se pasa de caracteres y añade puntos suspensivos."""
    s = s or ""
    return s if len(s) <= max_chars else s[:max_chars] + " […]"

def enforce_budget(text: str, max_chars: int) -> str:
    """Igual que clip, usado para asegurar límites de presupuesto de contexto."""
    return text if len(text) <= max_chars else text[:max_chars] + " […]"

def estimate_tokens(text: str) -> int:
    """
    Calcula aproximadamente cuántos tokens consume un texto.
    Regla general rápida: 1 token ~= 4 caracteres.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)

def trim_history_to_fit(
    history: List[Dict[str, str]],
    system_msg: str,
    user_msg: str,
    max_context_tokens: int = config.MODEL_MAX_CONTEXT_TOKENS,
    reserve_for_answer: int = config.RESERVE_FOR_ANSWER_TOKENS,
) -> List[Dict[str, str]]:
    """
    Recorta el historial de chat (mensajes antiguos) para que la nueva pregunta
    y la instrucción del sistema quepan en la ventana de contexto del modelo.
    Empieza quitando los mensajes más viejos.
    """
    budget = max_context_tokens - reserve_for_answer
    used = estimate_tokens(system_msg) + estimate_tokens(user_msg)
    
    # Vamos añadiendo mensajes del más nuevo al más viejo hasta llenar presupuesto
    trimmed: List[Dict[str, str]] = []
    for m in reversed(history):
        mt = estimate_tokens(m.get("content", ""))
        if used + mt > budget:
            break
        trimmed.append(m)
        used += mt
    
    # Devolvemos la lista en orden cronológico correcto
    return list(reversed(trimmed))

def context_token_report(system_msg: str, history: List[Dict[str, str]], user_msg: str) -> Dict[str, int]:
    """Genera un reporte de cuántos tokens estamos gastando en total."""
    sys_t = estimate_tokens(system_msg)
    hist_t = sum(estimate_tokens(m.get("content", "")) for m in history)
    user_t = estimate_tokens(user_msg)
    total = sys_t + hist_t + user_t
    return {"system": sys_t, "history": hist_t, "user": user_t, "total": total}
