"""Step 5 grade test: the plan, its guard and a whole run against a fake trainer with the timings shrunk."""
import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import tools.zwift_grade_test as gr
from coach.bluetooth.discovery import FTMS, Advert
from coach.devices.gear_shifter import gear_for_ratio
from coach.devices.wahoo import INDOOR_BIKE_DATA
from coach.devices.zwift_hub import (ASYNC, OP_HUB_REQUEST, RIDE_ON_TRAINER, SYNC_RX, SYNC_TX, Physical,
                                     Simulation, decode_fields, decode_hub_command, encode_hub_command,
                                     encode_hub_request, gear_ratio)
from tests.test_gear_shifter import confirmation
from tools.zwift_gear_test import GuardedWriter

FTMS_60_RPM = bytes([0x44, 0x00, 0xCB, 0x05, 0x78, 0x00, 0x7F, 0x00])  # 14.83 km/h, 60 rpm, 127 W
FTMS_30_RPM = bytes([0x44, 0x00, 0xCB, 0x05, 0x3C, 0x00, 0x7F, 0x00])  # 30 rpm
FAST = dict(BASELINE_SECONDS=0.3, NEUTRAL_HOLD_SECONDS=0.3, STEP_SECONDS=0.3, SHORT_STEP_SECONDS=0.3,
            FINAL_HOLD_SECONDS=0.3, STALE_SECONDS=0.5)


def inclines(writes):
    return [decode_hub_command(w)['simulation']['inclineX100'] for w in writes
            if 'simulation' in (decode_hub_command(w) or {})]


def gears(writes):
    return [gear_for_ratio(decode_hub_command(w)['physical']['gearRatioX10000']) for w in writes
            if 'physical' in (decode_hub_command(w) or {})]


class FakeTrainer:
    """Streams FTMS every 50 ms; answers 520 with the last gear and 512 with an opaque message."""
    instances = []
    packet = FTMS_60_RPM
    silent_after = None

    def __init__(self, address, timeout):
        self.writes, self.callbacks, self.is_connected, self.gear = [], {}, True, None
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
                self.callbacks[INDOOR_BIKE_DATA](None, self.packet)

    async def start_notify(self, uuid, callback):
        self.callbacks[uuid] = callback

    async def stop_notify(self, uuid):
        self.callbacks.pop(uuid, None)

    async def write_gatt_char(self, uuid, data, response):
        data = bytes(data)
        self.writes.append(data)
        physical = (decode_hub_command(data) or {}).get('physical')
        if physical:
            self.gear = gear_for_ratio(physical['gearRatioX10000'])
        if data[:1] == bytes([OP_HUB_REQUEST]) and SYNC_TX in self.callbacks:
            data_id = decode_fields(data[1:])[0][2]
            if data_id == 520 and self.gear:
                self.callbacks[SYNC_TX](None, confirmation(self.gear))
            elif data_id == 512:
                self.callbacks[SYNC_TX](None, bytes([0x3C, 0x08, 0x80, 0x04, 0x12, 0x02, 0x08, 0x01]))


async def fake_scan(_seconds, scan_lock=None):
    return {'K': Advert(address='K', name='KICKR CORE 0000', service_uuids=(FTMS,))}


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = gr.build_plan(80, 9.5)

    def test_order_and_timing(self):
        labels = [label for _, label, _, _ in self.plan]
        self.assertEqual(labels, ['ride_on', 'start_0.4_gear_12', 'grade_1.0', 'grade_1.5', 'gear_12_at_1.5',
                                  'grade_1.0_down', 'grade_0.4', 'grade_0.0', 'gear_13_at_0.0', 'gear_12_at_0.0',
                                  'grade_0.4_end', 'end'])
        times = [t for t, *_ in self.plan]
        self.assertEqual(times[0], gr.BASELINE_SECONDS)              # nothing written in the baseline
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))
        grade_steps = [i for i, (_, label, _, _) in enumerate(self.plan) if label in ('grade_1.0', 'grade_1.0_down', 'grade_0.4')]
        for i in grade_steps:                                        # the main grade steps last >= 20 s
            self.assertGreaterEqual(times[i + 1] - times[i], 20)
        self.assertLess(times[-1], 200)

    def test_gentle_ramp_only(self):
        sent = [x for _, _, msgs, _ in self.plan for x in inclines(msgs)]
        self.assertEqual(sent, [40, 100, 150, 100, 40, 0, 40])
        self.assertLessEqual(max(sent), 150)                         # never above 1.5 %
        steps = [abs(b - a) for a, b in zip(sent, sent[1:])]
        self.assertLessEqual(max(steps), 60)                         # never more than 0.6 % at once
        self.assertEqual(sorted({g for _, _, msgs, _ in self.plan for g in gears(msgs)}), [12, 13])

    def test_no_unsupported_handshake_and_requests(self):
        messages = [m for _, _, msgs, _ in self.plan for m in msgs]
        self.assertNotIn(bytes([0x41, 0x08, 0x05]), messages)
        self.assertEqual(messages[0], RIDE_ON_TRAINER)
        for _, label, msgs, step in self.plan:
            if step.get('inclineX100') is not None:
                self.assertIn(encode_hub_request(512), msgs, label)  # look for a grade answer
            if step.get('gear') is not None:
                self.assertIn(encode_hub_request(520), msgs, label)  # gear confirmation

    def test_grade_message_refuses_anything_outside_the_test(self):
        for x100 in (-10, 151, 200, 800):
            with self.subTest(x100=x100), self.assertRaises(ValueError):
                gr.grade_message(x100)


class GuardTests(unittest.TestCase):
    def test_guard_refuses_everything_outside_the_plan(self):
        written = []

        class Client:
            async def write_gatt_char(self, uuid, data, response):
                written.append(data)
        writer = GuardedWriter(Client(), gr.allowed_messages(80, 9.5))
        refused = [
            (SYNC_RX, encode_hub_command(power_target=150)),                                 # ERG
            (SYNC_RX, encode_hub_command(simulation=Simulation(incline_x100=200))),         # 2 %: not in the plan
            (SYNC_RX, encode_hub_command(simulation=Simulation(incline_x100=-100))),
            (SYNC_RX, encode_hub_command(simulation=Simulation(incline_x100=100, wind_x100=200))),
            (SYNC_RX, encode_hub_command(physical=Physical.of(gear_ratio(20), 9.5, 80))),  # gear 20
            (SYNC_RX, bytes([0x41, 0x08, 0x05])),
            ('00002ad9-0000-1000-8000-00805f9b34fb', encode_hub_command(simulation=Simulation(incline_x100=100))),
            ('8ec90003-f315-4f60-9fb8-838830daea50', b'\x01'),
            (ASYNC, encode_hub_command(simulation=Simulation(incline_x100=100))),
        ]
        for uuid, data in refused:
            with self.subTest(data=data.hex()), self.assertRaises(PermissionError):
                asyncio.run(writer.write(uuid, data))
        self.assertEqual(written, [])
        asyncio.run(writer.write(SYNC_RX, gr.grade_message(150)))   # in the plan: allowed
        self.assertEqual(len(written), 1)


class GradeTestRunTests(unittest.TestCase):
    def run_test(self, silent_after=None, packet=FTMS_60_RPM):
        FakeTrainer.instances.clear()
        bleak = types.ModuleType('bleak')

        class Client(FakeTrainer):
            pass
        Client.silent_after, Client.packet = silent_after, packet
        bleak.BleakClient = Client
        with patch.dict(sys.modules, {'bleak': bleak}), patch.multiple(gr, **FAST), \
                patch('coach.bluetooth.discovery.scan', fake_scan):
            result = asyncio.run(gr.run(80, 9.5))
        return result, FakeTrainer.instances[0].writes

    def test_full_run_sends_the_plan_and_ends_in_neutral(self):
        result, writes = self.run_test()
        with patch.multiple(gr, **FAST):
            planned = [m for _, _, ms, _ in gr.build_plan(80, 9.5) for m in ms]
        self.assertEqual(writes[:len(planned)], planned)
        self.assertEqual(inclines(writes), [40, 100, 150, 100, 40, 0, 40, 40])   # last one: the restore
        self.assertEqual(gears(writes)[-1], 12)
        self.assertIn('left in gear 12 at 0.4 %', result['notes'])
        self.assertEqual([s['label'] for s in result['segments']],
                         ['baseline_free_mode', 'ride_on', 'start_0.4_gear_12', 'grade_1.0', 'grade_1.5',
                          'gear_12_at_1.5', 'grade_1.0_down', 'grade_0.4', 'grade_0.0', 'gear_13_at_0.0',
                          'gear_12_at_0.0', 'grade_0.4_end'])
        self.assertTrue(result['findings']['gearsConfirmedAtZeroGrade'])
        self.assertGreaterEqual(result['findings']['answersTo512Count'], 7)
        by_label = {s['label']: s for s in result['segments']}
        self.assertEqual(by_label['grade_1.5']['sentInclinePercent'], 1.5)
        self.assertEqual(by_label['gear_13_at_0.0']['gearConfirmedRatioX10000'], 26100)

    def test_low_cadence_skips_every_harder_step(self):
        result, writes = self.run_test(packet=FTMS_30_RPM)
        # every step harder than where the trainer is gets skipped; easier ones and the final restore are sent
        self.assertEqual(inclines(writes), [40, 40, 0, 40])
        self.assertNotIn(13, gears(writes))
        skipped = {s['label'] for s in result['segments'] if s.get('skipped')}
        self.assertEqual(skipped, {'grade_1.0', 'grade_1.5', 'grade_1.0_down', 'gear_13_at_0.0', 'grade_0.4_end'})
        self.assertIsNone(result['findings']['gearsConfirmedAtZeroGrade'])

    def test_lost_telemetry_aborts_and_restores_neutral(self):
        result, writes = self.run_test(silent_after=1.0)
        self.assertTrue(any(n.startswith('aborted: RuntimeError: FTMS telemetry stale') for n in result['notes']))
        self.assertEqual(inclines(writes)[-1], 40)
        self.assertEqual(gears(writes)[-1], 12)
        self.assertIn('left in gear 12 at 0.4 %', result['notes'])

    def test_no_telemetry_at_all_never_writes_anything(self):
        result, writes = self.run_test(silent_after=0)
        self.assertTrue(any('no FTMS telemetry at all' in n for n in result['notes']))
        self.assertEqual(writes, [])


if __name__ == '__main__':
    unittest.main()
