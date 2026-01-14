import unittest
from chat_utils.prompt_loader import load_prompt, clear_prompts_cache

class TestPromptLoader(unittest.TestCase):
    def setUp(self):
        clear_prompts_cache()

    def test_load_existing_prompt(self):
        # Assuming 'rag_system' exists as we created it
        prompt = load_prompt("rag_system")
        self.assertIn("respes SOLO con la información del contexto", prompt.replace("Respondes", "respes")) # typo check or substr check logic
        self.assertTrue(len(prompt) > 0)

    def test_load_prompt_with_kwargs(self):
        # intent_router has {today} placeholder
        prompt = load_prompt("intent_router", today="2025-01-01", extracto_types="[]", question="test")
        self.assertIn("2025-01-01", prompt)

    def test_missing_prompt(self):
        with self.assertRaises(FileNotFoundError):
            load_prompt("non_existent_prompt_file_12345")

if __name__ == '__main__':
    unittest.main()
