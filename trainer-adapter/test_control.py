import asyncio
import struct
import unittest
from control import simulation_packet, parse_response, simulation_supported, experiment_phase, FtmsController

class ControlTest(unittest.TestCase):
    def test_ramp_sequence(self):
        self.assertEqual(experiment_phase(0), ('BASELINE', None))
        self.assertEqual(experiment_phase(299.9), ('BASELINE', None))
        for t, grade in [(300, 1), (360, 2), (420, 3), (480, 2), (540, 0)]:
            self.assertEqual(experiment_phase(t)[1], grade)
        self.assertEqual(experiment_phase(600), ('FINISHED', None))

    def test_payload(self):
        self.assertEqual(simulation_packet(3.0), struct.pack('<BhhBB', 0x11, 0, 300, 40, 30))
        for val in [-1, 3.1]:
            with self.assertRaises(ValueError):
                simulation_packet(val)

    def test_flags_and_responses(self):
        self.assertFalse(simulation_supported(b'\x00' * 8))
        self.assertTrue(simulation_supported(b'\x00'*4 + (1 << 13).to_bytes(4, 'little')))
        parse_response(bytes.fromhex('80 11 01'), 0x11)
        with self.assertRaises(RuntimeError):
            parse_response(bytes.fromhex('80 11 02'), 0x11)
        with self.assertRaises(ValueError):
            parse_response(bytes.fromhex('80 05 01'), 0x11)

    def test_controller_waits_for_ack(self):
        class FakeClient:
            is_connected = True
            async def start_notify(self, uuid, callback):
                self.callback = callback
            async def write_gatt_char(self, uuid, packet, response):
                self.callback(None, bytes([0x80, packet[0], 1]))
            async def stop_notify(self, uuid):
                pass
        async def scenario():
            c = FtmsController(FakeClient())
            await c.begin()
            await c.request_control()
            await c.grade(2.0)
            await c.finish()
        asyncio.run(scenario())
