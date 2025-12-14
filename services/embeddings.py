"""Wrapper sencillo para generar embeddings de texto."""
from typing import List

from clients import emb_client
import config


def embed_text(text: str, max_chars: int = 4000) -> List[float]:
    if not text:
        return []
    text = text[:max_chars]
    resp = emb_client.embeddings.create(model=config.EMB_MODEL, input=text)
    return resp.data[0].embedding
