import csv
import json
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.app.runtime import AdapterRuntime, EnvConfig
from coach.app.server import make_server
from coach.app.settings import Settings
from coach.session.recording import CsvReplay
from coach.session.session import SessionError, SessionManager, list_sessions
from coach.session.session_store import SessionStore


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def reading():
    return {'source': 'WAHOO', 'connected': True, 'status': 'STREAMING', 'powerWatts': 150, 'cadenceRpm': 80,
            'speedKph': 30.0, 'heartRateBpm': 130, 'heartRateConnected': True, 'trainerGear': 14,
            'requestedGear': 14, 'gearStatus': 'READY'}


class SessionManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.clock = Clock()
        # a sampling period far longer than the test: samples happen only on pause/finish (deterministic)
        self.session = SessionManager(reading, self.folder, ftp=lambda: 200, clock=self.clock, sample_seconds=60,
                                      db_path=self.folder / 'coach.db')

    def tearDown(self):
        self.temp.cleanup()

    def test_start_pause_resume_finish(self):
        self.assertEqual(self.session.start()['sessionState'], 'RUNNING')
        self.clock.t = 60
        self.assertEqual(self.session.pause()['sessionElapsedSeconds'], 60.0)
        self.clock.t = 600                                   # 9 minutes paused: not counted
        self.session.resume()
        self.clock.t = 660
        summary = self.session.finish()
        self.assertEqual(summary['elapsedSeconds'], 120.0)
        self.assertEqual(summary['workKj'], 18.0)          # 150 W × 120 s
        self.assertAlmostEqual(summary['distanceKm'], 1.0)  # 30 km/h × 120 s
        self.assertEqual(summary['gearSeconds'], {'14': 120.0})
        self.assertEqual(summary['ftpWatts'], 200)
        saved = SessionStore(self.folder / 'coach.db').get(summary['session'])
        self.assertEqual(saved['csv'], f"{summary['session']}.csv")
        with (self.folder / saved['csv']).open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([r['elapsedSeconds'] for r in rows], ['60.0', '120.0'])
        self.assertEqual(rows[0]['trainerGear'], '14')
        CsvReplay(self.folder / saved['csv'])               # a finished session can be replayed

    def test_wrong_state_actions(self):
        for action in (self.session.pause, self.session.resume, self.session.finish):
            with self.assertRaises(SessionError):
                action()
        self.session.start()
        with self.assertRaises(SessionError):
            self.session.start()
        self.session.finish()
        self.assertIsNone(SessionManager(reading, self.folder).finish_if_active('x'))

    def test_safety_limit_finishes_by_itself(self):
        session = SessionManager(reading, self.folder, max_seconds=0.2, sample_seconds=0.05)
        session.start()
        time.sleep(0.6)
        self.assertEqual(session.snapshot()['sessionState'], 'IDLE')
        self.assertEqual(session.last_summary['finishReason'], 'safety limit of 4 h reached')

    def test_list_sessions(self):
        self.session.start()
        self.clock.t = 30
        self.session.finish()
        (self.folder / 'session_broken.json').write_text('{oops')        # a stray file does not matter any more
        [entry] = list_sessions(self.folder, self.folder / 'coach.db')
        self.assertEqual(entry['files'], [entry['csv'], f"{entry['session']}.json"])


class SessionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = AdapterRuntime(EnvConfig(history_db=Path(self.temp.name) / 'coach.db', record_dir=Path(self.temp.name)), Settings(mode='SIMULATOR'),
                                      start_workers=False).start()
        self.httpd = make_server('127.0.0.1', 0, self.runtime)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.runtime.shutdown()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.temp.cleanup()

    def call(self, method, path):
        with urlopen(Request(self.base + path, data=b'' if method == 'POST' else None, method=method), timeout=5) as r:
            return r.status, r.headers, r.read()

    def test_session_through_http(self):
        self.assertEqual(json.loads(self.call('GET', '/telemetry')[2])['sessionState'], 'IDLE')
        self.assertEqual(json.loads(self.call('POST', '/session/start')[2])['sessionState'], 'RUNNING')
        self.assertEqual(json.loads(self.call('GET', '/telemetry')[2])['sessionState'], 'RUNNING')
        with self.assertRaises(HTTPError) as ctx:
            self.call('POST', '/session/resume')
        self.assertEqual(ctx.exception.code, 409)
        time.sleep(1.2)
        summary = json.loads(self.call('POST', '/session/finish')[2])
        listing = json.loads(self.call('GET', '/sessions')[2])['sessions']
        self.assertEqual(listing[0]['session'], summary['session'])
        status, headers, body = self.call('GET', f"/sessions/{summary['csv']}")
        self.assertEqual(status, 200)
        self.assertIn('attachment', headers['Content-Disposition'])
        self.assertTrue(body.decode().startswith('recordedAtUtc,'))
        for bad in ('/sessions/../settings.json', '/sessions/ride_x.csv', '/sessions/session_20990101_000000.csv'):
            with self.subTest(bad=bad), self.assertRaises(HTTPError) as ctx:
                self.call('GET', bad)
            self.assertEqual(ctx.exception.code, 404)

    def test_changing_settings_finishes_the_session(self):
        self.call('POST', '/session/start')
        self.runtime.update({'hrEnabled': True})
        [entry] = list_sessions(Path(self.temp.name), self.runtime.env.history_db)
        self.assertEqual(entry['finishReason'], 'settings changed')

    def test_no_sessions_in_replay(self):
        folder = Path(self.temp.name)
        (folder / 'r.csv').write_text('elapsedSeconds,source,powerWatts,cadenceRpm,speedKph,connected,status,'
                                      'heartRateBpm,heartRateConnected\n0,WAHOO,1,1,1,true,S,,false\n')
        self.runtime.update({'mode': 'REPLAY', 'replayFile': 'r.csv'})
        with self.assertRaises(HTTPError) as ctx:
            self.call('POST', '/session/start')
        self.assertEqual(ctx.exception.code, 409)


if __name__ == '__main__':
    unittest.main()
