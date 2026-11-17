"""The history of the FTP in the database (coach/history/ftp_log.py): tests, estimates and where the FTP came from."""
import tempfile
import unittest
from pathlib import Path

from coach.app import db
from coach.app.rider_profile import ProfileStore
from coach.history.ftp_log import mark_estimate_accepted, mark_test_accepted, record_estimate
from coach.session.session_store import SessionStore

ADVICE = {'ftp': 150, 'kind': 'raise', 'suggestedFtp': 162,
          'indoor': {'ftp': 162, 'method': 'cp', 'cp': 150, 'wPrime': 14000, 'efforts': [{'seconds': 300, 'w': 210}]},
          'outdoor': None}


def ramp_session(stem, saved=False):
    return {'session': stem, 'startedAtUtc': '2026-11-16T18:00:00+00:00', 'finishedAtUtc': '2026-11-16T18:25:00+00:00',
            'elapsedSeconds': 1500.0, 'workKj': 250.0, 'distanceKm': 12.0,
            'workout': {'type': 'RAMP_TEST', 'name': 'Test de FTP (rampa)', 'ftpW': 171, 'best60sW': 228,
                        'maxHeartRate': 183, 'savedAsFtp': saved}}


class FtpLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = db.migrate(Path(self.temp.name) / 'coach.db')

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, sql):
        with db.opened(self.db) as conn:
            return conn.execute(sql).fetchall()

    def test_an_estimate_is_kept_once_until_it_changes(self):
        self.assertTrue(record_estimate(self.db, ADVICE, 'strava:1'))
        self.assertFalse(record_estimate(self.db, ADVICE, 'strava:1'))        # every visit to the Panel asks again
        self.assertTrue(record_estimate(self.db, {**ADVICE, 'suggestedFtp': 165, 'indoor': {**ADVICE['indoor'], 'ftp': 165}}, 'app:x'))
        rows = self.rows('SELECT indoor_ftp_w, method, cp_w, suggested_ftp_w, profile_ftp_w, advice, accepted '
                         'FROM ftp_estimates ORDER BY computed_utc, rowid')
        self.assertEqual(rows[0], (162, 'cp', 150.0, 162, 150, 'raise', None))
        self.assertEqual(len(rows), 2)
        self.assertTrue(mark_estimate_accepted(self.db, 165))                  # the rider took the newest proposal
        self.assertEqual(self.rows('SELECT suggested_ftp_w, accepted FROM ftp_estimates ORDER BY computed_utc, rowid'),
                         [(162, None), (165, 1)])

    def test_a_ramp_test_is_kept_with_its_session_whatever_the_order(self):
        store = SessionStore(self.db)
        store.save(ramp_session('session_20261116_180000'))                    # finished, not saved as FTP yet
        self.assertEqual(self.rows('SELECT activity_id, ftp_w, best_minute_w, max_hr, accepted FROM ftp_tests'),
                         [('app:session_20261116_180000', 171, 228, 183, 0)])
        self.assertTrue(mark_test_accepted(self.db, 'app:session_20261116_180000'))   # «Guardar» after finishing
        store.save(ramp_session('session_20261116_190000', saved=True))         # «Guardar» before finishing
        store.save(ramp_session('session_20261116_190000', saved=True))         # saving again: still one test
        self.assertEqual(self.rows('SELECT activity_id, accepted FROM ftp_tests ORDER BY activity_id'),
                         [('app:session_20261116_180000', 1), ('app:session_20261116_190000', 1)])

    def test_the_profile_knows_where_its_ftp_came_from(self):
        profiles = ProfileStore(self.db)
        profiles.update({'ftpWatts': 150})
        self.assertEqual(profiles.ftp_source(), 'manual')
        profiles.update({'riderWeightKg': 80})                                  # the FTP did not change: same source
        self.assertEqual(profiles.ftp_source(), 'manual')
        profiles.update({'ftpWatts': 162}, ftp_source='estimate')
        self.assertEqual(profiles.ftp_source(), 'estimate')
        profiles.update({'ftpWatts': 171}, ftp_source='test')
        self.assertEqual([(v['ftpWatts'], v['ftpSource']) for _, v in profiles.versions()],
                         [(150, 'manual'), (150, 'manual'), (162, 'estimate'), (171, 'test')])


if __name__ == '__main__':
    unittest.main()
