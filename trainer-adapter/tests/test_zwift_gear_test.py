import asyncio
import unittest

from coach.devices.zwift_hub import (Physical, RIDE_ON_TRAINER, SYNC_RX, TRAINER_HANDSHAKE_2, decode_hub_command,
                                     encode_hub_command, gear_ratio)
from tools.zwift_gear_test import (BASELINE_SECONDS, GuardedWriter, allowed_messages, build_plan, gear_message,
                                   summarise)


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, uuid, data, response):
        self.writes.append((uuid, bytes(data), response))


class GearTestPlanTests(unittest.TestCase):
    def test_plan_order_and_content(self):
        plan = build_plan(80, 9.5)
        self.assertEqual([label for _, label, _ in plan], ['ride_on', 'gear_12', 'gear_13', 'gear_12', 'gear_11', 'gear_12', 'end'])
        self.assertEqual(plan[0][0], BASELINE_SECONDS)                 # nothing written during the baseline
        self.assertEqual(plan[0][2], [RIDE_ON_TRAINER])
        first = [decode_hub_command(m) for m in plan[1][2][:2]]
        self.assertEqual(first[0]['simulation']['inclineX100'], 40)    # 0.4 % before any gear
        self.assertEqual(first[1]['physical'], {'gearRatioX10000': 24000, 'bikeWeightX100': 950, 'riderWeightX100': 8000})
        times = [t for t, _, _ in plan]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(b - a >= 15 for a, b in zip(times[2:], times[3:])))  # >= 15 s between shifts
        self.assertNotIn(TRAINER_HANDSHAKE_2, [m for _, _, ms in plan for m in ms])

    def test_only_gears_11_to_13(self):
        with self.assertRaises(ValueError):
            gear_message(14, 80, 9.5)
        with self.assertRaises(ValueError):
            gear_message(1, 80, 9.5)

    def test_guard(self):
        client = FakeClient()
        writer = GuardedWriter(client, allowed_messages(80, 9.5))
        for _, _, messages in build_plan(80, 9.5):
            for msg in messages:
                asyncio.run(writer.write(SYNC_RX, msg))
        refused = [
            (SYNC_RX, encode_hub_command(physical=Physical.of(gear_ratio(24), 9.5, 80))),  # a hard gear
            (SYNC_RX, encode_hub_command(physical=Physical.of(gear_ratio(12), 9.5, 75))),   # other weight
            (SYNC_RX, encode_hub_command(power_target=300)),                                  # ERG
            (SYNC_RX, TRAINER_HANDSHAKE_2),
            ('00002ad9-0000-1000-8000-00805f9b34fb', RIDE_ON_TRAINER),                         # FTMS control point
            ('8ec90003-f315-4f60-9fb8-838830daea50', b'\x01'),                                 # firmware update
        ]
        for uuid, data in refused:
            with self.subTest(data=data.hex()), self.assertRaises(PermissionError):
                asyncio.run(writer.write(uuid, data))
        self.assertTrue(all(response is False for _, _, response in client.writes))

    def test_summary_finds_the_applied_gear(self):
        segments = [{'t': 0.0, 'label': 'baseline_free_mode'}, {'t': 10.5, 'label': 'gear_12', 'ratioX10000': 24000},
                    {'t': 30.5, 'label': 'gear_13', 'ratioX10000': 26100}]
        riding = [{'t': 5, 'unknown6': 23003}, {'t': 11.5, 'unknown6': 23003}, {'t': 12.4, 'unknown6': 24000},
                  {'t': 31.5, 'unknown6': 26100}]
        ftms = [{'t': 5, 'powerWatts': 100, 'cadenceRpm': 60.0, 'speedKph': 17.0},
                {'t': 20, 'powerWatts': 110, 'cadenceRpm': 60.0, 'speedKph': 17.0},
                {'t': 35, 'powerWatts': 130, 'cadenceRpm': 60.0, 'speedKph': 18.5}]
        s = summarise(segments, riding, ftms)
        self.assertEqual([x['unknown6MatchedAfterSeconds'] for x in s], [None, 1.9, 1.0])
        self.assertEqual([x['ftmsPowerW'] for x in s], [100.0, 110.0, 130.0])
        self.assertEqual(s[1]['unknown6Seen'], [23003, 24000])


if __name__ == '__main__':
    unittest.main()
