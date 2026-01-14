"""
CARGADOR DE PROMPTS: prompt_loader.py
DESCRIPCIÓN:
Carga las plantillas de texto (prompts) desde la carpeta 'prompts/'.
Permite inyectar variables dinámicas (como {today} o {question}) dentro del texto.
"""

import os
from typing import Dict, Any

# Ruta absoluta a la carpeta de prompts
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

# Caché en memoria para no leer el disco en cada petición
_prompts_cache: Dict[str, str] = {}

def load_prompt(prompt_name: str, **kwargs: Any) -> str:
    """
    Carga un archivo .txt de la carpeta prompts y reemplaza sus variables.
    
    Args:
        prompt_name: Nombre del archivo sin extensión (ej: 'intent_router').
        **kwargs: Variables a reemplazar (ej: question="Hola").
        
    Returns:
        El texto final listo para enviar al LLM.
    """
    # 1. Cargar desde disco si no está en caché
    if prompt_name not in _prompts_cache:
        file_path = os.path.join(PROMPTS_DIR, f"{prompt_name}.txt")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"No encuentro el archivo de prompt: {file_path}")
            
        with open(file_path, "r", encoding="utf-8") as f:
            _prompts_cache[prompt_name] = f.read().strip()
            
    prompt_template = _prompts_cache[prompt_name]
    
    # 2. Formatear con variables (si las hay)
    if kwargs:
        return prompt_template.format(**kwargs)
        
    return prompt_template

def clear_prompts_cache():
    """Limpia la caché (útil si editamos prompts en caliente)."""
    _prompts_cache.clear()
