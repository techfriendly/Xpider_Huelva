import unittest
import config

class TestConfig(unittest.TestCase):
    def test_config_constants(self):
        self.assertIsInstance(config.K_CONTRATOS, int)
        self.assertGreater(config.K_CONTRATOS, 0)
        self.assertTrue(config.NEO4J_URI.startswith("bolt"))

if __name__ == '__main__':
    unittest.main()
