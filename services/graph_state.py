"""
ESTADO DEL GRAFO: graph_state.py
DESCRIPCIÓN:
Define la estructura de datos ("Estado") que se pasa de un nodo a otro en el grafo.
Es como la "memoria compartida" durante la ejecución de una pregunta.
"""

from typing import Annotated, Dict, Any, List, Optional, Union
from typing_extensions import TypedDict
import operator

class AgentState(TypedDict):
    # La pregunta original del usuario
    question: str
    
    # Estado Interno o Memoria
    history: List[Dict[str, str]]    # Historial de chat previo
    router_state: Dict[str, Any]     # Memoria a largo plazo (filtros previos, empresa actual...)
    intent: Optional[Dict[str, Any]] # Clasificación de la intención (RAG, Saludo, etc.)
    
    # Parámetros intermedios para generación de respuesta (Orquestador)
    answer_prompt: Optional[Dict[str, Any]]      # Prompt listo para RAG
    ppt_generation_input: Optional[Dict[str, Any]] # Prompt listo para PPT
    
    # Resultados encontrados
    answer: Optional[str]                        # Respuesta final de texto
    contratos: Optional[List[Dict[str, Any]]]    # Lista de contratos encontrados
    capitulos: Optional[List[Dict[str, Any]]]    # Lista de capítulos de pliegos encontrados
    extractos: Optional[List[Dict[str, Any]]]    # Lista de fragmentos de texto encontrados
    
    # Elementos de UI (para Chainlit)
    thinking_message_id: Optional[str]   # ID del mensaje "Pensando..." para actualizarlo
    sidebar_title: Optional[str]         # Título de la barra lateral
    sidebar_md: Optional[str]            # Contenido Markdown de la barra lateral
    sidebar_props: Optional[Dict[str, Any]] # Propiedades extra para la UI
    follow_ups: Optional[List[str]]      # Preguntas sugeridas generadas
    element_to_send: Optional[Any]       # Archivos adjuntos (Word, Imagen...)
    
    # Errores
    error: Optional[str]                 # Mensaje de error si algo falla
