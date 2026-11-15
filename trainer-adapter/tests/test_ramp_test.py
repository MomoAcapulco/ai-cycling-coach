"""Ramp FTP test: protocol, end detection, result, API, simulated rider."""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.workouts.ramp_test import RampTest, best_average


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def ride(test, clock, seconds, power=None, cadence=85, hr=150, connected=True):
    """``seconds`` of 1 Hz telemetry; ``power`` None follows the target (or 120 W in the warm-up)."""
    for _ in range(int(seconds)):
        clock.t += 1
        watts = power if power is not None else (test.target_w() or 120)
        test.tick({'connected': connected, 'powerWatts': watts, 'cadenceRpm': cadence,
                   'heartRateBpm': hr, 'heartRateConnected': True})


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.test = RampTest(clock=self.clock)

    def test_warm_up_then_steps_of_one_minute(self):
        ride(self.test, self.clock, 299)
        self.assertEqual((self.test.phase, self.test.target_w()), ('WARMUP', None))
        ride(self.test, self.clock, 1)
        self.assertEqual((self.test.phase, self.test.step(), self.test.target_w()), ('RAMP', 1, 100))
        ride(self.test, self.clock, 60)
        self.assertEqual((self.test.step(), self.test.target_w()), (2, 120))
        ride(self.test, self.clock, 120)
        self.assertEqual(self.test.target_w(), 160)
        self.assertEqual(self.test.snapshot()['workoutStepRemainingS'], 60)

    def test_stopping_pedalling_ends_it_and_gives_75_percent_of_the_best_minute(self):
        ride(self.test, self.clock, 300)                     # warm-up
        ride(self.test, self.clock, 8 * 60)                  # 100 … 240 W
        ride(self.test, self.clock, 30, power=250)           # half a minute at 250 W, then gives up
        ride(self.test, self.clock, 4, power=0, cadence=0)
        self.assertEqual(self.test.phase, 'RAMP')            # 4 s are not enough
        ride(self.test, self.clock, 2, power=0, cadence=0)
        self.assertEqual((self.test.phase, self.test.reason), ('DONE', 'stopped pedalling'))
        best = (30 * 240 + 30 * 250) / 60                    # the best 60 s: last 30 s at 240 + 30 s at 250
        self.assertAlmostEqual(self.test.best_60s, best, delta=0.6)
        self.assertEqual(self.test.ftp, round(best * 0.75))
        self.assertEqual(self.test.snapshot()['ftpEstimateW'], self.test.ftp)
        self.assertEqual(self.test.max_hr, 150)

    def test_the_rider_can_finish_it(self):
        ride(self.test, self.clock, 300 + 5 * 60)
        self.test.finish()
        self.assertEqual((self.test.phase, self.test.reason, self.test.ftp), ('DONE', 'rider finished', round(180 * 0.75)))

    def test_too_short_ramp_gives_no_ftp(self):
        ride(self.test, self.clock, 300 + 120)
        self.test.finish()
        self.assertEqual((self.test.phase, self.test.ftp), ('DONE', None))

    def test_stopping_in_the_warm_up_aborts(self):
        ride(self.test, self.clock, 60)
        self.test.finish()
        self.assertEqual((self.test.phase, self.test.ftp), ('ABORTED', None))

    def test_lost_data_counts_as_not_pedalling_and_breaks_the_minute(self):
        self.assertIsNone(best_average([200] * 30 + [None] + [200] * 30, 60))
        ride(self.test, self.clock, 300 + 200)
        ride(self.test, self.clock, 6, connected=False)
        self.assertEqual(self.test.phase, 'DONE')

    def test_start_from_a_known_ftp(self):
        test = RampTest(start_w=80, step_w=10, clock=self.clock)
        ride(test, self.clock, 300 + 61)
        self.assertEqual(test.target_w(), 90)


class ApiTests(unittest.TestCase):
    def setUp(self):
        from coach.app.rider_profile import ProfileStore
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        self.profiles = ProfileStore(folder / 'profile.json')
        self.runtime = AdapterRuntime(EnvConfig(record_dir=folder, routes_dir=folder / 'r', history_db=folder / 'h.db'),
                                      Settings(mode='SIMULATOR'), start_workers=False, profile_store=self.profiles).start()
        self.httpd = make_server('127.0.0.1', 0, self.runtime)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.runtime.shutdown()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.temp.cleanup()

    def call(self, path, body=None, method='POST'):
        data = None if body is None else json.dumps(body).encode()
        if method == 'POST' and data is None:
            data = b''
        request = Request(self.base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as r:
            return json.loads(r.read())

    def test_start_ride_save_and_clear(self):
        from coach.app.server import current_reading
        started = self.call('/workout/ramp/start')
        self.assertEqual((started['workoutPhase'], started['workoutStartW']), ('WARMUP', 100))
        self.assertEqual(self.call('/telemetry', method='GET')['sessionState'], 'RUNNING')   # recorded
        test = self.runtime.state.workout
        clock = Clock()
        test.clock, test.started = clock, clock.t                      # drive it fast with a fake clock
        for _ in range(300 + 12 * 60):                                  # the simulated rider follows the target
            clock.t += 1
            test.tick(current_reading(self.runtime.state))
            if test.phase == 'DONE':
                break
        telemetry = self.call('/telemetry', method='GET')
        self.assertEqual((telemetry['workoutPhase'], telemetry['workoutEndReason']), ('DONE', 'stopped pedalling'))
        self.assertEqual(telemetry['ftpEstimateW'], round(260 * 0.75))   # it gave up above 260 W
        self.assertEqual(self.call('/workout/ftp/save'), {'ftpWatts': 195})
        self.assertEqual(self.profiles.load()[0].ftp_watts, 195)
        self.assertEqual(self.call('/workout/clear'), {'workout': None})
        self.assertNotIn('workoutPhase', self.call('/telemetry', method='GET'))

    def test_start_from_the_saved_ftp_and_options(self):
        self.profiles.update({'ftpWatts': 240})
        self.assertEqual(self.call('/workout/ramp/start')['workoutStartW'], 100)       # round(240 × 0.4, tens)
        self.call('/workout/stop')
        self.call('/workout/clear')
        self.assertEqual(self.call('/workout/ramp/start', {'startW': 150, 'stepW': 25})['workoutStepW'], 25)

    def test_errors(self):
        for path, body, code in (('/workout/stop', None, 409), ('/workout/ftp/save', None, 409),
                                 ('/workout/ramp/start', {'startW': 20}, 400),
                                 ('/workout/ramp/start', {'stepW': 'x'}, 400)):
            with self.subTest(path=path, body=body), self.assertRaises(HTTPError) as ctx:
                self.call(path, body)
            self.assertEqual(ctx.exception.code, code)
        self.call('/workout/ramp/start')
        for path in ('/workout/ramp/start', '/workout/clear'):                          # already running
            with self.subTest(path=path), self.assertRaises(HTTPError) as ctx:
                self.call(path)
            self.assertEqual(ctx.exception.code, 409)

    def test_not_on_a_route(self):
        from coach.session.route import parse_gpx
        from tests.test_routes import gpx, segments_profile
        self.runtime.state.ride.start_route(parse_gpx(gpx(segments_profile([(1000, 3)]))))
        with self.assertRaises(HTTPError) as ctx:
            self.call('/workout/ramp/start')
        self.assertEqual(ctx.exception.code, 409)


if __name__ == '__main__':
    unittest.main()
