import json
import tempfile
import unittest
from pathlib import Path
from coach.session.diagnostics import RawCapture
from coach.devices.hr50 import parse_heart_rate
from coach.devices.wahoo import parse_cycling_power_measurement, parse_indoor_bike_data

class DiagnosticsTests(unittest.TestCase):
    def test_capture_starts_at_motion_and_stops_at_limit(self):
        with tempfile.TemporaryDirectory() as d:
            now = [0]
            obj = RawCapture(d, seconds=3, clock=lambda: now[0])
            obj.event('heart_rate', b'\x00\x60', {'heartRateBpm':96})
            obj.event('ftms', b'\x00', {'powerWatts':0,'speedKph':0})
            self.assertEqual(list(Path(d).glob('*.jsonl')), [])
            obj.event('ftms', b'\x01\x02', {'powerWatts':80})
            now[0] = 1
            obj.event('heart_rate', b'\x00\x60', {'heartRateBpm':96})
            now[0] = 3
            obj.event('ftms', b'\x03', {'powerWatts':100})
            obj.close()
            logs = list(Path(d).glob('*.jsonl'))
            rows = [json.loads(x) for x in logs[0].read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['hex'], '0102')
    def test_cycling_power(self):
        self.assertEqual(parse_cycling_power_measurement(b'\x00\x00\x7f\x00')['cyclingPowerWatts'], 127)
    def test_more_ftms_fields(self):
        # Speed + cadence + power + avg power + elapsed
        packet = b'\xc4\x08\xcb\x05\x68\x00\x7f\x00\x65\x00\x2d\x00'
        x = parse_indoor_bike_data(packet)
        self.assertEqual(x['powerWatts'],127)
        self.assertEqual(x['averagePowerWatts'],101)
        self.assertEqual(x['machineElapsedSeconds'],45)
    def test_hr_rr(self):
        value = parse_heart_rate(bytes([0x10, 120, 0x00, 0x04]))
        self.assertEqual(value['heartRateBpm'], 120)
        self.assertEqual(value['rrIntervalsMs'], [1000.0])

if __name__=='__main__': unittest.main()
