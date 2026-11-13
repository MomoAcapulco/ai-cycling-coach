"""The real trainer worker (coach.devices.wahoo.bluetooth_worker) with native shifting, against a fake KICKR."""
import asyncio
import sys
import types
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from coach.app.server import ReadingStore
from coach.devices.gear_shifter import GearShifter, gear_for_ratio
from coach.devices.wahoo import INDOOR_BIKE_DATA
from coach.devices.zwift_controllers import ControllerState
from coach.devices.zwift_hub import ASYNC, OP_HUB_REQUEST, SYNC_RX, SYNC_TX, decode_hub_command
from tests.test_gear_shifter import confirmation

FTMS_75_RPM = bytes([0x44, 0x00, 0xCB, 0x05, 0x96, 0x00, 0x7F, 0x00])  # 14.83 km/h, 75 rpm, 127 W


class FakeKickr:
    """Streams FTMS; answers every HubRequest 520 with the last gear it received, like our KICKR."""
    last = None

    def __init__(self, device, timeout=20):
        FakeKickr.last = self
        chars = [SimpleNamespace(uuid=u) for u in (INDOOR_BIKE_DATA, ASYNC, SYNC_RX, SYNC_TX)]
        self.services = [SimpleNamespace(characteristics=chars)]
        self.callbacks, self.writes, self.is_connected, self.gear = {}, [], True, None

    async def __aenter__(self):
        self.task = asyncio.create_task(self.stream())
        return self

    async def __aexit__(self, *exc):
        self.task.cancel()
        self.is_connected = False

    async def stream(self):
        while True:
            await asyncio.sleep(0.05)
            if INDOOR_BIKE_DATA in self.callbacks:
                self.callbacks[INDOOR_BIKE_DATA](None, FTMS_75_RPM)

    async def start_notify(self, uuid, callback):
        self.callbacks[uuid] = callback

    async def stop_notify(self, uuid):
        self.callbacks.pop(uuid, None)

    async def write_gatt_char(self, uuid, data, response):
        data = bytes(data)
        self.writes.append((uuid, data))
        physical = (decode_hub_command(data) or {}).get('physical')
        if physical:
            self.gear = gear_for_ratio(physical['gearRatioX10000'])
        if data[:1] == bytes([OP_HUB_REQUEST]) and self.gear and SYNC_TX in self.callbacks:
            self.callbacks[SYNC_TX](None, confirmation(self.gear))

    def gears(self):
        return [gear_for_ratio(decode_hub_command(d)['physical']['gearRatioX10000'])
                for _, d in self.writes if 'physical' in (decode_hub_command(d) or {})]


async def found_trainer(*args, **kwargs):
    return SimpleNamespace(device=SimpleNamespace(address='K', name='KICKR CORE 0000'), item=None, source='scan')


class TrainerWorkerShiftingTests(unittest.TestCase):
    def test_buttons_shift_the_trainer_and_exit_returns_to_neutral(self):
        from coach.devices.wahoo import bluetooth_worker
        bleak = types.ModuleType('bleak')
        bleak.BleakClient = FakeKickr
        controllers = ControllerState()
        shifter = GearShifter(controllers, rider_kg=80, bike_kg=9.5)
        store = ReadingStore()
        stop = Event()

        async def scenario():
            task = asyncio.create_task(bluetooth_worker(store, stop, shifter=shifter))
            await asyncio.sleep(0.5)
            first = controllers.snapshot()['trainerGear']
            controllers.simulate_shift(+1)
            controllers.simulate_shift(+1)        # two quick presses: one jump to 14
            await asyncio.sleep(0.6)
            after_up = controllers.snapshot()['trainerGear']
            controllers.simulate_shift(-1)
            await asyncio.sleep(0.6)
            after_down = controllers.snapshot()['trainerGear']
            stop.set()
            await asyncio.wait_for(task, timeout=5)
            return first, after_up, after_down

        with patch.dict(sys.modules, {'bleak': bleak}), patch('coach.devices.wahoo.find_for_role', found_trainer):
            first, after_up, after_down = asyncio.run(scenario())
        self.assertEqual((first, after_up, after_down), (12, 14, 13))
        self.assertEqual(FakeKickr.last.gears(), [12, 14, 13, 12])        # start, jump, down, exit → neutral
        self.assertTrue(all(uuid == SYNC_RX for uuid, _ in FakeKickr.last.writes))
        self.assertEqual(controllers.requested_gear(), 12)

    def test_gears_and_grade_together_and_exit_returns_to_neutral(self):
        from coach.devices.grade_controller import GradeController
        from coach.devices.wahoo import bluetooth_worker
        bleak = types.ModuleType('bleak')
        bleak.BleakClient = FakeKickr
        controllers = ControllerState()
        shifter = GearShifter(controllers, rider_kg=80, bike_kg=9.5)
        grade = GradeController(min_interval_s=0.1, max_rise_per_s=100)  # fast for the test
        store = ReadingStore()
        stop = Event()

        async def scenario():
            task = asyncio.create_task(bluetooth_worker(store, stop, shifter=shifter, grade=grade))
            await asyncio.sleep(0.5)
            nothing_yet = grade.snapshot()['sentGradePercent']
            grade.ride.request(8)                  # effective 4 % once the road gets there
            grade.ride.road_grade = 8              # (the ride ticker is not running in this test)
            controllers.simulate_shift(+1)
            await asyncio.sleep(2.5)
            during = (grade.snapshot()['sentGradePercent'], controllers.snapshot()['trainerGear'])
            stop.set()
            await asyncio.wait_for(task, timeout=5)
            return nothing_yet, during

        with patch.dict(sys.modules, {'bleak': bleak}), patch('coach.devices.wahoo.find_for_role', found_trainer):
            nothing_yet, during = asyncio.run(scenario())
        self.assertEqual(nothing_yet, 0.4)            # only GearShifter's start grade until the rider chooses
        self.assertEqual(during, (4.0, 13))
        writes = [d for _, d in FakeKickr.last.writes]
        grades = [decode_hub_command(d)['simulation']['inclineX100'] for d in writes
                  if 'simulation' in (decode_hub_command(d) or {})]
        self.assertEqual(grades[0], 40)
        self.assertEqual(max(grades), 400)
        self.assertEqual(grades[-1], 40)              # exit: back to 0.4 %
        self.assertEqual(FakeKickr.last.gears()[-1], 12)
        self.assertEqual(grade.snapshot()['gradeStatus'], 'STOPPED')
        self.assertTrue(all(uuid == SYNC_RX for uuid, _ in FakeKickr.last.writes))

    def test_grade_needs_the_shifting_channel(self):
        from coach.devices.grade_controller import GradeController
        from coach.devices.wahoo import bluetooth_worker
        with self.assertRaises(ValueError):
            asyncio.run(bluetooth_worker(ReadingStore(), Event(), grade=GradeController()))

    def test_grade_test_and_shifting_are_exclusive(self):
        from coach.devices.wahoo import bluetooth_worker
        with self.assertRaises(ValueError):
            asyncio.run(bluetooth_worker(ReadingStore(), Event(), control_test=True,
                                         shifter=GearShifter(ControllerState(), 80, 9.5)))


if __name__ == '__main__':
    unittest.main()
