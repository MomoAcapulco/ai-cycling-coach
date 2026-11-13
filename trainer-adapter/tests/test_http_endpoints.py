"""HTTP contract of the adapter, against a real server on a free local port."""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.bluetooth.device_registry import DeviceRegistry
from coach.bluetooth.discovery import Classified
from coach.session.recording import CsvReplay
from coach.app.server import AdapterState, make_server

CSV = ('elapsedSeconds,source,powerWatts,cadenceRpm,speedKph,connected,status,heartRateBpm,heartRateConnected,targetGradePercent\n'
       '0,WAHOO,100,60,15,true,STREAMING,120,true,\n'
       '2,WAHOO,200,70,18,true,STREAMING,140,true,2\n')


class ServerFixture:
    def __init__(self, state):
        self.httpd = make_server('127.0.0.1', 0, state)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def get(self, path):
        with urlopen(self.base + path, timeout=5) as response:
            return response.status, json.loads(response.read())

    def post(self, path, body, raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        request = Request(self.base + path, data=data, method='POST',
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())


class ReplayModeEndpoints(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / 'ride.csv'
        path.write_text(CSV)
        self.now = [0.0]
        replay = CsvReplay(path, clock=lambda: self.now[0])
        self.server = ServerFixture(AdapterState(mode='REPLAY', replay=replay))

    def tearDown(self):
        self.server.close()
        self.temp.cleanup()

    def test_telemetry_comes_from_the_recording(self):
        status, data = self.server.get('/telemetry')
        self.assertEqual(status, 200)
        self.assertEqual(data['source'], 'REPLAY')
        self.assertEqual(data['powerWatts'], 100)
        self.assertEqual(data['heartRateBpm'], 120)
        self.assertEqual(data['virtualGear'], 12)
        self.assertEqual(data['gearControlMode'], 'DISPLAY_ONLY')

    def test_query_string_is_ignored(self):
        self.assertEqual(self.server.get('/telemetry?cache=1')[0], 200)

    def test_health(self):
        _, data = self.server.get('/health')
        self.assertEqual(data, {'status': 'UP', 'mode': 'REPLAY', 'trainerConnected': True,
                                'trainerStatus': 'REPLAY'})

    def test_session_and_state(self):
        _, session = self.server.get('/replay/session')
        self.assertEqual(len(session['samples']), 2)
        self.assertEqual(session['gradeKind'], 'ORDERED_NOT_MEASURED')
        _, state = self.server.get('/replay/state')
        self.assertEqual(state['durationSeconds'], 2.0)

    def test_seek_then_telemetry(self):
        status, result = self.server.post('/replay/control', {'action': 'seek', 'value': 2})
        self.assertEqual(status, 200)
        self.assertEqual(result['positionSeconds'], 2.0)
        self.assertEqual(self.server.get('/telemetry')[1]['powerWatts'], 200)

    def test_virtual_gear(self):
        self.assertEqual(self.server.post('/replay/gear', {'delta': 1})[1]['virtualGear'], 13)
        self.assertEqual(self.server.get('/telemetry')[1]['virtualGear'], 13)

    def test_bad_requests_are_400(self):
        cases = [
            ('/replay/gear', {'delta': 'up'}, None),
            ('/replay/gear', {'delta': 1.0}, None),
            ('/replay/gear', {'delta': 5}, None),
            ('/replay/control', {'action': 'fly'}, None),
            ('/replay/control', {'action': 'speed', 'value': 30}, None),
            ('/replay/control', None, b'[1, 2]'),
            ('/replay/control', None, b'{not json'),
            ('/replay/control', None, b'\xff\xfe'),
        ]
        for path, body, raw in cases:
            with self.subTest(path=path, body=body, raw=raw):
                with self.assertRaises(HTTPError) as ctx:
                    self.server.post(path, body, raw)
                self.assertEqual(ctx.exception.code, 400)

    def test_unknown_paths_are_404(self):
        with self.assertRaises(HTTPError) as ctx:
            self.server.get('/nope')
        self.assertEqual(ctx.exception.code, 404)
        with self.assertRaises(HTTPError) as ctx:
            self.server.post('/nope', {})
        self.assertEqual(ctx.exception.code, 404)


class LiveModeEndpoints(unittest.TestCase):
    def test_simulator_rejects_replay_endpoints_with_409(self):
        server = ServerFixture(AdapterState(mode='SIMULATOR'))
        try:
            self.assertEqual(server.get('/telemetry')[1]['source'], 'SIMULATOR')
            for call in (lambda: server.get('/replay/session'),
                         lambda: server.get('/replay/state'),
                         lambda: server.post('/replay/control', {'action': 'play'}),
                         lambda: server.post('/replay/gear', {'delta': 1})):
                with self.assertRaises(HTTPError) as ctx:
                    call()
                self.assertEqual(ctx.exception.code, 409)
        finally:
            server.close()

    def test_wahoo_mode_reports_waiting_and_disabled_hr(self):
        server = ServerFixture(AdapterState(mode='WAHOO'))
        try:
            data = server.get('/telemetry')[1]
            self.assertEqual(data['source'], 'WAHOO')
            self.assertFalse(data['connected'])
            self.assertEqual(data['status'], 'WAITING')
            self.assertEqual(data['powerWatts'], 0)
            self.assertEqual(data['heartRateStatus'], 'DISABLED')
        finally:
            server.close()

    def test_wahoo_mode_serves_live_store_values(self):
        state = AdapterState(mode='WAHOO', hr_enabled=True)
        state.store.update({'powerWatts': 180, 'cadenceRpm': 85.5, 'speedKph': 31.2})
        state.hr_store.update({'heartRateBpm': 141})
        server = ServerFixture(state)
        try:
            data = server.get('/telemetry')[1]
            self.assertEqual((data['powerWatts'], data['cadenceRpm'], data['speedKph']), (180, 85.5, 31.2))
            self.assertEqual(data['heartRateBpm'], 141)
            self.assertEqual(data['status'], 'STREAMING')
        finally:
            server.close()

    def test_devices_lists_the_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = DeviceRegistry(Path(folder) / 'devices.json')
            registry.remember('trainer', Classified('trainer', 'KICKR-ID', 'KICKR CORE 5A'))
            server = ServerFixture(AdapterState(mode='SIMULATOR', registry=registry))
            try:
                data = server.get('/devices')[1]
                self.assertEqual(data['remembered']['trainer']['address'], 'KICKR-ID')
                self.assertEqual(data['registryFile'], str(registry.path))
                self.assertIn('zwiftLeftStatus', data['controllers'])
            finally:
                server.close()

    def test_state_validation(self):
        with self.assertRaises(ValueError):
            AdapterState(mode='REPLAY')
        with self.assertRaises(ValueError):
            AdapterState(mode='ZWIFT')


if __name__ == '__main__':
    unittest.main()
