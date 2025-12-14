"""Clientes compartidos (Neo4j y modelos LLM/embeddings)."""
from neo4j import GraphDatabase
from openai import OpenAI

import config


driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
llm_client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
emb_client = OpenAI(base_url=config.EMB_BASE_URL, api_key=config.EMB_API_KEY)
