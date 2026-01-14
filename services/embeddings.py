"""
EMBEDDINGS (VECTORES): embeddings.py
DESCRIPCIÓN:
Convierte texto (preguntas del usuario, contenido de contratos) en listas de números (vectores).
Esto permite a la base de datos (Neo4j) buscar por "significado" y no solo por palabras clave.
"""

from typing import List
from clients import emb_client
import config


def embed_text(text: str, max_chars: int = 4000) -> List[float]:
    """
    Genera el vector numérico para un texto dado.
    Recortamos a 4000 caracteres para no exceder el límite del modelo de embeddings.
    """
    if not text:
        return []
    text = text[:max_chars]
    
    # Llamada a la API de Embeddings (OpenAI compatible)
    resp = emb_client.embeddings.create(model=config.EMB_MODEL, input=text)
    
    # Devolvemos la lista de float (ej: [0.12, -0.04, ...])
    return resp.data[0].embedding
