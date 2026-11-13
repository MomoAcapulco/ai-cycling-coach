import asyncio
import unittest

from coach.devices.gear_shifter import GearShifter, SafeZwiftWriter, check_outgoing, gear_for_ratio
from coach.devices.zwift_controllers import ControllerState
from coach.devices.zwift_hub import (RIDE_ON_TRAINER, SYNC_RX, Physical, Simulation, decode_hub_command,
                                     encode_hub_command, encode_hub_request, gear_ratio)

LIVE = {'connected': True, 'cadenceRpm': 75}
STOPPED = {'connected': True, 'cadenceRpm': 0}
STALE = {'connected': False, 'cadenceRpm': 0}


def confirmation(gear):
    """The trainer's 0x3C answer to HubRequest 520, as recorded on our KICKR."""
    from coach.devices.zwift_hub import encode_varint
    ratio = encode_varint(round(gear_ratio(gear) * 10000))
    inner = bytes([0x40]) + ratio                       # field 8: ratio
    level1 = bytes([0x0A, len(inner)]) + inner          # field 1: {8: ratio}
    return bytes([0x3C, 0x08, 0x88, 0x04, 0x12, len(level1)]) + level1


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, uuid, data, response):
        self.writes.append(bytes(data))


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def gears_sent(writes):
    out = []
    for w in writes:
        cmd = decode_hub_command(w) or {}
        if 'physical' in cmd:
            out.append(gear_for_ratio(cmd['physical']['gearRatioX10000']))
    return out


class ShifterTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.controllers = ControllerState()
        self.client = FakeClient()
        self.writer = SafeZwiftWriter(self.client)
        self.shifter = GearShifter(self.controllers, rider_kg=80, bike_kg=9.5, clock=self.clock)
        self.controllers.last_request = 0.0

    def run_(self, coroutine):
        return asyncio.run(coroutine)

    def tick(self, trainer=LIVE, advance=0.25):
        self.clock.now += advance
        self.run_(self.shifter.tick(self.writer, trainer))

    def press(self, delta, times=1):
        for _ in range(times):
            self.controllers.simulate_shift(delta)
            self.controllers.last_request = self.clock.now

    def test_ratio_to_gear(self):
        self.assertEqual(gear_for_ratio(24000), 12)
        self.assertEqual(gear_for_ratio(26099), 13)  # the trainer's rounding
        self.assertIsNone(gear_for_ratio(25000))

    def test_start_sends_rideon_incline_gear_and_request(self):
        self.run_(self.shifter.start(self.writer))
        self.assertEqual(self.client.writes[0], RIDE_ON_TRAINER)
        self.assertEqual(decode_hub_command(self.client.writes[1])['simulation']['inclineX100'], 40)
        self.assertEqual(decode_hub_command(self.client.writes[2])['physical'],
                         {'gearRatioX10000': 24000, 'bikeWeightX100': 950, 'riderWeightX100': 8000})
        self.assertEqual(self.client.writes[3], encode_hub_request(520))
        self.assertEqual(self.shifter.status, 'WAITING_CONFIRMATION')
        self.shifter.on_message(confirmation(12))
        self.assertEqual((self.shifter.status, self.shifter.confirmed_gear), ('READY', 12))

    def test_quick_presses_become_one_jump(self):
        self.run_(self.shifter.start(self.writer))
        self.shifter.on_message(confirmation(12))
        self.client.writes.clear()
        self.press(+1, times=3)
        self.tick(advance=0.02)          # still inside the 80 ms window: nothing sent
        self.assertEqual(gears_sent(self.client.writes), [])
        self.tick(advance=0.1)
        self.assertEqual(gears_sent(self.client.writes), [15])

    def test_ui_shows_only_the_confirmed_gear(self):
        self.run_(self.shifter.start(self.writer))
        self.shifter.on_message(confirmation(12))
        self.press(+1)
        self.tick()
        snap = self.controllers.snapshot()
        self.assertEqual((snap['gearControlMode'], snap['trainerGear'], snap['requestedGear'], snap['gearStatus']),
                         ('TRAINER', 12, 13, 'WAITING_CONFIRMATION'))
        self.shifter.on_message(confirmation(13))
        self.assertEqual(self.controllers.snapshot()['trainerGear'], 13)

    def test_unconfirmed_gear_is_retried_then_reported(self):
        self.run_(self.shifter.start(self.writer))
        self.shifter.on_message(confirmation(12))
        self.press(+1)
        self.tick()
        for _ in range(3):
            self.tick(advance=1.1)
        self.assertEqual(gears_sent(self.client.writes)[-4:], [13, 13, 13, 13])  # first + 3 retries
        self.tick(advance=1.1)
        self.assertEqual(self.shifter.status, 'UNCONFIRMED')
        self.assertEqual(self.controllers.requested_gear(), 12)  # back to what the trainer really has

    def test_never_harder_without_pedalling_or_live_data(self):
        self.run_(self.shifter.start(self.writer))
        self.shifter.on_message(confirmation(12))
        self.client.writes.clear()
        for trainer in (STOPPED, STALE):
            with self.subTest(trainer=trainer):
                self.press(+1)
                self.tick(trainer)
                self.assertEqual(gears_sent(self.client.writes), [])
                self.assertEqual(self.controllers.requested_gear(), 12)
                self.assertIn('harder refused', self.shifter.last_refusal)

    def test_easier_is_allowed_when_stopped(self):
        self.run_(self.shifter.start(self.writer))
        self.shifter.on_message(confirmation(12))
        self.client.writes.clear()
        self.press(-1, times=2)
        self.tick(STOPPED)
        self.assertEqual(gears_sent(self.client.writes), [10])

    def test_full_zwift_range_is_clamped_to_1_and_24(self):
        self.controllers.force_gear(24)
        self.press(+1)
        self.assertEqual(self.controllers.requested_gear(), 24)
        self.controllers.force_gear(1)
        self.press(-1)
        self.assertEqual(self.controllers.requested_gear(), 1)

    def test_finish_leaves_gear_12(self):
        self.controllers.force_gear(18)
        self.run_(self.shifter.finish(self.writer))
        self.assertEqual(gears_sent(self.client.writes), [12])
        self.assertEqual(self.controllers.requested_gear(), 12)

    def test_reconnect_restores_the_rider_gear(self):
        self.run_(self.shifter.start(self.writer))
        self.shifter.on_message(confirmation(12))
        self.press(+1, times=4)
        self.tick(advance=0.2)
        self.shifter.on_message(confirmation(16))
        self.shifter.disconnected()
        self.client.writes.clear()
        self.run_(self.shifter.start(self.writer))
        self.assertEqual(gears_sent(self.client.writes), [16])


class OutgoingGuardTests(unittest.TestCase):
    def test_allowed(self):
        for data in (RIDE_ON_TRAINER, encode_hub_request(520),
                     encode_hub_command(simulation=Simulation(incline_x100=40)),
                     encode_hub_command(physical=Physical.of(gear_ratio(24), 9.5, 80))):
            check_outgoing(SYNC_RX, data)

    def test_refused(self):
        cases = [
            (SYNC_RX, encode_hub_command(power_target=250)),                     # ERG
            (SYNC_RX, encode_hub_command(simulation=Simulation(incline_x100=800))),  # a grade: not shifting
            (SYNC_RX, encode_hub_command(physical=Physical(25000, 950, 8000))),  # not a Zwift gear
            (SYNC_RX, bytes([0x41, 0x08, 0x05])),
            ('00002ad9-0000-1000-8000-00805f9b34fb', b'\x00'),                    # FTMS control point
            ('8ec90003-f315-4f60-9fb8-838830daea50', b'\x01'),                    # firmware update
        ]
        for uuid, data in cases:
            with self.subTest(data=data.hex()), self.assertRaises(PermissionError):
                check_outgoing(uuid, data)


if __name__ == '__main__':
    unittest.main()
