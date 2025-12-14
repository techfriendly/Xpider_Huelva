"""Utilidades relacionadas con texto y presupuesto de tokens."""
from typing import Dict, List

import config


def clip(s: str, max_chars: int) -> str:
    s = s or ""
    return s if len(s) <= max_chars else s[:max_chars] + " […]"


def enforce_budget(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars] + " […]"


def estimate_tokens(text: str) -> int:
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
    budget = max_context_tokens - reserve_for_answer
    used = estimate_tokens(system_msg) + estimate_tokens(user_msg)
    trimmed: List[Dict[str, str]] = []
    for m in reversed(history):
        mt = estimate_tokens(m.get("content", ""))
        if used + mt > budget:
            break
        trimmed.append(m)
        used += mt
    return list(reversed(trimmed))


def context_token_report(system_msg: str, history: List[Dict[str, str]], user_msg: str) -> Dict[str, int]:
    sys_t = estimate_tokens(system_msg)
    hist_t = sum(estimate_tokens(m.get("content", "")) for m in history)
    user_t = estimate_tokens(user_msg)
    total = sys_t + hist_t + user_t
    return {"system": sys_t, "history": hist_t, "user": user_t, "total": total}
