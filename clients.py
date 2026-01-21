"""
CLIENTES V2: clients.py
Conexiones con servicios externos.
"""
from neo4j import GraphDatabase
from openai import OpenAI
import config

# Neo4j
driver = GraphDatabase.driver(
    config.NEO4J_URI,
    auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
)

# LLM
llm_client = OpenAI(
    base_url=config.LLM_BASE_URL,
    api_key=config.LLM_API_KEY
)

# Embeddings (puede ser mismo endpoint u otro)
emb_client = OpenAI(
    base_url=config.EMB_BASE_URL,
    api_key=config.EMB_API_KEY
)
