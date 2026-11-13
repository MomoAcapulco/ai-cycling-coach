import unittest
from coach.devices.hr50 import parse_heart_rate
from coach.app.server import HeartRateStore

class TestHeartRate(unittest.TestCase):
    def test_uint8(self):
        self.assertEqual(parse_heart_rate(bytes([0, 137])), {'heartRateBpm': 137, 'heartRateFlags': 0})

    def test_uint16(self):
        self.assertEqual(parse_heart_rate(bytes([1, 0x2c, 0x01])), {'heartRateBpm': 300, 'heartRateFlags': 1})

    def test_short(self):
        with self.assertRaises(ValueError):
            parse_heart_rate(bytes([1, 0x2c]))

    def test_staleness(self):
        h = HeartRateStore()
        h.update({'heartRateBpm': 140})
        self.assertEqual(h.snapshot()['heartRateBpm'], 140)
        h.last_update -= 10
        self.assertIsNone(h.snapshot()['heartRateBpm'])
        self.assertEqual(h.snapshot()['heartRateStatus'], 'STALE')
