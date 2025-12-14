"""Utilidades de resumen y generación de preguntas de seguimiento."""
from typing import List

import config
from clients import llm_client
from utils.json_utils import safe_json_loads


def summarize_for_memory(text: str, max_tokens: int = config.MEMORY_SUMMARY_TOKENS) -> str:
    if not text:
        return ""
    prompt = f"""
Resume lo siguiente en {max_tokens} tokens máximo:
\"\"\"{text}\"\"\"
"""
    resp = llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": "Resumidor breve."}, {"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=max_tokens + 50,
    )
    return resp.choices[0].message.content or ""


def should_generate_followups(answer: str, contratos, capitulos, extractos) -> bool:
    if not answer:
        return False
    evidence_count = len(contratos or []) + len(capitulos or []) + len(extractos or [])
    return evidence_count > 0 and len(answer) >= 200


def generate_follow_up_questions(question: str, answer: str, max_suggestions: int = 3) -> List[str]:
    prompt = f"""
Eres un asistente de contratación pública.
Genera {max_suggestions} preguntas de seguimiento inteligentes y variadas, en castellano.
Basadas en la pregunta y la respuesta previa.
Devuelve SOLO JSON:
{{"questions": ["..."]}}

Pregunta original:
\"\"\"{question}\"\"\"

Respuesta anterior:
\"\"\"{answer}\"\"\"
"""
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
    return [str(q) for q in questions if q]
