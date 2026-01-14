import unittest
from services.intent_router import detect_intent

class TestIntentRouter(unittest.TestCase):
    def test_greeting_regex(self):
        # Should return greeting intent directly without LLM
        res = detect_intent("Hola")
        self.assertTrue(res.get("is_greeting"))
        self.assertEqual(res["intent"], "RAG_QA")

    def test_cypher_regex(self):
        # Should detect cypher/aggregation intent via regex
        res = detect_intent("Cuántos contratos ha ganado Techfriendly")
        self.assertEqual(res["intent"], "CYPHER_QA")
        self.assertEqual(res["focus"], "EMPRESA")
        # simple check if regex captured the entity
        # Note: detect_intent might call LLM if regex fails or is partial, 
        # but _RE_CUANTOS_CONTRATOS is strong. 
        # However, detect_intent implementation calls LLM if it falls through.
        # Let's hope the environment has access or we mock it.
        # Actually, without mocking llm_client, this test relies on the regex taking precedence 
        # BEFORE the LLM call. In the code, if regex matches, it returns immediately.
        self.assertEqual(res["empresa_query"], "Techfriendly")

if __name__ == '__main__':
    unittest.main()
