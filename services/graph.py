"""
DEFINICIÓN DEL GRAFO: graph.py
DESCRIPCIÓN:
Aquí definimos el mapa de decisiones del Chatbot usando LangGraph.
Es como un diagrama de flujo donde determinamos qué nodo se ejecuta después de otro
basándonos en condiciones (edges).
"""

from langgraph.graph import StateGraph, END
from services.graph_state import AgentState
from services.graph_nodes import (
    router_node,
    greeting_node,
    cypher_node,
    rag_node,
    ppt_plan_node,
    ppt_generate_node,
    post_process_node,
    simple_chat_node
)

def define_graph():
    # Creamos un grafo de estado basado en 'AgentState' (definido en services/graph_state.py)
    workflow = StateGraph(AgentState)
    
    # 1. Definición de NODOS (Las cajas del diagrama de flujo)
    workflow.add_node("router", router_node)         # Clasificador de intención (Primer paso)
    workflow.add_node("greeting", greeting_node)     # Nodo de saludo
    workflow.add_node("cypher", cypher_node)         # Nodo para consultas exactas (SQL/Cypher)
    workflow.add_node("rag", rag_node)               # Nodo de búsqueda semántica (RAG)
    workflow.add_node("ppt_plan", ppt_plan_node)     # Planificador de PPT (pide aclaraciones)
    workflow.add_node("ppt_generate", ppt_generate_node) # Generador de PPT final
    workflow.add_node("simple_chat", simple_chat_node)   # Chat simple (memoria, cálculo)
    workflow.add_node("post_process", post_process_node) # Post-procesado (guardar historial, generar sugerencias)
    
    # 2. Definición de ARISTAS (Flechas del diagrama)
    
    # Punto de entrada: siempre empezamos en el Router
    workflow.set_entry_point("router")
    
    # Lógica de decisión desde el Router
    def route_intent(state: AgentState):
        intent_data = state["intent"]
        # Si es saludo -> Nodo Saludo
        if intent_data.get("is_greeting"):
            return "greeting"
        
        intent = intent_data.get("intent")
        
        # Enrutamiento según el tipo de intención detectada
        if intent == "GENERATE_PPT":
            return "ppt_plan"
        if intent == "CYPHER_QA":
            return "cypher"
        if intent == "SIMPLE_CHAT":
            return "simple_chat"
        
        # Por defecto -> RAG (Búsqueda en documentos)
        return "rag"
    
    # Condiciones desde ROUTER
    workflow.add_conditional_edges(
        "router",
        route_intent,
        {
            "greeting": "greeting",
            "ppt_plan": "ppt_plan",
            "cypher": "cypher",
            "simple_chat": "simple_chat",
            "rag": "rag"
        }
    )

    # Condiciones desde RAG (Búsqueda)
    def route_rag(state: AgentState):
        # Si el RAG falla y necesita datos estructurados -> Cypher
        if state["intent"].get("needs_cypher_fallback"):
            return "cypher"
        # Si no, terminamos
        return "post_process"

    workflow.add_conditional_edges(
        "rag",
        route_rag,
        {
            "cypher": "cypher",
            "post_process": "post_process"
        }
    )

    # Condiciones desde CHAT SIMPLE
    def route_simple_chat(state: AgentState):
        # Si el chat simple no sabe la respuesta -> Mandamos de vuelta al Router para buscar información (RAG)
        if state["intent"].get("needs_rag_fallback"):
            state["intent"]["intent"] = "RAG_QA" 
            return "router"
        return "post_process"

    workflow.add_conditional_edges(
        "simple_chat",
        route_simple_chat,
        {
            "router": "router",
            "post_process": "post_process"
        }
    )

    # Condiciones desde PPT PLAN
    def route_ppt(state: AgentState):
        # Si faltan datos -> Terminamos (para pedir al usuario)
        if state["intent"].get("ppt_clarifications_needed"):
            return "post_process"
        # Si tenemos todo -> Generamos el PPT
        return "ppt_generate"

    workflow.add_conditional_edges(
        "ppt_plan",
        route_ppt,
        {
            "post_process": "post_process",
            "ppt_generate": "ppt_generate"
        }
    )
    
    # Edges directos (sin condición)
    workflow.add_edge("greeting", "post_process")
    workflow.add_edge("cypher", "post_process")
    workflow.add_edge("ppt_generate", "post_process")
    
    # Final del camino
    workflow.add_edge("post_process", END)
    
    return workflow.compile()

# Singleton (Instancia única del grafo compilado)
chatbot_graph = define_graph()
