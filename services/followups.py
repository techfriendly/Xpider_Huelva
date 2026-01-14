"""
SEGUIMIENTO Y SUGERENCIAS: followups.py
DESCRIPCIÓN:
Utilidades para generar preguntas sugeridas ("¿Quieres saber más sobre X?")
y para resumir textos largos antes de guardarlos en la memoria.
"""

from typing import List
import config
from clients import llm_client
from chat_utils.json_utils import safe_json_loads
from chat_utils.prompt_loader import load_prompt


def summarize_for_memory(text: str, max_tokens: int = config.MEMORY_SUMMARY_TOKENS) -> str:
    """
    Resume una respuesta larga del asistente para que ocupe menos espacio
    en el historial de conversación (memoria a corto plazo).
    """
    if not text:
        return ""
    prompt = load_prompt("summarize_memory", max_tokens=max_tokens, text=text)
    
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Resumidor breve."}, {"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=max_tokens + 50,
    )
    return resp.choices[0].message.content or ""


def should_generate_followups(answer: str, contratos, capitulos, extractos) -> bool:
    """
    Decide si vale la pena generar preguntas sugeridas.
    Solo lo hacemos si hemos encontrado evidencias reales (contratos, etc.)
    y si la respuesta es mínimamente sustancial.
    """
    if not answer:
        return False
    evidence_count = len(contratos or []) + len(capitulos or []) + len(extractos or [])
    return evidence_count > 0 and len(answer) >= 200


def generate_follow_up_questions(question: str, answer: str, max_suggestions: int = 3) -> List[str]:
    """
    Genera 3 preguntas cortas relacionadas con la respuesta que acabamos de dar,
    para invitar al usuario a seguir explorando.
    """
    prompt = load_prompt(
        "followup_questions",
        max_suggestions=max_suggestions,
        question=question,
        answer=answer
    )
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Devuelve SOLO JSON."}, {"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=280,
    )
    data = safe_json_loads(resp.choices[0].message.content or "") or {}
    questions = data.get("questions") or []
    
    if not isinstance(questions, list):
        return []
    # Convertimos a string por seguridad
    return [str(q) for q in questions if q]
