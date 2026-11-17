import sqlite3
"""Admin page backend: settings, live mode switching, recordings upload, device forgetting."""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.bluetooth.device_registry import DeviceRegistry
from coach.bluetooth.discovery import Classified
from coach.app.runtime import AdapterRuntime, EnvConfig
from coach.app.server import make_server
from coach.app.settings import Settings, SettingsStore
from coach.app import db

CSV = ('elapsedSeconds,source,powerWatts,cadenceRpm,speedKph,connected,status,heartRateBpm,heartRateConnected,targetGradePercent\n'
       '0,WAHOO,100,60,15,true,STREAMING,120,true,\n'
       '2,WAHOO,200,70,18,true,STREAMING,140,true,2\n')


class SettingsTests(unittest.TestCase):
    def test_from_env(self):
        s = Settings.from_env({'TRAINER_MODE': 'replay', 'REPLAY_FILE': ' a.csv ', 'HR_ENABLED': 'true',
                               'ZWIFT_ENABLED': 'yes', 'RECORD_ENABLED': 'false', 'RECORD_SECONDS': '900'})
        self.assertEqual(s, Settings('REPLAY', 'a.csv', True, True, False, 900))
        self.assertEqual(Settings.from_env({}), Settings(mode='WAHOO', record_enabled=True))   # the trainer; the simulator is for development

    def test_updated_is_strict(self):
        base = Settings()
        self.assertEqual(base.updated({'mode': 'wahoo', 'hrEnabled': True}).mode, 'WAHOO')
        for bad in ({'hrEnabled': 'true'}, {'recordSeconds': '600'}, {'mode': 3}, {'controlTest': True},
                    {'replayFile': 7}, [1]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                base.updated(bad)

    def test_validate(self):
        with self.assertRaises(ValueError):
            Settings(mode='ZWIFT').validate()
        with self.assertRaises(ValueError):
            Settings(mode='REPLAY').validate()
        with self.assertRaises(ValueError):
            Settings(mode='REPLAY', replay_file='/nope/missing.csv').validate()
        with self.assertRaises(ValueError):
            Settings(record_seconds=10).validate()
        # The experimental physical control (.env only) pins the configuration it needs.
        with self.assertRaises(PermissionError):
            Settings(mode='SIMULATOR').validate(control_test=True)
        Settings(mode='WAHOO', record_enabled=True, record_seconds=600).validate(control_test=True)

    def test_replay_file_is_found_in_the_recordings_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            recordings = Path(folder)
            (recordings / 'ride.csv').write_text(CSV)
            for value in ('ride.csv', 'trainer-adapter/recordings/ride.csv'):  # new style and old .env style
                with self.subTest(value=value):
                    s = Settings(mode='REPLAY', replay_file=value)
                    self.assertEqual(s.replay_path(recordings), recordings / 'ride.csv')
                    s.validate(recordings_dir=recordings)
            with self.assertRaises(ValueError):
                Settings(mode='REPLAY', replay_file='other.csv').validate(recordings_dir=recordings)

    def test_gear_control_setting(self):
        self.assertFalse(Settings().gear_control_enabled)                      # physical control is opt-in
        self.assertTrue(Settings.from_env({'GEAR_CONTROL_ENABLED': 'true'}).gear_control_enabled)
        s = Settings(mode='WAHOO').updated({'gearControlEnabled': True})
        self.assertEqual(s.to_json()['gearControlEnabled'], True)
        with self.assertRaises(ValueError):
            Settings().updated({'gearControlEnabled': 'yes'})
        with self.assertRaises(PermissionError):
            Settings(mode='WAHOO', record_enabled=True, record_seconds=600, gear_control_enabled=True).validate(control_test=True)

    def test_store_round_trip_and_damage(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(Path(folder) / 'settings.json')
            defaults = Settings(mode='SIMULATOR')
            self.assertEqual(store.load(defaults), (defaults, 'env'))
            store.save(Settings(mode='WAHOO', hr_enabled=True))
            self.assertEqual(store.load(defaults)[0].mode, 'WAHOO')
            self.assertEqual(store.load(defaults)[1], 'saved')
            with db.opened(store.path) as conn:                     # a value that is not valid any more
                conn.execute("UPDATE settings SET value = '{oops'")
            self.assertEqual(store.load(defaults), (defaults, 'env'))
            store.reset()
            store.reset()
            self.assertEqual(store.load(defaults), (defaults, 'env'))
            self.assertEqual(store.saved(), {})


class AdminServerTests(unittest.TestCase):
    """The real HTTP server around an AdapterRuntime without Bluetooth workers."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.recordings = root / 'recordings'
        self.recordings.mkdir()
        (self.recordings / 'ride.csv').write_text(CSV)
        self.registry = DeviceRegistry(root / 'devices.json')
        self.store = SettingsStore(root / 'coach.db')
        self.runtime = AdapterRuntime(EnvConfig(history_db=Path(self.recordings) / 'coach.db', record_dir=self.recordings), Settings(mode='SIMULATOR'),
                                      store=self.store, registry=self.registry, start_workers=False).start()
        self.httpd = make_server('127.0.0.1', 0, self.runtime)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.temp.cleanup()

    def call(self, method, path, body=None, raw=None, content_type='application/json'):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = Request(self.base + path, data=data, method=method, headers={'Content-Type': content_type})
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_switch_to_replay_and_back(self):
        self.assertEqual(self.call('GET', '/telemetry')[1]['source'], 'SIMULATOR')
        status, result = self.call('POST', '/admin/settings',
                                   {'mode': 'REPLAY', 'replayFile': str(self.recordings / 'ride.csv')})
        self.assertEqual((status, result['source'], result['settings']['mode']), (200, 'saved', 'REPLAY'))
        telemetry = self.call('GET', '/telemetry')[1]
        self.assertEqual((telemetry['source'], telemetry['mode'], telemetry['powerWatts']), ('REPLAY', 'REPLAY', 100))
        self.assertEqual(self.call('GET', '/replay/state')[1]['durationSeconds'], 2.0)
        self.assertTrue(self.store.path.exists())
        status, result = self.call('POST', '/admin/settings/reset')
        self.assertEqual((result['source'], result['settings']['mode']), ('env', 'SIMULATOR'))
        self.assertEqual(self.store.saved(), {})
        self.assertEqual(self.call('GET', '/telemetry')[1]['source'], 'SIMULATOR')

    def test_saved_settings_survive_a_restart(self):
        self.call('POST', '/admin/settings', {'mode': 'REPLAY', 'replayFile': str(self.recordings / 'ride.csv')})
        again = AdapterRuntime(EnvConfig(history_db=Path(self.recordings) / 'coach.db', record_dir=self.recordings), Settings(mode='SIMULATOR'),
                               store=self.store, start_workers=False).start()
        self.assertEqual((again.settings.mode, again.source), ('REPLAY', 'saved'))

    def test_bad_change_keeps_the_running_configuration(self):
        for body in ({'mode': 'REPLAY', 'replayFile': '/missing.csv'}, {'mode': 'MOON'}, {'hrEnabled': 'yes'}):
            with self.subTest(body=body), self.assertRaises(HTTPError) as ctx:
                self.call('POST', '/admin/settings', body)
            self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(self.call('GET', '/admin/settings')[1]['settings']['mode'], 'SIMULATOR')
        self.assertEqual(self.store.saved(), {})

    def test_replay_a_recording_of_the_folder_and_no_uploads(self):
        # Replays are opened from Sessions or Routes; uploading a CSV from elsewhere is gone (17-11)
        self.assertEqual(self.call('POST', '/admin/settings', {'mode': 'REPLAY', 'replayFile': 'ride.csv'})[0], 200)
        for method, path in (('GET', '/admin/recordings'), ('POST', '/admin/recordings?name=x.csv')):
            with self.subTest(path=path), self.assertRaises(HTTPError) as ctx:
                self.call(method, path, raw=CSV.encode() if method == 'POST' else None, content_type='text/csv')
            self.assertEqual(ctx.exception.code, 404)

    def test_describe(self):
        data = self.call('GET', '/admin/settings')[1]
        self.assertEqual(data['modes'], ['SIMULATOR', 'WAHOO', 'REPLAY'])
        self.assertFalse(data['controlTestEnabled'])
        self.assertEqual(data['envDefaults']['mode'], 'SIMULATOR')

    def test_gear_endpoint(self):
        with self.assertRaises(HTTPError) as ctx:                               # SIMULATOR: no shifting
            self.call('POST', '/gear', {'delta': 1})
        self.assertEqual(ctx.exception.code, 409)
        self.call('POST', '/admin/settings', {'mode': 'REPLAY', 'replayFile': str(self.recordings / 'ride.csv')})
        status, data = self.call('POST', '/gear', {'delta': 1})               # REPLAY: display only
        self.assertEqual((status, data['requestedGear'], data['gearControlMode']), (200, 13, 'DISPLAY_ONLY'))
        with self.assertRaises(HTTPError) as ctx:
            self.call('POST', '/gear', {'delta': 'up'})
        self.assertEqual(ctx.exception.code, 400)

    def test_forget_device(self):
        self.registry.remember('zwift_left', Classified('zwift', 'L', 'Zwift Click', side='left'))
        status, data = self.call('DELETE', '/devices/zwift_left')
        self.assertEqual((status, data['remembered']), (200, {}))
        with self.assertRaises(HTTPError) as ctx:
            self.call('DELETE', '/devices/bike')
        self.assertEqual(ctx.exception.code, 404)


class ControlTestPinsSettings(unittest.TestCase):
    def test_admin_cannot_leave_the_control_test_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = AdapterRuntime(EnvConfig(history_db=Path(folder) / 'coach.db', control_test=True, record_dir=Path(folder)),
                                     Settings(mode='WAHOO', record_enabled=True, record_seconds=600),
                                     start_workers=False).start()
            with self.assertRaises(PermissionError):
                runtime.update({'mode': 'SIMULATOR'})
            self.assertEqual(runtime.settings.mode, 'WAHOO')


if __name__ == '__main__':
    unittest.main()


class DataHomeTests(unittest.TestCase):
    def test_default_is_next_to_the_version_folders(self):
        from unittest.mock import patch
        from coach.app.paths import PROJECT_ROOT, data_file, data_home, recordings_dir
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(data_home(), PROJECT_ROOT.parent / 'ai-cycling-coach-data')
            self.assertEqual(recordings_dir(), data_home() / 'recordings')
            self.assertEqual(data_file('devices.json', 'DEVICES_FILE'), data_home() / 'devices.json')
        with patch.dict('os.environ', {'AI_COACH_HOME': '/tmp/x', 'DEVICES_FILE': '/tmp/d.json'}, clear=True):
            self.assertEqual(data_home(), Path('/tmp/x'))
            self.assertEqual(data_file('devices.json', 'DEVICES_FILE'), Path('/tmp/d.json'))

    def test_legacy_migration_copies_missing_files_only(self):
        from coach.app.paths import migrate_legacy_home
        with tempfile.TemporaryDirectory() as folder:
            legacy, target = Path(folder) / 'legacy', Path(folder) / 'new'
            (legacy / 'recordings').mkdir(parents=True)
            (legacy / 'profile.json').write_text('old profile')
            (legacy / 'recordings' / 'ride.csv').write_text(CSV)
            (legacy / 'settings.json.tmp').write_text('half written')
            target.mkdir()
            (target / 'profile.json').write_text('new profile')
            copied = migrate_legacy_home(legacy, target)
            self.assertEqual([p.relative_to(target).as_posix() for p in copied], ['recordings/ride.csv'])
            self.assertEqual((target / 'profile.json').read_text(), 'new profile')   # never overwritten
            self.assertTrue((legacy / 'profile.json').exists())                       # never deleted
            self.assertEqual(migrate_legacy_home(legacy, target), [])                 # idempotent
            (target / 'profile.json').unlink()                                       # moved into coach.db…
            (target / 'coach.db').write_bytes(b'')
            self.assertEqual(migrate_legacy_home(legacy, target), [])                 # …so the old one stays away
            self.assertFalse((target / 'profile.json').exists())
