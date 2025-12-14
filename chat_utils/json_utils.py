"""Utilidades de parsing JSON tolerantes a respuestas con fences."""
import json
import re
from typing import Any, Dict, Optional


def _strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = s.replace("```", "").strip()
    i = s.find("{")
    j = s.rfind("}")
    if i >= 0 and j > i:
        s = s[i : j + 1]
    return s.strip()


def safe_json_loads(s: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_strip_code_fences(s))
    except Exception:
        return None
