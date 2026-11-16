"""Replay of a recorded GPX (one of your rides), and deleting routes and sessions to the trash."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.session.gpx_activity import NotEnoughData, build_replay
from coach.session.recording import CsvReplay
from coach.session.route import parse_gpx
from tests.test_fit_export import row as csv_row, write_session

T0 = datetime(2026, 5, 9, 6, 0, tzinfo=timezone.utc)


def recorded_gpx(seconds=600, timed=True, hr=True):
    """A ride heading north at ~5 m/s, climbing 1 m every 10 s, with time (and heart rate) on every point."""
    points = []
    for s in range(seconds):
        time = f'<time>{(T0 + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")}</time>' if timed else ''
        ext = (f'<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>{130 + s % 10}</gpxtpx:hr>'
               f'<gpxtpx:cad>85</gpxtpx:cad></gpxtpx:TrackPointExtension></extensions>') if hr else ''
        points.append(f'<trkpt lat="{40 + s * 5 / 111195:.7f}" lon="-3.0"><ele>{600 + s / 10:.1f}</ele>{time}{ext}</trkpt>')
    return ('<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1" '
            'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"><trk><name>Mi salida</name><trkseg>'
            + ''.join(points) + '</trkseg></trk></gpx>').encode()


class GpxReplayTests(unittest.TestCase):
    def test_a_recorded_ride_plays_like_a_session(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'ride.gpx').write_bytes(recorded_gpx())
            route = parse_gpx((folder / 'ride.gpx').read_bytes(), 'ride.gpx')
            self.assertEqual(route.timed_points, 600)
            name = build_replay(route, folder / 'ride.gpx', folder / 'rec')
            self.assertEqual(name, 'gpx_ride.csv')
            replay = CsvReplay(folder / 'rec' / name)
            series = replay.series()
            self.assertEqual((replay.duration, series['routes'][0]['file']), (599.0, 'ride.gpx'))
            middle = series['samples'][300]
            self.assertAlmostEqual(middle['speed'], 18.0, delta=0.3)          # 5 m/s
            self.assertAlmostEqual(middle['grade'], 2.0, delta=0.3)           # 0.1 m per 5 m
            self.assertEqual((middle['heart'], middle['cadence'], middle['power']), (130.0, 85.0, None))
            reading = replay.snapshot()                                        # what /telemetry serves
            self.assertIsInstance(reading['heartRateBpm'], int)
            meta = json.loads((folder / 'rec' / 'gpx_ride.json').read_text())
            self.assertEqual(meta['sensors'], ['hr', 'cad'])
            mtime = (folder / 'rec' / name).stat().st_mtime
            build_replay(route, folder / 'ride.gpx', folder / 'rec')                # reused while the GPX is the same
            self.assertEqual((folder / 'rec' / name).stat().st_mtime, mtime)

    def test_a_replay_written_with_decimal_sensors_still_plays(self):
        # gpx_*.csv converted before the fix carry '103.0': /telemetry crashed and the Java API said "offline".
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'ride.gpx').write_bytes(recorded_gpx())
            route = parse_gpx((folder / 'ride.gpx').read_bytes(), 'ride.gpx')
            path = folder / 'rec' / build_replay(route, folder / 'ride.gpx', folder / 'rec')
            lines = path.read_text().splitlines()
            header = lines[0].split(',')
            for column in ('heartRateBpm', 'cadenceRpm'):
                i = header.index(column)
                lines[1:] = [','.join(c + '.0' if n == i and c else c for n, c in enumerate(l.split(',')))
                             for l in lines[1:]]
            path.write_text('\n'.join(lines) + '\n')
            reading = CsvReplay(path).snapshot()
            self.assertIsInstance(reading['heartRateBpm'], int)

    def test_the_replay_shows_distance_altitude_and_climbing(self):
        # The Panel said «Desnivel —» in every replay: the snapshot carried no altitude and no climbing.
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'ride.gpx').write_bytes(recorded_gpx())                 # 60 m up in 3 km
            route = parse_gpx((folder / 'ride.gpx').read_bytes(), 'ride.gpx')
            replay = CsvReplay(folder / 'rec' / build_replay(route, folder / 'ride.gpx', folder / 'rec'))
            start = replay.snapshot()
            self.assertEqual(start['elevationGainM'], 0)
            replay.control('seek', replay.duration)
            end = replay.snapshot()
            self.assertAlmostEqual(end['elevationGainM'], 60, delta=6)
            self.assertAlmostEqual(end['rideDistanceKm'], 3.0, delta=0.1)
            self.assertIsNotNone(end['altitudeM'])

    def test_a_session_replay_uses_its_recorded_climbing(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write_session(folder, [csv_row(t, elevationGainM=f'{t * 0.05:.1f}') for t in range(120)])
            replay = CsvReplay(folder / 'session_20261113_130000.csv')
            replay.control('seek', 100)
            self.assertEqual(replay.snapshot()['elevationGainM'], 5.0)

    def test_a_planned_route_has_no_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for data, why in ((recorded_gpx(timed=False), 'ruta planificada'), (recorded_gpx(seconds=50), 'puntos')):
                (folder / 'r.gpx').write_bytes(data)
                with self.subTest(why=why), self.assertRaises(NotEnoughData) as ctx:
                    build_replay(parse_gpx(data, 'r.gpx'), folder / 'r.gpx', folder / 'rec')
                self.assertIn(why, str(ctx.exception))


class ApiTests(unittest.TestCase):
    def setUp(self):
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder / 'routes').mkdir()
        (self.folder / 'rec').mkdir()
        self.runtime = AdapterRuntime(EnvConfig(record_dir=self.folder / 'rec', routes_dir=self.folder / 'routes',
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

    def call(self, path, body=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        method = method or ('GET' if body is None else 'POST')
        with urlopen(Request(self.base + path, data=data, method=method,
                             headers={'Content-Type': 'application/json'}), timeout=20) as r:
            return json.loads(r.read())

    def error(self, path, body=None, method=None):
        with self.assertRaises(HTTPError) as ctx:
            self.call(path, body, method)
        return ctx.exception

    def test_replay_of_a_recorded_route(self):
        (self.folder / 'routes' / 'mine.gpx').write_bytes(recorded_gpx())
        (self.folder / 'routes' / 'plan.gpx').write_bytes(recorded_gpx(timed=False))
        listed = {r['file']: r for r in self.call('/routes')['routes']}
        self.assertEqual((listed['mine.gpx']['recorded'], listed['plan.gpx']['recorded']), (True, False))
        self.assertEqual(self.call('/routes/mine.gpx/replay', {}), {'replayFile': 'gpx_mine.csv'})
        self.call('/admin/settings', {'mode': 'REPLAY', 'replayFile': 'gpx_mine.csv'})
        self.assertEqual(self.call('/replay/session')['routes'][0]['file'], 'mine.gpx')
        error = self.error('/routes/plan.gpx/replay', {})
        self.assertEqual(error.code, 409)
        self.assertIn('Datos insuficientes', error.reason)
        self.assertEqual(self.error('/routes/nope.gpx/replay', {}).code, 404)

    def test_delete_route_and_session_to_the_trash(self):
        (self.folder / 'routes' / 'mine.gpx').write_bytes(recorded_gpx())
        self.call('/routes/rename', {'file': 'mine.gpx', 'name': 'La mía'})
        self.assertEqual(self.call('/routes/mine.gpx', method='DELETE')['deleted'], 'mine.gpx')
        self.assertEqual(self.call('/routes')['routes'], [])
        self.assertTrue((self.folder / 'routes' / '.papelera' / 'mine.gpx').is_file())   # recoverable
        self.assertEqual(self.error('/routes/mine.gpx', method='DELETE').code, 404)

        write_session(self.folder / 'rec', [csv_row(t) for t in range(60)])
        stem = 'session_20261113_130000'
        self.assertEqual(len(self.call('/history')['activities']), 1)
        self.assertEqual(self.call(f'/sessions/{stem}', method='DELETE')['deleted'], stem)
        self.assertEqual(self.call('/sessions')['sessions'], [])
        self.assertEqual(self.call('/history')['activities'], [])                      # out of the history too
        self.assertTrue((self.folder / 'rec' / '.papelera' / f'{stem}.csv').is_file())
        for bad in ('/sessions/../h.db', '/sessions/session_1'):
            self.assertEqual(self.error(bad, method='DELETE').code, 404)

    def test_what_is_in_use_is_not_deleted(self):
        route = self.call('/routes/generate', {'mode': 'custom', 'distanceKm': 10, 'gainM': 100, 'climbs': 1,
                                               'avgGrade': 5, 'maxGrade': 8, 'save': True})
        self.call('/route/start', {'file': route['file']})
        self.assertEqual(self.error(f'/routes/{route["file"]}', method='DELETE').code, 409)
        stem = self.runtime.session.start()['session']
        self.assertEqual(self.error(f'/sessions/{stem}', method='DELETE').code, 409)


if __name__ == '__main__':
    unittest.main()
