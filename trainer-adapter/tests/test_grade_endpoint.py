"""POST /grade and the grade fields of /telemetry, through HTTP."""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.app.rider_profile import ProfileStore
from coach.app.runtime import AdapterRuntime, EnvConfig
from coach.app.server import AdapterState, make_server
from coach.app.settings import Settings
from coach.devices.grade_controller import GradeController, GradePrefs
from coach.session.session import SESSION_FIELDS
from coach.session.virtual_ride import VirtualRide


class Server:
    def __init__(self, runtime):
        self.httpd = make_server('127.0.0.1', 0, runtime)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        Thread(target=self.httpd.serve_forever, daemon=True).start()

    def call(self, method, path, body=None):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        request = Request(self.base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as r:
            return r.status, json.loads(r.read())

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class GradeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.ride = VirtualRide(80, 9.5)
        self.grade = GradeController(GradePrefs(), ride=self.ride)
        self.server = Server(AdapterState(mode='WAHOO', grade=self.grade, ride=self.ride))

    def tearDown(self):
        self.server.close()

    def test_rider_sets_the_grade(self):
        status, body = self.server.call('POST', '/grade', {'gradePercent': 6})
        self.assertEqual((status, body), (200, {'targetGradePercent': 6.0}))
        self.ride.road_grade = 6.0                   # (the ride ticker is not running in this test)
        telemetry = self.server.call('GET', '/telemetry')[1]
        self.assertEqual((telemetry['targetGradePercent'], telemetry['roadGradePercent'],
                          telemetry['effectiveGradePercent'], telemetry['gradeControlMode']), (6.0, 6.0, 3.0, 'TRAINER'))
        for key in ('rideSpeedKph', 'rideDistanceKm', 'altitudeM', 'elevationGainM', 'vamMh'):
            self.assertIn(key, telemetry)

    def test_bad_values_are_400(self):
        for body in ({'gradePercent': 'x'}, {'gradePercent': 30}, {'gradePercent': None}, {}, b'[1]', b'{oops'):
            with self.subTest(body=body), self.assertRaises(HTTPError) as ctx:
                self.server.call('POST', '/grade', body)
            self.assertEqual(ctx.exception.code, 400)
        self.assertIsNone(self.ride.target_grade)

    def test_session_csv_has_the_grade_columns(self):
        for column in ('targetGradePercent', 'effectiveGradePercent', 'sentGradePercent', 'gradeStatus',
                       'roadGradePercent', 'rideSpeedKph', 'rideDistanceKm', 'altitudeM', 'elevationGainM'):
            self.assertIn(column, SESSION_FIELDS)


class NoGradeControlTests(unittest.TestCase):
    def test_409_without_native_control(self):
        # WAHOO with the virtual road but no gear control: climbing it would not be felt on the trainer
        for state in (AdapterState(mode='SIMULATOR'), AdapterState(mode='WAHOO'),
                      AdapterState(mode='WAHOO', ride=VirtualRide())):
            mode = state.mode
            server = Server(state)
            try:
                with self.subTest(mode=mode), self.assertRaises(HTTPError) as ctx:
                    server.call('POST', '/grade', {'gradePercent': 2})
                self.assertEqual(ctx.exception.code, 409)
            finally:
                server.close()


class SimulatorGradeTests(unittest.TestCase):
    def test_simulator_moves_the_virtual_road(self):
        ride = VirtualRide()
        server = Server(AdapterState(mode='SIMULATOR', ride=ride))
        try:
            self.assertEqual(server.call('POST', '/grade', {'gradePercent': 4})[1], {'targetGradePercent': 4.0})
            telemetry = server.call('GET', '/telemetry')[1]
            self.assertEqual((telemetry['gradeControlMode'], telemetry['targetGradePercent']), ('SIMULATED', 4.0))
            self.assertIsNotNone(telemetry['wattsPerKg'])
        finally:
            server.close()


class ProfileUpdatesGradeTests(unittest.TestCase):
    def test_saving_the_profile_changes_the_running_controller(self):
        with tempfile.TemporaryDirectory() as folder:
            profile_store = ProfileStore(Path(folder) / 'profile.json')
            runtime = AdapterRuntime(EnvConfig(history_db=Path(folder) / 'coach.db', record_dir=Path(folder)), Settings(mode='SIMULATOR'),
                                     start_workers=False, profile_store=profile_store).start()
            runtime.state.grade = GradeController(GradePrefs(), ride=runtime.state.ride)  # as WAHOO + gear control
            server = Server(runtime)
            try:
                server.call('POST', '/admin/profile', {'gradeDifficultyPercent': 100, 'maxGradePercent': 6})
                self.assertEqual(runtime.state.grade.prefs, GradePrefs(100, 50, 6.0, -5.0))
                server.call('POST', '/admin/profile', {'gradeTransitionMetersPerPercent': 40, 'riderWeightKg': 110})
                self.assertEqual((runtime.state.ride.meters_per_percent, runtime.state.ride.rider_kg), (40.0, 110.0))
                with self.assertRaises(HTTPError) as ctx:
                    server.call('POST', '/admin/profile', {'gradeDifficultyPercent': 150})
                self.assertEqual(ctx.exception.code, 400)
                self.assertEqual(runtime.state.grade.prefs.difficulty_percent, 100)
            finally:
                server.close()
                runtime.shutdown()

    def test_runtime_builds_the_controller_only_with_gear_control(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder) / 'profile.json')
            store.update({'gradeDifficultyPercent': 30})
            for settings, expected in ((Settings(mode='WAHOO', gear_control_enabled=True), True),
                                       (Settings(mode='WAHOO'), False), (Settings(mode='SIMULATOR'), False)):
                runtime = AdapterRuntime(EnvConfig(history_db=Path(folder) / 'coach.db', record_dir=Path(folder)), settings, start_workers=False,
                                         profile_store=store).start()
                try:
                    with self.subTest(settings=settings):
                        self.assertEqual(runtime.state.grade is not None, expected)
                        self.assertIsNotNone(runtime.state.ride)  # the virtual road exists outside REPLAY
                        if expected:
                            self.assertEqual(runtime.state.grade.prefs.difficulty_percent, 30)
                finally:
                    runtime.shutdown()

if __name__ == '__main__':
    unittest.main()
