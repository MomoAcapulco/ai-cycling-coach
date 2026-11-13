import unittest
from unittest.mock import patch
from server import telemetry, server_config

class TestTrainer(unittest.TestCase):
    def test_telemetry_schema(self):
        t = telemetry(0)
        self.assertEqual(t["source"], "SIMULATOR")
        self.assertEqual(t["powerWatts"], 165)
        self.assertTrue(t["connected"])

    def test_default_port(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(server_config(), ("127.0.0.1", 8766))

    def test_custom_port(self):
        with patch.dict("os.environ", {"TRAINER_HOST": "127.0.0.1", "TRAINER_PORT": "9191"}):
            self.assertEqual(server_config(), ("127.0.0.1", 9191))
