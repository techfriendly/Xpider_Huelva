
# Función auxiliar para generar cabecera de contexto de empresa
def _empresa_context_header(empresa_query: str, nif_found: str) -> str:
    """Genera una cabecera de texto para el contexto del LLM."""
    if nif_found:
        return f"Focus: EMPRESA (Query: '{empresa_query}', NIF: {nif_found})"
    return f"Focus: EMPRESA (Query: '{empresa_query}')"
