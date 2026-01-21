import os
import requests
import sys

# Load environment like app.py does
from dotenv import load_dotenv
load_dotenv()

# Configuration to test
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://100.71.46.94:8002/v1")
EMB_BASE_URL = os.getenv("EMB_BASE_URL", "http://100.71.46.94:8003/v1")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://49.13.151.49:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "root_tech_2019")

def test_url(name, url):
    print(f"Testing {name} at {url} ...", end=" ")
    try:
        # Try a simple GET or POST. 
        # For OpenAI-compatible APIs, /models is usually a safe GET
        target = f"{url.rstrip('/')}/models"
        resp = requests.get(target, timeout=5)
        if resp.status_code == 200:
            print("✅ OK")
            return True
        else:
            print(f"❌ Error {resp.status_code}")
            print(f"   Response: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        return False

def test_neo4j():
    print(f"Testing Neo4j at {NEO4J_URI} ...", end=" ")
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("✅ OK")
        return True
    except ImportError:
        print("⚠️ Skipped (neo4j library not installed)")
        return False
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        return False

if __name__ == "__main__":
    print("--- SERVER DIAGNOSTICS ---")
    print("Running from:", os.getcwd())
    
    ok_llm = test_url("LLM Service", LLM_BASE_URL)
    ok_emb = test_url("Embedding Service", EMB_BASE_URL)
    ok_neo = test_neo4j()

    print("\n--- SUMMARY ---")
    if ok_llm and ok_emb and ok_neo:
        print("✅ All systems appear reachable.")
    else:
        print("❌ Some systems are unreachable. See details above.")
        print("NOTE: If running in Docker, 'localhost' or private IPs might behave differently.")
