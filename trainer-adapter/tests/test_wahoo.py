import unittest
from unittest.mock import patch
from coach.app.server import ReadingStore, trainer_mode
from coach.devices.wahoo import parse_indoor_bike_data

class TestWahoo(unittest.TestCase):
    def test_speed_cadence_power(self):
        # Flags: cadence + power; speed included because bit0=0
        raw = bytes([0x44, 0x00, 0xCB, 0x05, 0x68, 0x00, 0x7F, 0x00])
        self.assertEqual({k: v for k, v in parse_indoor_bike_data(raw).items() if k != 'ftmsFlags'}, {'speedKph': 14.83, 'cadenceRpm': 52.0, 'powerWatts': 127})

    def test_half_cadence(self):
        raw = bytes([0x45, 0x00, 0x65, 0x00, 0x32, 0x00]) # no instant speed, 50.5 rpm, 50 W
        self.assertEqual(parse_indoor_bike_data(raw)['cadenceRpm'], 50.5)

    def test_truncated(self):
        with self.assertRaises(ValueError):
            parse_indoor_bike_data(b'\x44\x00\x01')

    def test_stale_data_hidden(self):
        store = ReadingStore()
        store.update({'powerWatts': 100, 'cadenceRpm': 80, 'speedKph': 20})
        self.assertTrue(store.snapshot()['connected'])
        store.last_update -= 10
        result = store.snapshot()
        self.assertFalse(result['connected'])
        self.assertEqual(result['powerWatts'], 0)
        self.assertEqual(result['status'], 'STALE')

    def test_mode(self):
        with patch.dict('os.environ', {'TRAINER_MODE': 'WAHOO'}):
            self.assertEqual(trainer_mode(), 'WAHOO')
