"""Sessions in the local database (coach/session/session_store.py, ADR-003 phase 2c)."""
import json
from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from unittest import mock
from urllib.request import urlopen

from coach.app import db
from coach.app.legacy_json import import_session_files
from coach.app.routes_store import save_upload
from coach.app.runtime import AdapterRuntime, EnvConfig
from coach.app.server import make_server
from coach.app.settings import Settings
from coach.history.store import HistoryStore
from coach.session.session import SessionManager, delete_session, sessions_page
from coach.session.session_store import SessionStore
from tests.test_routes import CLIMB, gpx, segments_profile


def summary(stem, day=1, **extra):
    return {'session': stem, 'startedAtUtc': f'2026-11-{day:02d}T10:00:00+00:00', 'csv': f'{stem}.csv',
            'elapsedSeconds': 3600.0, 'distanceKm': 30.0, 'workKj': 600.0, 'avgPowerW': 170.0, 'maxPowerW': 400,
            'normalizedPowerW': 180.0, 'ftpWatts': 200, 'tss': 81.0, 'elevationGainM': 300.0,
            'bestEffortsW': {'300': 230}, 'gearSeconds': {'12': 3600.0}, **extra}


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.db = db.migrate(self.folder / 'coach.db')
        self.store = SessionStore(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_saved_whole_with_its_columns_and_its_activity(self):
        self.store.save(summary('session_20261101_100000', trainerDifficultyPercent=50,
                                workout={'id': 'sweet_spot', 'name': 'Sweet spot 3×12', 'workCompliancePct': 97}))
        self.assertEqual(self.store.get('session_20261101_100000')['bestEffortsW'], {'300': 230})
        with db.opened(self.db) as conn:
            row = conn.execute('SELECT tss, work_kj, trainer_difficulty_pct, workout_id, gear_seconds FROM sessions').fetchone()
        self.assertEqual(row[:4], (81.0, 600.0, 50.0, 'sweet_spot'))
        self.assertEqual(json.loads(row[4]), {'12': 3600.0})
        [activity] = HistoryStore(self.db).list()
        self.assertEqual((activity['id'], activity['name'], activity['np']), ('app:session_20261101_100000', 'Sweet spot 3×12', 180.0))

    def test_saving_again_keeps_what_the_history_added(self):
        self.store.save(summary('session_20261101_100000'))
        HistoryStore(self.db).update('app:session_20261101_100000', {'mmp': '{"60": 300}', 'enriched': 1})
        self.store.update('session_20261101_100000', {'feedback': {'rpe': 7, 'note': 'bien'}})
        [activity] = HistoryStore(self.db).list()
        self.assertEqual((activity['rpe'], activity['feeling'], activity['mmp']), (7, 'bien', '{"60": 300}'))

    def test_pages_newest_first(self):
        for day in range(1, 26):
            self.store.save(summary(f'session_202611{day:02d}_100000', day))
        first, total = self.store.list(limit=10)
        self.assertEqual(total, 25)
        self.assertEqual([s['session'] for s in first[:2]], ['session_20261125_100000', 'session_20261124_100000'])
        last, _ = self.store.list(limit=10, offset=20)
        self.assertEqual(len(last), 5)
        self.assertEqual(last[-1]['session'], 'session_20261101_100000')

    def test_deleting_stops_counting_but_keeps_the_rows(self):
        stem = 'session_20261101_100000'
        (self.folder / f'{stem}.csv').write_text('recordedAtUtc\n')
        self.store.save(summary(stem))
        out = delete_session(self.folder, stem, self.db)
        self.assertEqual(out['moved'], [f'{stem}.csv'])
        self.assertIsNone(self.store.get(stem))
        self.assertEqual(self.store.list(), ([], 0))
        self.assertEqual(HistoryStore(self.db).list(), [])                 # not in the history nor the load
        self.assertEqual(self.store.get(stem, include_deleted=True)['tss'], 81.0)
        with self.assertRaises(FileNotFoundError):
            delete_session(self.folder, stem, self.db)

    def test_routes_ridden_are_linked_to_the_catalogue(self):
        routes = self.folder / 'routes'
        save_upload(routes, 'cuna.gpx', gpx(segments_profile(CLIMB)), self.db)
        self.store.save(summary('session_20261101_100000', routes=[{'file': 'cuna.gpx', 'name': 'Cuna', 'km': 2.4},
                                                                   {'file': 'gone.gpx', 'km': 1.0}]))
        with db.opened(self.db) as conn:
            linked = conn.execute('SELECT r.file, sr.km FROM session_routes sr JOIN routes r ON r.id = sr.route_id').fetchall()
        self.assertEqual(linked, [('cuna.gpx', 2.4)])                      # an unknown route stays in the summary only
        self.assertEqual(len(self.store.get('session_20261101_100000')['routes']), 2)

    def test_summaries_left_as_json_are_imported_and_moved(self):
        rec = self.folder / 'rec'
        rec.mkdir()
        (rec / 'session_20261102_100000.json').write_text(json.dumps(summary('session_20261102_100000', 2)))
        (rec / 'session_20261101_100000.json').write_text(json.dumps(summary('session_20261101_100000', 1, tss=1.0)))
        (rec / 'session_broken.json').write_text('{oops')
        self.store.save(summary('session_20261101_100000'))                 # already there: not replaced
        self.assertEqual(import_session_files(rec, self.db), 1)
        self.assertEqual(self.store.get('session_20261101_100000')['tss'], 81.0)
        self.assertEqual(self.store.list()[1], 2)
        self.assertEqual(list(rec.glob('*.json')), [])
        self.assertEqual(len(list(self.folder.glob('backup-json-*/rec/*.json'))), 3)


class SessionManagerStoreTests(unittest.TestCase):
    def test_a_finished_session_goes_to_the_database_or_next_to_its_csv(self):
        reading = lambda: {'source': 'WAHOO', 'connected': True, 'powerWatts': 150, 'cadenceRpm': 80, 'speedKph': 30.0}
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            session = SessionManager(reading, folder, sample_seconds=60, db_path=folder / 'coach.db')
            session.start()
            stem = session.finish()['session']
            self.assertIsNotNone(SessionStore(folder / 'coach.db').get(stem))
            self.assertEqual(list(folder.glob('session_*.json')), [])
            session.now = lambda: datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)   # another session, another stem
            session.start()
            with mock.patch('coach.session.session_store.SessionStore.save', side_effect=OSError('disk full')):
                stem = session.finish()['session']
            self.assertTrue((folder / f'{stem}.json').is_file())           # never lost: imported on the next read
            self.assertEqual(import_session_files(folder, folder / 'coach.db'), 1)
            self.assertIsNotNone(SessionStore(folder / 'coach.db').get(stem))


class SessionsApiTests(unittest.TestCase):
    def test_pages_and_the_summary_download_come_from_the_database(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            store = SessionStore(folder / 'coach.db')
            for day in range(1, 24):
                store.save(summary(f'session_202611{day:02d}_100000', day))
            runtime = AdapterRuntime(EnvConfig(history_db=folder / 'coach.db', record_dir=folder),
                                     Settings(mode='SIMULATOR'), start_workers=False).start()
            httpd = make_server('127.0.0.1', 0, runtime)
            base = f'http://127.0.0.1:{httpd.server_address[1]}'
            Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                with urlopen(base + '/sessions', timeout=10) as r:
                    page = json.loads(r.read())
                self.assertEqual((len(page['sessions']), page['total'], page['limit'], page['offset']), (20, 23, 20, 0))
                with urlopen(base + '/sessions?limit=20&offset=20', timeout=10) as r:
                    self.assertEqual(len(json.loads(r.read())['sessions']), 3)
                with urlopen(base + '/sessions/session_20261105_100000.json', timeout=10) as r:
                    self.assertEqual(json.loads(r.read())['tss'], 81.0)
                self.assertEqual(sessions_page(folder, folder / 'coach.db', 5, 0)[1], 23)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
