"""Configuración y constantes de la aplicación Chainlit."""
import os
from datetime import date

TODAY_STR = date.today().isoformat()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://49.13.151.49:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "root_tech_2019")
NEO4J_DB = os.getenv("NEO4J_DB", "huelva")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://100.71.46.94:8002/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "dummy-key")
LLM_MODEL = os.getenv("LLM_MODEL", "llm")

EMB_BASE_URL = os.getenv("EMB_BASE_URL", "http://100.71.46.94:8003/v1")
EMB_API_KEY = os.getenv("EMB_API_KEY", "dummy-key")
EMB_MODEL = os.getenv("EMB_MODEL", "embedding")
EMB_DIM = int(os.getenv("EMB_DIM", "1024"))

K_CONTRATOS = int(os.getenv("K_CONTRATOS", "3"))
K_CAPITULOS = int(os.getenv("K_CAPITULOS", "15"))
K_EXTRACTOS = int(os.getenv("K_EXTRACTOS", "50"))

MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "12"))
SUGGESTION_LABEL_MAX_CHARS = int(os.getenv("SUGGESTION_LABEL_MAX_CHARS", "100"))

MODEL_MAX_CONTEXT_TOKENS = int(os.getenv("MODEL_MAX_CONTEXT_TOKENS", "40000"))
RESERVE_FOR_ANSWER_TOKENS = int(os.getenv("RESERVE_FOR_ANSWER_TOKENS", "6000"))
MEMORY_SUMMARY_TOKENS = int(os.getenv("MEMORY_SUMMARY_TOKENS", "600"))

RAG_CONTEXT_MAX_TOKENS = int(os.getenv("RAG_CONTEXT_MAX_TOKENS", "12000"))
RAG_CONTEXT_MAX_CHARS = RAG_CONTEXT_MAX_TOKENS * 4

KNOWN_EXTRACTO_TYPES = [
    "normativa",
#    "presupuesto_base",
    "garantia_definitiva",
    "garantia_otros_tipos",
#    "duracion_y_prorrogas",
    "solvencia_tecnica",
    "solvencia_economica",
#    "modificacion_contrato",
#    "causas_imprevistas",
#    "criterios_adjudicacion",
    "criterios_ambientales",
    "clausulas_sociales",
    "clausulas_igualdad_genero",
#    "medios_personales",
#    "medios_materiales",
#    "CPV",
]
