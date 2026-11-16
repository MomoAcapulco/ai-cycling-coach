import sqlite3
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.app.rider_profile import ProfileStore, RiderProfile
from coach.app.runtime import AdapterRuntime, EnvConfig
from coach.app.server import make_server
from coach.app.settings import Settings
from coach.app import db


class ProfileTests(unittest.TestCase):
    def test_defaults_and_total_mass(self):
        p = RiderProfile().updated({'riderWeightKg': 80, 'bikeWeightKg': 9.5, 'drivetrain': 'ZWIFT_COG'})
        self.assertEqual((p.rider_weight_kg, p.bike_weight_kg, p.total_mass_kg, p.ftp_watts), (80.0, 9.5, 89.5, None))
        self.assertEqual(p.to_json()['totalMassKg'], 89.5)

    def test_out_of_range_is_rejected_not_clamped(self):
        for bad in ({'riderWeightKg': 800}, {'riderWeightKg': 20}, {'bikeWeightKg': 0}, {'ftpWatts': 5000},
                    {'ftpWatts': 250.5}, {'ftpWatts': '250'}, {'riderWeightKg': True}, {'drivetrain': 'BELT'},
                    {'heightCm': 180}, [1]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                RiderProfile().updated(bad)

    def test_ftp_can_be_cleared(self):
        p = RiderProfile().updated({'ftpWatts': 230})
        self.assertIsNone(p.updated({'ftpWatts': None}).ftp_watts)

    def test_store(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder) / 'p' / 'profile.json')
            self.assertEqual(store.load(), (RiderProfile(), False))
            store.update({'riderWeightKg': 80, 'bikeWeightKg': 9.5})
            store.update({'ftpWatts': 200})
            profile, saved = store.load()
            self.assertTrue(saved)
            self.assertEqual((profile.rider_weight_kg, profile.ftp_watts), (80.0, 200))
            self.assertEqual([v['ftpWatts'] for _, v in store.versions()], [None, 200])   # every version kept
            with db.opened(store.path) as conn:                                  # a value no version allows
                conn.execute('UPDATE profile SET rider_weight_kg = 900')
            self.assertEqual(store.load(), (RiderProfile(), False))


class ProfileEndpointTests(unittest.TestCase):
    def test_get_and_post(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder) / 'profile.json')
            runtime = AdapterRuntime(EnvConfig(history_db=Path(folder) / 'coach.db', record_dir=Path(folder)), Settings(), start_workers=False,
                                     profile_store=store).start()
            httpd = make_server('127.0.0.1', 0, runtime)
            base = f'http://127.0.0.1:{httpd.server_address[1]}'
            Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                with urlopen(base + '/admin/profile', timeout=5) as r:
                    self.assertFalse(json.loads(r.read())['saved'])
                body = json.dumps({'riderWeightKg': 80, 'bikeWeightKg': 9.5, 'drivetrain': 'ZWIFT_COG'}).encode()
                with urlopen(Request(base + '/admin/profile', data=body, method='POST',
                                     headers={'Content-Type': 'application/json'}), timeout=5) as r:
                    data = json.loads(r.read())
                self.assertEqual((data['saved'], data['profile']['totalMassKg']), (True, 89.5))
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(Request(base + '/admin/profile', data=b'{"riderWeightKg": 800}', method='POST',
                                    headers={'Content-Type': 'application/json'}), timeout=5)
                self.assertEqual(ctx.exception.code, 400)
                self.assertEqual(store.load()[0].rider_weight_kg, 80.0)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
