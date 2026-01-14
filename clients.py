"""
CLIENTES EXTERNOS: clients.py
DESCRIPCIÓN:
Aquí inicializamos las conexiones con servicios externos que usaremos en toda la aplicación.
En lugar de conectar cada vez, creamos una conexión única ("Singleton") y la reutilizamos.
"""

from neo4j import GraphDatabase
from openai import OpenAI
import config

# 1. CLIENTE NEO4J (Grafo de Conocimiento)
# Conexión con la base de datos donde están los contratos y relaciones.
# Usamos el 'driver' oficial para lanzar consultas Cypher.
driver = GraphDatabase.driver(
    config.NEO4J_URI, 
    auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
)

# 2. CLIENTE LLM (El Cerebro)
# Conexión con el modelo de lenguaje (como GPT-4) para generar texto.
llm_client = OpenAI(
    base_url=config.LLM_BASE_URL, 
    api_key=config.LLM_API_KEY
)

# 3. CLIENTE EMBEDDINGS (Buscador Semántico)
# Conexión con el modelo que entiende el significado de las palabras para buscar documentos similares.
emb_client = OpenAI(
    base_url=config.EMB_BASE_URL, 
    api_key=config.EMB_API_KEY
)
