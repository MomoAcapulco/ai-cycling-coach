import asyncio
import unittest
from types import SimpleNamespace

from coach.bluetooth.discovery import FTMS, ZWIFT_RIDE_SERVICE
from tools.trainer_probe import inventory


class ReadOnlyClient:
    """Fails the test on any write, subscription or control request."""
    def __init__(self, services):
        self.services = services
        self.reads = []

    async def read_gatt_char(self, uuid):
        self.reads.append(uuid)
        if uuid == 'deny':
            raise PermissionError('not permitted')
        return {'00002a24-0000-1000-8000-00805f9b34fb': b'KICKR CORE 2\x00',
                '00002a26-0000-1000-8000-00805f9b34fb': b'1.2.3'}.get(uuid, b'\x03\x40')

    async def write_gatt_char(self, *args, **kwargs):
        raise AssertionError('probe must not write')

    async def start_notify(self, *args, **kwargs):
        raise AssertionError('probe must not subscribe')


def char(uuid, *props):
    return SimpleNamespace(uuid=uuid, properties=list(props))


class TrainerProbeTests(unittest.TestCase):
    def test_inventory_reads_only_and_detects_zwift(self):
        client = ReadOnlyClient([
            SimpleNamespace(uuid='0000180A-0000-1000-8000-00805F9B34FB', characteristics=[
                char('00002a24-0000-1000-8000-00805f9b34fb', 'read'),
                char('00002a26-0000-1000-8000-00805f9b34fb', 'read')]),
            SimpleNamespace(uuid=FTMS, characteristics=[
                char('00002acc-0000-1000-8000-00805f9b34fb', 'read'),
                char('00002ad9-0000-1000-8000-00805f9b34fb', 'write', 'indicate'),
                char('deny', 'read')]),
            SimpleNamespace(uuid=ZWIFT_RIDE_SERVICE, characteristics=[
                char('00000003-19ca-4651-86e5-fa29dcdd09d1', 'write-without-response')]),
        ])
        result = asyncio.run(inventory(client))
        self.assertTrue(result['hasZwiftService'])
        self.assertEqual(result['deviceInformation'], {'model': 'KICKR CORE 2', 'firmware': '1.2.3'})
        ftms = next(s for s in result['services'] if s['uuid'] == FTMS)
        self.assertEqual(ftms['name'], 'Fitness Machine (FTMS)')
        self.assertNotIn('00002ad9-0000-1000-8000-00805f9b34fb', client.reads)  # write-only: not touched
        self.assertIn('readError', ftms['characteristics'][2])

    def test_no_zwift_service(self):
        client = ReadOnlyClient([SimpleNamespace(uuid=FTMS, characteristics=[])])
        self.assertFalse(asyncio.run(inventory(client))['hasZwiftService'])


if __name__ == '__main__':
    unittest.main()
