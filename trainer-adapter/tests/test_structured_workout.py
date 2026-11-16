"""Structured workouts without ERG: library, blocks over time, scoring, pause, API and session summary."""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.workouts.structured import LIBRARY, Block, StructuredWorkout, WorkoutDef, watts
from coach.session.session_store import SessionStore


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


SHORT = WorkoutDef('short', 'Corto', 'test', (Block('Calentamiento', 'WARMUP', 60, 50, 70),
                                              Block('Duro', 'WORK', 120, 100, cadence=85),
                                              Block('Suave', 'REST', 60, 50)))


def ride(workout, clock, seconds, power=None, state='RUNNING', step=1.0, connected=True):
    for _ in range(int(seconds / step)):
        clock.t += step
        watts_now = power if power is not None else (workout.target_w() or 0)
        workout.tick({'connected': connected, 'powerWatts': watts_now, 'sessionState': state})


class LibraryTests(unittest.TestCase):
    def test_every_workout_is_sensible(self):
        self.assertGreaterEqual(len(LIBRARY), 6)
        for w in LIBRARY.values():
            with self.subTest(w.id):
                data = w.to_json(200)
                self.assertTrue(30 * 60 <= w.seconds <= 90 * 60, w.seconds)
                self.assertEqual(w.blocks[0].kind if w.id != 'recovery' else 'WARMUP', 'WARMUP')
                self.assertEqual(w.blocks[-1].kind, 'COOLDOWN')
                self.assertTrue(all(0 < b.seconds and 30 <= b.start_pct <= 130 for b in w.blocks))
                self.assertTrue(0.5 < data['intensityFactor'] < 1.0)
                self.assertEqual(data['blocks'][0]['startW'], watts(w.blocks[0].start_pct, 200))
        self.assertEqual(LIBRARY['sweetspot-3x12'].to_json()['workSeconds'], 36 * 60)
        self.assertIsNone(LIBRARY['vo2-5x4'].to_json()['blocks'][0]['startW'])      # no FTP: no watts

    def test_targets_round_to_5_w(self):
        self.assertEqual(watts(88, 156), 135)
        self.assertEqual(watts(115, 156), 180)


class RideTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.w = StructuredWorkout(SHORT, ftp=200, clock=self.clock)
        self.w.tick({'connected': True, 'powerWatts': 0})             # the first tick only starts the clock

    def test_warm_up_ramps_then_blocks_follow(self):
        self.assertEqual(self.w.target_w(), 100)
        ride(self.w, self.clock, 30)
        self.assertEqual(self.w.target_w(), 120)                         # halfway 50 → 70 %
        ride(self.w, self.clock, 30)
        snap = self.w.snapshot()
        self.assertEqual((snap['workoutBlock'], snap['workoutBlockName'], snap['targetPowerW'], snap['targetCadenceRpm']),
                         (2, 'Duro', 200, 85))
        self.assertEqual(snap['workoutNext']['targetW'], 100)
        self.assertEqual(snap['workoutStepRemainingS'], 120)

    def test_scoring_and_the_end(self):
        ride(self.w, self.clock, 60)
        ride(self.w, self.clock, 60, power=180)
        ride(self.w, self.clock, 60, power=230)                          # 180 and 230: average 205, half in range
        ride(self.w, self.clock, 60, power=100)
        self.assertEqual((self.w.phase, self.w.reason), ('DONE', 'completed'))
        hard = self.w.results[1]
        self.assertEqual((hard['avgW'], hard['targetW'], hard['compliancePct'], hard['inRangePct']), (205, 200, 102, 50))
        summary = self.w.summary()
        self.assertEqual((summary['completedPct'], summary['workCompliancePct'], len(summary['blocks'])), (100, 102, 3))
        ride(self.w, self.clock, 10)                                      # nothing after the end
        self.assertEqual(self.w.elapsed, 240)

    def test_pause_stops_the_clock_and_lost_data_counts_as_zero(self):
        ride(self.w, self.clock, 30, state='PAUSED')
        self.assertEqual(self.w.elapsed, 0)
        ride(self.w, self.clock, 60)
        ride(self.w, self.clock, 60, connected=False)
        ride(self.w, self.clock, 60)
        self.assertEqual(self.w.results[1]['compliancePct'], 50)

    def test_a_late_tick_is_split_between_blocks(self):
        ride(self.w, self.clock, 58)
        ride(self.w, self.clock, 4, power=150, step=4.0)                 # crosses 60 s: 2 s in each block
        self.assertEqual(self.w.results[0]['seconds'], 60)
        self.assertAlmostEqual(self.w.block_elapsed(), 2)

    def test_stopping_early_keeps_what_was_done(self):
        ride(self.w, self.clock, 90)
        self.w.finish()
        self.assertEqual((self.w.phase, self.w.reason, len(self.w.results)), ('DONE', 'rider finished', 2))
        self.assertEqual(self.w.results[1]['seconds'], 30)
        self.assertEqual(self.w.summary()['completedPct'], 38)
        self.assertIsNone(self.w.target_w())


class ApiTests(unittest.TestCase):
    def setUp(self):
        from coach.app.rider_profile import ProfileStore
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.profiles = ProfileStore(self.folder / 'coach.db')
        self.runtime = AdapterRuntime(EnvConfig(record_dir=self.folder, routes_dir=self.folder / 'r',
                                                history_db=self.folder / 'h.db'),
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
        data = b'' if body is None and method == 'POST' else (None if body is None else json.dumps(body).encode())
        request = Request(self.base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as r:
            return json.loads(r.read())

    def test_needs_an_ftp(self):
        self.assertIsNone(self.call('/workout/library', method='GET')['ftpW'])
        self.assertIsNone(self.call('/telemetry', method='GET')['ftpW'])          # no FTP: no zone
        with self.assertRaises(HTTPError) as ctx:
            self.call('/workout/structured/start', {'id': 'sweetspot-3x12'})
        self.assertEqual(ctx.exception.code, 409)
        with self.assertRaises(HTTPError) as ctx:
            self.call('/workout/structured/start', {'id': 'nope'})
        self.assertEqual(ctx.exception.code, 400)

    def test_ride_one_and_the_session_keeps_it(self):
        from coach.app.server import current_reading
        self.profiles.update({'ftpWatts': 200})
        library = self.call('/workout/library', method='GET')
        self.assertEqual((library['ftpW'], library['ftpSource']), (200, 'profile'))
        telemetry = self.call('/telemetry', method='GET')                          # for the zone in the Panel
        self.assertEqual((telemetry['ftpW'], telemetry['ftpSource']), (200, 'profile'))
        self.assertEqual(next(w for w in library['workouts'] if w['id'] == 'sweetspot-3x12')['blocks'][1]['startW'], 180)
        started = self.call('/workout/structured/start', {'id': 'sweetspot-3x12'})
        self.assertEqual((started['workoutType'], started['workoutName'], started['targetPowerW']),
                         ('STRUCTURED', 'Sweet spot 3×12', 90))
        self.assertEqual(self.call('/telemetry', method='GET')['sessionState'], 'RUNNING')
        with self.assertRaises(HTTPError) as ctx:                       # one at a time
            self.call('/workout/ramp/start')
        self.assertEqual(ctx.exception.code, 409)
        workout = self.runtime.state.workout
        clock = Clock()
        workout.clock = clock
        for _ in range(60 * 26 + 1):                                    # warm-up and the first interval
            clock.t += 1
            reading = current_reading(self.runtime.state)
            reading['sessionState'] = 'RUNNING'
            workout.tick(reading)
        self.assertEqual(workout.results[1]['compliancePct'], 100)      # the simulated rider follows the target
        self.assertEqual(workout.results[1]['inRangePct'], 100)
        self.runtime.session.finish()                                   # finishing the session ends the workout
        [saved], _total = SessionStore(self.runtime.env.history_db).list()
        self.assertEqual((saved['workout']['type'], saved['workout']['endReason']), ('STRUCTURED', 'session finished'))
        self.assertEqual(saved['workout']['workCompliancePct'], 100)
        self.assertEqual(self.call('/workout/clear'), {'workout': None})


if __name__ == '__main__':
    unittest.main()
