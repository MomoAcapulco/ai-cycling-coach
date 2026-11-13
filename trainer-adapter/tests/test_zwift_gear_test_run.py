"""Whole gear test against a fake trainer, with the timings shrunk."""
import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import tools.zwift_gear_test as gt
from coach.bluetooth.discovery import FTMS, Advert
from coach.devices.wahoo import INDOOR_BIKE_DATA
from coach.devices.zwift_hub import ASYNC, SYNC_RX, SYNC_TX, decode_hub_command

FTMS_PACKET = bytes([0x44, 0x00, 0xCB, 0x05, 0x78, 0x00, 0x7F, 0x00])  # 14.83 km/h, 60 rpm, 127 W


class FakeTrainer:
    """Async-context BLE client: streams FTMS every 50 ms until told to go silent."""
    instances = []

    def __init__(self, address, timeout):
        self.writes, self.callbacks, self.is_connected, self.silent_after = [], {}, True, None
        chars = [SimpleNamespace(uuid=u) for u in (INDOOR_BIKE_DATA, ASYNC, SYNC_RX, SYNC_TX)]
        self.services = [SimpleNamespace(characteristics=chars)]
        FakeTrainer.instances.append(self)

    async def __aenter__(self):
        self.task = asyncio.create_task(self.stream())
        return self

    async def __aexit__(self, *exc):
        self.task.cancel()
        self.is_connected = False

    async def stream(self):
        t = 0.0
        while True:
            await asyncio.sleep(0.05)
            t += 0.05
            if self.silent_after is not None and t > self.silent_after:
                continue
            if INDOOR_BIKE_DATA in self.callbacks:
                self.callbacks[INDOOR_BIKE_DATA](None, FTMS_PACKET)

    async def start_notify(self, uuid, callback):
        self.callbacks[uuid] = callback

    async def stop_notify(self, uuid):
        self.callbacks.pop(uuid, None)

    async def write_gatt_char(self, uuid, data, response):
        self.writes.append(bytes(data))


async def fake_scan(_seconds, scan_lock=None):
    return {'K': Advert(address='K', name='KICKR CORE 0000', service_uuids=(FTMS,))}


class GearTestRunTests(unittest.TestCase):
    def run_test(self, silent_after=None):
        FakeTrainer.instances.clear()
        bleak = types.ModuleType('bleak')

        class Client(FakeTrainer):
            def __init__(self, address, timeout):
                super().__init__(address, timeout)
                self.silent_after = silent_after
        bleak.BleakClient = Client
        fast = dict(BASELINE_SECONDS=0.3, NEUTRAL_HOLD_SECONDS=0.3, STEP_SECONDS=0.3, STALE_SECONDS=0.5)
        with patch.dict(sys.modules, {'bleak': bleak}), patch.multiple(gt, **fast), \
                patch('coach.bluetooth.discovery.scan', fake_scan):
            result = asyncio.run(gt.run(80, 9.5))
        return result, FakeTrainer.instances[0].writes

    def test_full_run_sends_the_plan_and_ends_in_neutral(self):
        result, writes = self.run_test()
        planned = [m for _, _, ms in gt.build_plan(80, 9.5) for m in ms]
        self.assertEqual(writes[:len(planned)], planned)
        gears = [decode_hub_command(w)['physical']['gearRatioX10000'] for w in writes
                 if w[:1] == b'\x04' and 'physical' in (decode_hub_command(w) or {})]
        self.assertEqual(gears, [24000, 26100, 24000, 22200, 24000, 24000])  # last one: the restore
        self.assertIn('left in gear 12 at 0.4 %', result['notes'])
        self.assertEqual([s['label'] for s in result['segments']],
                         ['baseline_free_mode', 'ride_on', 'gear_12', 'gear_13', 'gear_12', 'gear_11', 'gear_12'])

    def test_lost_telemetry_aborts_and_restores_neutral(self):
        result, writes = self.run_test(silent_after=1.0)
        self.assertTrue(any(n.startswith('aborted: RuntimeError: FTMS telemetry stale') for n in result['notes']))
        last_gear = decode_hub_command(writes[-1])['physical']['gearRatioX10000']
        self.assertEqual(last_gear, 24000)
        self.assertIn('left in gear 12 at 0.4 %', result['notes'])


    def test_no_telemetry_at_all_never_sends_a_gear(self):
        result, writes = self.run_test(silent_after=0)
        self.assertTrue(any('no FTMS telemetry at all' in n for n in result['notes']))
        self.assertEqual(writes, [])  # aborted during the baseline: nothing was ever written


if __name__ == '__main__':
    unittest.main()
