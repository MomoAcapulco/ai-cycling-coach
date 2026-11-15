"""Bike type (road / mountain bike): virtual road physics and the rolling resistance the trainer gets."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from coach.app.rider_profile import ProfileStore, RiderProfile
from coach.devices.gear_shifter import GearShifter, SafeZwiftWriter, check_outgoing
from coach.devices.grade_controller import GradeController, GradePrefs
from coach.devices.zwift_controllers import ControllerState
from coach.devices.zwift_hub import SYNC_RX, Simulation, decode_hub_command, encode_hub_command
from coach.session.virtual_ride import BIKE_PHYSICS, VirtualRide
from tests.test_grade_controller import FakeClient, LIVE

MASS = 80 + 9.5


def crrs(writes):
    return {decode_hub_command(w)['simulation']['crrX100000'] for w in writes
            if 'simulation' in (decode_hub_command(w) or {})}


class ProfileTests(unittest.TestCase):
    def test_default_and_validation(self):
        self.assertEqual(RiderProfile().bike_type, 'ROAD')
        self.assertEqual(RiderProfile().updated({'bikeType': 'MTB'}).to_json()['bikeType'], 'MTB')
        for bad in ('mtb', 'GRAVEL', None, 3):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                RiderProfile().updated({'bikeType': bad})

    def test_old_profile_files_stay_road(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profile.json'
            path.write_text('{"profile": {"riderWeightKg": 80, "bikeWeightKg": 9.5}}')
            profile, saved = ProfileStore(path).load()
            self.assertEqual((saved, profile.bike_type), (True, 'ROAD'))


class PhysicsTests(unittest.TestCase):
    def test_mountain_bike_is_slower_on_the_flat_almost_the_same_climbing(self):
        flat_road = VirtualRide.steady_speed_ms(200, 0, MASS, 'ROAD') * 3.6
        flat_mtb = VirtualRide.steady_speed_ms(200, 0, MASS, 'MTB') * 3.6
        climb_road = VirtualRide.steady_speed_ms(200, 8, MASS, 'ROAD') * 3.6
        climb_mtb = VirtualRide.steady_speed_ms(200, 8, MASS, 'MTB') * 3.6
        self.assertLess(flat_mtb, flat_road * 0.85)                  # air and dirt cost a lot on the flat
        self.assertGreater(climb_mtb, climb_road * 0.9)              # gravity dominates a climb
        self.assertLess(climb_mtb, climb_road)

    def test_the_ride_uses_and_changes_the_bike_type(self):
        ride = VirtualRide(80, 9.5, bike_type='MTB')
        self.assertEqual((ride.cda, ride.crr), BIKE_PHYSICS['MTB'])
        for _ in range(800):
            ride.step(0.25, 200)
        mtb_speed = ride.speed_ms
        ride.set_profile(80, 9.5, 20, 'ROAD')
        for _ in range(800):
            ride.step(0.25, 200)
        self.assertGreater(ride.speed_ms, mtb_speed * 1.1)
        self.assertEqual(ride.snapshot()['bikeType'], 'ROAD')


class TrainerTests(unittest.TestCase):
    def test_guard_allows_only_the_bike_type_values(self):
        for crr in (400, 1000):
            check_outgoing(SYNC_RX, encode_hub_command(simulation=Simulation(incline_x100=40, crr_x100000=crr)))
        for crr in (0, 700, 2000):
            with self.subTest(crr=crr), self.assertRaises(PermissionError):
                check_outgoing(SYNC_RX, encode_hub_command(simulation=Simulation(incline_x100=40, crr_x100000=crr)))

    def test_shifter_start_and_finish_send_the_bike_type_crr(self):
        client = FakeClient()
        shifter = GearShifter(ControllerState(), 80, 9.5, crr_x100000=1000)
        writer = SafeZwiftWriter(client)
        asyncio.run(shifter.start(writer))
        asyncio.run(shifter.finish(writer))
        self.assertEqual(crrs(client.writes), {1000})

    def test_grades_carry_the_bike_type_crr(self):
        prefs = GradePrefs.from_profile(RiderProfile(bike_type='MTB'))
        self.assertEqual(prefs.crr_x100000, 1000)
        self.assertEqual(GradePrefs.from_profile(RiderProfile()).crr_x100000, 400)
        clock = type('C', (), {'t': 100.0, '__call__': lambda self: self.t})()
        ride = VirtualRide(80, 9.5, bike_type='MTB')
        grade = GradeController(prefs, ride=ride, clock=clock)
        client = FakeClient()
        writer = SafeZwiftWriter(client, incline_limits=grade.limits_x100)
        grade.start()
        ride.request(4)
        ride.road_grade = 4
        for _ in range(40):
            clock.t += 0.25
            asyncio.run(grade.tick(writer, LIVE))
        self.assertEqual(crrs(client.writes), {1000})


class RuntimeTests(unittest.TestCase):
    def test_runtime_and_profile_change(self):
        import json
        from threading import Thread
        from urllib.request import Request, urlopen
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder) / 'profile.json')
            store.update({'bikeType': 'MTB'})
            runtime = AdapterRuntime(EnvConfig(record_dir=Path(folder), routes_dir=Path(folder) / 'r'),
                                     Settings(mode='WAHOO', gear_control_enabled=True), start_workers=False,
                                     profile_store=store).start()
            httpd = make_server('127.0.0.1', 0, runtime)
            Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                self.assertEqual((runtime.state.ride.bike_type, runtime.state.grade.prefs.crr_x100000), ('MTB', 1000))
                body = json.dumps({'bikeType': 'ROAD'}).encode()
                urlopen(Request(f'http://127.0.0.1:{httpd.server_address[1]}/admin/profile', data=body, method='POST',
                                headers={'Content-Type': 'application/json'}), timeout=5).read()
                self.assertEqual((runtime.state.ride.bike_type, runtime.state.grade.prefs.crr_x100000), ('ROAD', 400))
            finally:
                runtime.shutdown()
                httpd.shutdown()
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
