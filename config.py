"""
ARCHIVO DE CONFIGURACIÓN: config.py
DESCRIPCIÓN:
Aquí se definen las "constantes" y configuraciones globales.
Se leen del entorno (archivo .env) o se usan valores por defecto si no existen.
"""

import os
from datetime import date

# Fecha actual (útil para consultas que dependen del tiempo)
TODAY_STR = date.today().isoformat()

# --- SECCIÓN 1: CONEXIÓN CON NEO4J (BASE DE DATOS DE CONOCIMIENTO) ---
# Datos para conectar con el grafo donde están los contratos y empresas.

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://49.13.151.49:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "root_tech_2019")
NEO4J_DB = os.getenv("NEO4J_DB", "huelva")

# --- SECCIÓN 2: LARGE LANGUAGE MODEL (LLM) - EL CEREBRO --- 
# Configuración del modelo de IA generativa (similares a GPT-4).

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://100.71.46.94:8002/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "dummy-key")
LLM_MODEL = os.getenv("LLM_MODEL", "llm")

# --- SECCIÓN 3: EMBEDDINGS (BÚSQUEDA SEMÁNTICA) ---
# Configuración del modelo que convierte texto en vectores numéricos para buscar por significado.

EMB_BASE_URL = os.getenv("EMB_BASE_URL", "http://100.71.46.94:8003/v1")
EMB_API_KEY = os.getenv("EMB_API_KEY", "dummy-key")
EMB_MODEL = os.getenv("EMB_MODEL", "embedding")
EMB_DIM = int(os.getenv("EMB_DIM", "1024")) # Dimensión del vector (debe coincidir con la BD)

# --- SECCIÓN 4: PARÁMETROS DE RECUPERACIÓN (RAG) ---
# Cuántos documentos recuperamos de la base de datos para responder.

K_CONTRATOS = int(os.getenv("K_CONTRATOS", "5"))   # Cuántos contratos similares buscar
K_CAPITULOS = int(os.getenv("K_CAPITULOS", "25"))  # Cuántos capítulos de pliegos leer
K_EXTRACTOS = int(os.getenv("K_EXTRACTOS", "50"))  # Cuántos fragmentos de texto analizar

# Configuración del historial de chat
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "12")) # Cuántos mensajes recordamos
SUGGESTION_LABEL_MAX_CHARS = int(os.getenv("SUGGESTION_LABEL_MAX_CHARS", "100"))

# --- SECCIÓN 5: LÍMITES DE SEGURIDAD (TOKENS) ---
# Para no saturar la memoria del modelo.

MODEL_MAX_CONTEXT_TOKENS = int(os.getenv("MODEL_MAX_CONTEXT_TOKENS", "30000")) # Máximo total
RESERVE_FOR_ANSWER_TOKENS = int(os.getenv("RESERVE_FOR_ANSWER_TOKENS", "6000")) # Reservado para escribir respuesta
MEMORY_SUMMARY_TOKENS = int(os.getenv("MEMORY_SUMMARY_TOKENS", "1500")) # Tamaño del resumen de memoria

# Límite específico para el contexto RAG (documentos leídos)
RAG_CONTEXT_MAX_TOKENS = int(os.getenv("RAG_CONTEXT_MAX_TOKENS", "12000"))
RAG_CONTEXT_MAX_CHARS = RAG_CONTEXT_MAX_TOKENS * 4

# --- SECCIÓN 6: LÓGICA DE NEGOCIO ---
# Tipos de extractos (documentos) que sabemos manejar específicamente.

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
