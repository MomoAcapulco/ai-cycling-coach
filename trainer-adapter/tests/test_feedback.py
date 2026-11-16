"""How a session felt (perceived effort 1–10 and a note): saved in the session, the history and per route."""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.session.session import save_feedback
from tests.test_fit_export import row as csv_row, write_session
from coach.session.session_store import SessionStore


class FeedbackTests(unittest.TestCase):
    def test_saved_in_the_summary_and_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write_session(folder, [csv_row(t) for t in range(60)])
            saved = save_feedback(folder, 'session_20261113_130000', {'rpe': 7, 'note': '  piernas cargadas '}, folder / 'coach.db')
            self.assertEqual((saved['rpe'], saved['note']), (7, 'piernas cargadas'))
            summary = SessionStore(folder / 'coach.db').get('session_20261113_130000')
            self.assertEqual(summary['feedback']['rpe'], 7)
            self.assertEqual(summary['avgPowerW'], 200.0)                               # the rest is kept
            self.assertIsNone(save_feedback(folder, 'session_20261113_130000', {'rpe': None}, folder / 'coach.db')['rpe'])
            for bad in ({'rpe': 11}, {'rpe': 0}, {'rpe': 6.5}, {'rpe': True}, {'note': 'x' * 501}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    save_feedback(folder, 'session_20261113_130000', bad, folder / 'coach.db')
            for stem in ('session_20261113_130001', '../x', 'session_1'):
                with self.subTest(stem=stem), self.assertRaises(FileNotFoundError):
                    save_feedback(folder, stem, {'rpe': 5}, folder / 'coach.db')


class ApiTests(unittest.TestCase):
    def setUp(self):
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.runtime = AdapterRuntime(EnvConfig(record_dir=self.folder, routes_dir=self.folder / 'routes',
                                                history_db=self.folder / 'h.db'),
                                      Settings(mode='SIMULATOR'), start_workers=False).start()
        self.httpd = make_server('127.0.0.1', 0, self.runtime)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.runtime.shutdown()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.temp.cleanup()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        with urlopen(Request(self.base + path, data=data, method='GET' if body is None else 'POST',
                             headers={'Content-Type': 'application/json'}), timeout=20) as r:
            return json.loads(r.read())

    def test_a_session_on_a_route_feeds_the_history_and_the_route(self):
        route = self.call('/routes/generate', {'mode': 'custom', 'distanceKm': 10, 'gainM': 100, 'climbs': 1,
                                               'avgGrade': 5, 'maxGrade': 8, 'save': True})
        self.call('/route/start', {'file': route['file']})
        session = self.runtime.session
        session.start()
        session._sample_unlocked()                                     # one sample on the route
        stem = session.finish()['session']
        saved = SessionStore(self.runtime.env.history_db).get(stem)
        self.assertEqual(saved['routes'][0]['file'], route['file'])
        self.assertEqual(self.call(f'/sessions/{stem}/feedback', {'rpe': 8, 'note': 'dura'})['rpe'], 8)
        [listed] = self.call('/routes')['routes']
        self.assertEqual((listed['rides'], listed['lastRide']['rpe'], listed['lastRide']['session']), (1, 8, stem))
        self.assertFalse(listed['lastRide']['replayable'])                    # one second: not enough to replay
        self.assertIn('duró solo', listed['lastRide']['why'])
        self.assertIsNone(listed['replayRide'])
        from coach.session.recording import CsvReplay
        replay = CsvReplay(self.folder / f'{stem}.csv', db_path=self.runtime.env.history_db)
        self.assertEqual(replay.series()['routes'][0]['file'], route['file'])  # the replay can draw the route
        self.assertEqual(replay.snapshot()['routeName'], route['name'])
        store = SessionStore(self.runtime.env.history_db)                      # as if it had lasted 10 min, 5 km
        summary = store.get(stem)
        summary['elapsedSeconds'], summary['routes'][0]['km'] = 600, 5.0
        store.save(summary)
        [listed] = self.call('/routes')['routes']
        self.assertEqual((listed['replayRide']['session'], listed['replayRide']['csv']), (stem, f'{stem}.csv'))
        [activity] = self.call('/history')['activities']
        self.assertEqual((activity['rpe'], activity['feeling']), (8, 'dura'))
        with self.assertRaises(HTTPError) as ctx:
            self.call('/sessions/session_20000101_000000/feedback', {'rpe': 5})
        self.assertEqual(ctx.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
