import asyncio
import unittest

from coach.devices.zwift_hub import (Physical, RIDE_ON_TRAINER, SYNC_RX, TRAINER_HANDSHAKE_2, encode_hub_command)
from tools.zwift_hub_probe import GuardedWriter, summarise


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, uuid, data, response):
        self.writes.append((uuid, bytes(data), response))


class GuardedWriterTests(unittest.TestCase):
    def test_only_the_two_handshake_messages_reach_the_trainer(self):
        client = FakeClient()
        writer = GuardedWriter(client)
        asyncio.run(writer.write(SYNC_RX, RIDE_ON_TRAINER))
        asyncio.run(writer.write(SYNC_RX.upper(), TRAINER_HANDSHAKE_2))
        refused = [
            (SYNC_RX, encode_hub_command(physical=Physical.of(2.4, 9.5, 80))),  # a gear: not in step 2
            ('00002ad9-0000-1000-8000-00805f9b34fb', b'\x00'),                 # FTMS control point
            ('8ec90003-f315-4f60-9fb8-838830daea50', b'\x01'),                 # Nordic DFU (firmware update)
            ('00002ad9-0000-1000-8000-00805f9b34fb', RIDE_ON_TRAINER),         # right bytes, wrong place
        ]
        for uuid, data in refused:
            with self.subTest(uuid=uuid), self.assertRaises(PermissionError):
                asyncio.run(writer.write(uuid, data))
        self.assertEqual([w[1] for w in client.writes], [RIDE_ON_TRAINER, TRAINER_HANDSHAKE_2])
        self.assertTrue(all(w[2] is False for w in client.writes))  # write without response, as the protocol uses

    def test_summary(self):
        events = [{'t': 0.4, 'decoded': {'type': 'RideOn'}},
                  {'t': 1.2, 'decoded': {'type': 'RidingData', 'powerWatts': 100, 'cadenceRpm': 70, 'speedKph': 20.0}},
                  {'t': 2.2, 'decoded': {'type': 'RidingData', 'powerWatts': 120, 'cadenceRpm': 74, 'speedKph': 22.0}}]
        ftms = [{'t': 1.0, 'parsed': {'powerWatts': 110, 'cadenceRpm': 72.0, 'speedKph': 21.0}}]
        s = summarise(events, ftms)
        self.assertEqual((s['ridingDataCount'], s['firstRidingDataAfterSeconds']), (2, 1.2))
        self.assertEqual(s['zwiftMean'], {'powerWatts': 110.0, 'cadenceRpm': 72.0, 'speedKph': 21.0})
        self.assertEqual(s['zwiftMessagesByType'], {'RideOn': 1, 'RidingData': 2})


if __name__ == '__main__':
    unittest.main()
