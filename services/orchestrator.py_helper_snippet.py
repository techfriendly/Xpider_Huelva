
# Función auxiliar para resolver nombre/NIF de empresa
def _empresa_lookup(intent: Dict[str, Any], router_state: Dict[str, Any]) -> str:
    """Intenta obtener el mejor string de búsqueda para una empresa."""
    # 1. Prioridad: NIF explícito
    if intent.get("empresa_nif"):
        return intent["empresa_nif"]
    
    # 2. Prioridad: Nombre explícito en la query
    if intent.get("empresa_query"):
        return intent["empresa_query"]
        
    # 3. Contexto previo (estado del router)
    if router_state.get("last_empresa_nif"):
        return router_state["last_empresa_nif"]
    if router_state.get("last_empresa_query"):
        return router_state["last_empresa_query"]
        
    return ""
