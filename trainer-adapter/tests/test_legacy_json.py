"""coach/app/legacy_json.py: the JSON files of earlier versions go into coach.db once, and are moved, never deleted."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coach.app import db
from coach.app.legacy_json import import_all
from coach.app.rider_profile import ProfileStore
from coach.app.settings import Settings, SettingsStore

PROFILE = {'version': 1, 'updatedAtUtc': '2026-11-14T09:30:00+00:00',
           'profile': {'riderWeightKg': 80.0, 'bikeWeightKg': 9.5, 'ftpWatts': 180, 'drivetrain': 'ZWIFT_COG',
                       'totalMassKg': 89.5, 'gradeDifficultyPercent': 50, 'bikeType': 'MTB', 'maxHeartRate': 185}}
SETTINGS = {'version': 1, 'settings': {'mode': 'SIMULATOR', 'replayFile': None, 'hrEnabled': True,
                                       'zwiftEnabled': True, 'recordEnabled': False, 'recordSeconds': 600,
                                       'gearControlEnabled': True}}


class LegacyJsonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {'AI_COACH_HOME': str(self.home)})
        self.env.start()
        for name in ('PROFILE_FILE', 'SETTINGS_FILE', 'COACH_DB', 'HISTORY_DB'):
            os.environ.pop(name, None)
        db._ready.clear()
        self.db = db.migrate(self.home / 'coach.db')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def write(self, name, data):
        (self.home / name).write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')

    def backups(self):
        return sorted(p.relative_to(self.home).as_posix() for p in self.home.glob('backup-json-*/**/*') if p.is_file())

    def test_profile_and_settings_are_imported_and_moved(self):
        self.write('profile.json', PROFILE)
        self.write('settings.json', SETTINGS)
        done = import_all(self.home, self.db)
        self.assertTrue(done['profile'].startswith('imported') and done['settings'].startswith('imported'))
        profile, saved = ProfileStore(self.db).load()
        self.assertTrue(saved)
        self.assertEqual((profile.rider_weight_kg, profile.ftp_watts, profile.bike_type, profile.max_heart_rate),
                         (80.0, 180, 'MTB', 185))
        self.assertEqual(ProfileStore(self.db).versions()[0][0], '2026-11-14T09:30:00+00:00')   # when it was saved
        settings, source = SettingsStore(self.db).load(Settings())
        self.assertEqual((source, settings.hr_enabled, settings.gear_control_enabled), ('saved', True, True))
        self.assertFalse((self.home / 'profile.json').exists())                 # moved, not left behind…
        self.assertEqual([b.split('/', 1)[1] for b in self.backups()], ['profile.json', 'settings.json'])
        backup = next(self.home.glob('backup-json-*/profile.json'))
        self.assertEqual(json.loads(backup.read_text()), PROFILE)               # …and kept exactly as it was

    def test_it_runs_once(self):
        self.write('profile.json', PROFILE)
        import_all(self.home, self.db)
        self.write('profile.json', {**PROFILE, 'profile': {**PROFILE['profile'], 'ftpWatts': 999}})
        self.assertEqual(import_all(self.home, self.db), {})
        self.assertEqual(ProfileStore(self.db).load()[0].ftp_watts, 180)
        self.assertTrue((self.home / 'profile.json').exists())                  # a later file is not touched

    def test_nothing_to_import_is_noted_too(self):
        done = import_all(self.home, self.db)
        self.assertEqual(done, {'profile': 'no profile.json', 'settings': 'no settings.json',
                                'route_names': 'no names.json'})
        self.assertEqual(self.backups(), [])
        self.assertEqual(ProfileStore(self.db).load()[1], False)
        self.assertIn('no profile.json', db.meta(self.db, 'json_imported_profile'))

    def test_an_unreadable_file_is_moved_and_the_defaults_used(self):
        self.write('profile.json', '{half written')
        self.write('settings.json', {'settings': 'not an object'})
        done = import_all(self.home, self.db)
        self.assertIn('not valid', done['profile'])
        self.assertIn('not valid', done['settings'])
        self.assertEqual(ProfileStore(self.db).load(), ProfileStore(self.db).load()[:1] + (False,))
        self.assertEqual(SettingsStore(self.db).load(Settings())[1], 'env')
        self.assertEqual(len(self.backups()), 2)                                # still there to look at

    def test_the_default_database_imports_on_opening(self):
        self.write('profile.json', PROFILE)
        db._ready.clear()
        store = ProfileStore.default()
        self.assertEqual(store.path, self.home / 'coach.db')
        self.assertEqual(store.load()[0].ftp_watts, 180)


if __name__ == '__main__':
    unittest.main()
