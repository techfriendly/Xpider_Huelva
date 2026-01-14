"""
UTILIDADES JSON: json_utils.py
DESCRIPCIÓN:
Ayuda a limpiar y convertir respuestas del LLM a formato JSON (diccionario)
incluso si el modelo incluye Markdown (bloques ```json ... ```) o texto extra.
"""

import json
import re
from typing import Any, Dict, Optional

def _strip_code_fences(s: str) -> str:
    """Elimina las comillas triples de código Markdown (```json) de un string."""
    s = (s or "").strip()
    # Quitamos prefijo ```json (o cualquier lenguaje)
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    # Quitamos sufijo ```
    s = re.sub(r"\s*```$", "", s)
    s = s.replace("```", "").strip()
    
    # Buscamos el primer '{' y el último '}' para recortar basura externa
    i = s.find("{")
    j = s.rfind("}")
    if i >= 0 and j > i:
        s = s[i : j + 1]
    return s.strip()

def safe_json_loads(s: str) -> Optional[Dict[str, Any]]:
    """Intenta convertir un string a Diccionario de forma segura, sin romper si falla."""
    try:
        return json.loads(_strip_code_fences(s))
    except Exception:
        return None
