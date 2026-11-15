"""GPX routes: reading, profile, store, riding them on the virtual road, and the HTTP API."""
import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.app.routes_store import list_routes, load_route, save_upload
from coach.session.route import RouteError, STEP_M, haversine_m, parse_gpx
from coach.session.virtual_ride import VirtualRide

M_PER_DEG_LAT = math.pi * 6_371_000 / 180


def segments_profile(segments, step=20.0, noise=0.0, seed=1):
    """[(length m, grade %)] → [(distance, elevation)] every ``step`` m, with optional GPS-like noise."""
    rnd = random.Random(seed)
    points, d, e = [(0.0, 100.0)], 0.0, 100.0
    for length, grade in segments:
        for _ in range(int(length // step)):
            d += step
            e += step * grade / 100
            points.append((d, e))
    return [(d, e + (rnd.uniform(-noise, noise) if noise else 0)) for d, e in points]


def gpx(profile, version='1.1', kind='trk', name='Test climb', with_ele=True):
    ns = {'1.1': 'http://www.topografix.com/GPX/1/1', '1.0': 'http://www.topografix.com/GPX/1/0'}[version]
    pts = []
    for d, e in profile:
        lat = 40.0 + d / M_PER_DEG_LAT                 # along a meridian: distance is exact
        ele = f'<ele>{e:.2f}</ele>' if with_ele else ''
        tag = 'trkpt' if kind == 'trk' else 'rtept'
        pts.append(f'<{tag} lat="{lat:.7f}" lon="-3.7">{ele}</{tag}>')
    body = (f'<trk><name>{name}</name><trkseg>{"".join(pts)}</trkseg></trk>' if kind == 'trk'
            else f'<rte><name>{name}</name>{"".join(pts)}</rte>')
    return f'<?xml version="1.0" encoding="UTF-8"?><gpx version="{version}" xmlns="{ns}">{body}</gpx>'.encode()


CLIMB = [(1000, 0), (1000, 6), (500, -4)]


class ParseTests(unittest.TestCase):
    def test_distance_gain_and_grades(self):
        route = parse_gpx(gpx(segments_profile(CLIMB)), 'climb.gpx')
        self.assertAlmostEqual(route.distance_m, 2500, delta=5)
        self.assertAlmostEqual(route.gain_m, 60, delta=3)
        self.assertAlmostEqual(route.loss_m, 20, delta=3)
        self.assertAlmostEqual(route.grade_at(1500), 6, delta=0.2)
        self.assertAlmostEqual(route.grade_at(500), 0, delta=0.2)
        self.assertAlmostEqual(route.grade_at(2300), -4, delta=0.2)
        self.assertIsNone(route.grade_at(2600))      # after the end
        self.assertEqual(route.name, 'Test climb')

    def test_gps_noise_is_smoothed(self):
        route = parse_gpx(gpx(segments_profile(CLIMB, noise=1.5)), 'noisy.gpx')
        flat = [route.grade_at(d) for d in range(100, 900, 10)]
        climb = [route.grade_at(d) for d in range(1100, 1900, 10)]
        self.assertLess(max(abs(g) for g in flat), 3)            # raw ±1.5 m every 20 m would be ±15 %; 50 m smoothing: 5.5 %
        self.assertAlmostEqual(sum(climb) / len(climb), 6, delta=0.3)

    def test_gpx_1_0_and_route_points(self):
        for version, kind in (('1.0', 'trk'), ('1.1', 'rte')):
            with self.subTest(version=version, kind=kind):
                route = parse_gpx(gpx(segments_profile(CLIMB), version=version, kind=kind))
                self.assertAlmostEqual(route.distance_m, 2500, delta=5)

    def test_impossible_spikes_are_clipped_and_counted(self):
        profile = segments_profile([(1000, 0)])
        profile[25] = (profile[25][0], profile[25][1] + 200)     # a 200 m spike in the data
        route = parse_gpx(gpx(profile))
        self.assertLessEqual(max(route.grades), 30)
        self.assertGreaterEqual(min(route.grades), -30)
        self.assertGreater(route.clipped_steps, 0)

    def test_real_mountain_bike_descents_are_kept(self):
        route = parse_gpx(gpx(segments_profile([(500, 0), (400, -22), (500, 0)])))   # a -22 % MTB descent
        self.assertEqual(route.clipped_steps, 0)
        self.assertAlmostEqual(min(route.grades), -22, delta=0.5)

    def test_a_big_recording_with_extensions_is_read(self):
        profile = segments_profile([(25_000, 1), (25_000, -1)], step=5)                 # 10 000 points
        ext = '<time>2026-11-13T10:00:00Z</time><extensions><hr>140</hr><cad>85</cad><power>200</power>' + 'x' * 1300 + '</extensions>'
        data = gpx(profile).replace(b'</ele>', b'</ele>' + ext.encode())
        self.assertGreater(len(data), 10 * 1024 * 1024)                                 # bigger than the old 10 MB limit
        route = parse_gpx(data)
        self.assertAlmostEqual(route.distance_m, 50_000, delta=50)

    def test_refused_files(self):
        cases = {
            'no elevation': gpx(segments_profile(CLIMB), with_ele=False),
            'not xml': b'hello',
            'not gpx': b'<kml><Document/></kml>',
            'one point': gpx([(0, 100)]),
            'too short': gpx(segments_profile([(100, 0)])),
            'entity': b'<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY a "aaaa">]><gpx>&a;</gpx>',
        }
        for label, data in cases.items():
            with self.subTest(label=label), self.assertRaises(RouteError):
                parse_gpx(data)

    def test_a_route_that_starts_and_ends_climbing_keeps_its_grade(self):
        route = parse_gpx(gpx(segments_profile([(1000, 3)])))   # smoothing must not flatten the ends
        self.assertAlmostEqual(route.grades[0], 3, delta=0.1)
        self.assertAlmostEqual(route.grades[-1], 3, delta=0.1)

    def test_a_tiny_last_step_does_not_make_a_spike(self):
        profile = segments_profile([(1000, 3)])
        last_d, last_e = profile[-1]
        profile.append((last_d + 0.3, last_e - 0.5))            # 30 cm more, 50 cm lower: "-166 %"
        route = parse_gpx(gpx(profile))
        self.assertEqual(route.clipped_steps, 0)
        self.assertTrue(0 <= route.grades[-1] <= 4, route.grades[-1])

    def test_profile_for_the_chart(self):
        route = parse_gpx(gpx(segments_profile(CLIMB)))
        profile = route.profile(max_points=100)
        self.assertLessEqual(len(profile), 102)
        self.assertEqual(profile[0]['d'], 0)
        self.assertAlmostEqual(profile[-1]['d'], 2.5, delta=0.01)
        self.assertEqual(set(profile[0]), {'d', 'e', 'g'})

    def test_haversine(self):
        self.assertAlmostEqual(haversine_m(40, -3.7, 41, -3.7), M_PER_DEG_LAT, delta=1)
        self.assertEqual(STEP_M, 5)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / 'routes'

    def tearDown(self):
        self.temp.cleanup()

    def test_upload_list_and_never_overwrite(self):
        first = save_upload(self.folder, 'Puerto de Navacerrada.gpx', gpx(segments_profile(CLIMB)))
        second = save_upload(self.folder, 'Puerto de Navacerrada.gpx', gpx(segments_profile(CLIMB)))
        self.assertEqual((first['file'], second['file']), ('Puerto_de_Navacerrada.gpx', 'Puerto_de_Navacerrada_1.gpx'))
        listing = list_routes(self.folder)
        self.assertEqual({r['file'] for r in listing}, {first['file'], second['file']})
        self.assertTrue(all(r['valid'] for r in listing))
        self.assertAlmostEqual(listing[0]['elevationGainM'], 60, delta=3)

    def test_invalid_upload_is_not_stored(self):
        for name, data in (('x.gpx', b'<gpx/>'), ('x.csv', gpx(segments_profile(CLIMB))), ('x.gpx', b''),
                           ('x.gpx', b'0' * (10 * 1024 * 1024 + 1))):
            with self.subTest(name=name, size=len(data)), self.assertRaises(ValueError):
                save_upload(self.folder, name, data if len(data) < 10 * 1024 * 1024 else b'0' * (50 * 1024 * 1024 + 1))
        self.assertEqual(list(self.folder.glob('*')) if self.folder.exists() else [], [])

    def test_load_only_plain_names(self):
        save_upload(self.folder, 'a.gpx', gpx(segments_profile(CLIMB)))
        self.assertEqual(load_route(self.folder, 'a.gpx').file, 'a.gpx')
        for bad in ('../a.gpx', 'sub/a.gpx', 'a.csv', '', 'missing.gpx'):
            with self.subTest(bad=bad), self.assertRaises(FileNotFoundError):
                load_route(self.folder, bad)

    def test_a_broken_file_in_the_folder_is_listed_as_invalid(self):
        self.folder.mkdir(parents=True)
        (self.folder / 'broken.gpx').write_text('<gpx>')
        [entry] = list_routes(self.folder)
        self.assertFalse(entry['valid'])
        self.assertTrue(entry['error'])


class RideTheRouteTests(unittest.TestCase):
    def setUp(self):
        self.route = parse_gpx(gpx(segments_profile(CLIMB)), 'climb.gpx')
        self.ride = VirtualRide(80, 9.5)

    def ride_until(self, metres, power=250):
        while self.ride.route_progress_m() < metres and not self.ride.route_finished:
            self.ride.step(0.25, power)

    def test_the_grade_follows_the_route_by_distance(self):
        self.ride.start_route(self.route)
        self.ride_until(500)
        self.assertAlmostEqual(self.ride.road_grade, 0, delta=0.3)
        self.ride_until(1300)                                    # 300 m into the 6 % climb
        self.assertAlmostEqual(self.ride.road_grade, 6, delta=0.3)
        self.assertAlmostEqual(self.ride.target_grade, 6, delta=0.3)

    def test_entering_the_climb_is_gradual_never_a_wall(self):
        self.ride.start_route(self.route)
        self.ride_until(1000)
        start = self.ride.road_grade
        self.ride_until(1060)
        self.assertLess(self.ride.road_grade - start, 60 / 20 + 0.3)   # at most 1 % per 20 m

    def test_end_of_the_route_is_flat_and_finished(self):
        self.ride.start_route(self.route)
        self.ride_until(10_000)
        snap = self.ride.snapshot(250)
        self.assertTrue(snap['routeFinished'])
        self.assertEqual(snap['targetGradePercent'], 0.0)
        self.assertAlmostEqual(snap['routeProgressKm'], 2.5, delta=0.01)

    def test_manual_grade_refused_while_riding_a_route(self):
        self.ride.start_route(self.route)
        with self.assertRaises(PermissionError):
            self.ride.request(3)
        self.ride_until(1300)
        self.ride.stop_route()
        self.assertAlmostEqual(self.ride.target_grade, self.ride.road_grade, delta=0.1)  # no jump when leaving
        self.assertEqual(self.ride.request(3), 3.0)
        self.assertIsNone(self.ride.snapshot()['routeName'])

    def test_the_route_starts_where_the_rider_is(self):
        self.ride.request(2)
        for _ in range(400):
            self.ride.step(0.25, 250)
        self.assertGreater(self.ride.distance_m, 100)
        self.ride.start_route(self.route)
        self.assertEqual(self.ride.route_progress_m(), 0)


class RouteEndpointTests(unittest.TestCase):
    def setUp(self):
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        self.env = EnvConfig(record_dir=folder / 'rec', routes_dir=folder / 'routes')
        self.runtime = AdapterRuntime(self.env, Settings(mode='SIMULATOR'), start_workers=False).start()
        self.httpd = make_server('127.0.0.1', 0, self.runtime)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.runtime.shutdown()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.temp.cleanup()

    def call(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        headers = {'Content-Type': 'application/gpx+xml' if raw is not None else 'application/json'}
        with urlopen(Request(self.base + path, data=data, method=method, headers=headers), timeout=5) as r:
            return r.status, json.loads(r.read())

    def test_upload_choose_ride_and_leave(self):
        status, saved = self.call('POST', '/routes?name=climb.gpx', raw=gpx(segments_profile(CLIMB)))
        self.assertEqual((status, saved['file']), (201, 'climb.gpx'))
        listing = self.call('GET', '/routes')[1]
        self.assertEqual(([r['file'] for r in listing['routes']], listing['current'], listing['available']),
                         (['climb.gpx'], None, True))
        self.assertEqual(self.call('GET', '/route')[1], {'active': False})
        preview = self.call('GET', '/routes/climb.gpx')[1]                 # look before choosing
        self.assertAlmostEqual(preview['distanceKm'], 2.5, delta=0.01)
        self.assertGreater(len(preview['profile']), 10)
        for bad in ('/routes/nope.gpx', '/routes/..%2Fx.gpx'):
            with self.subTest(bad=bad), self.assertRaises(HTTPError) as ctx:
                self.call('GET', bad)
            self.assertEqual(ctx.exception.code, 404)
        self.call('POST', '/route/start', {'file': 'climb.gpx'})
        route = self.call('GET', '/route')[1]
        self.assertTrue(route['active'])
        self.assertGreater(len(route['profile']), 10)
        telemetry = self.call('GET', '/telemetry')[1]
        self.assertEqual((telemetry['routeName'], telemetry['routeDistanceKm']), ('Test climb', 2.5))
        with self.assertRaises(HTTPError) as ctx:                       # manual grade while on a route
            self.call('POST', '/grade', {'gradePercent': 3})
        self.assertEqual(ctx.exception.code, 409)
        self.call('POST', '/route/stop')
        self.assertEqual(self.call('POST', '/grade', {'gradePercent': 3})[1], {'targetGradePercent': 3.0})

    def test_errors(self):
        for method, path, body, raw, code in (
                ('POST', '/routes?name=x.gpx', None, b'<gpx/>', 400),
                ('POST', '/routes?name=x.txt', None, gpx(segments_profile(CLIMB)), 400),
                ('POST', '/route/start', {'file': 'nope.gpx'}, None, 404),
                ('POST', '/route/start', {'file': '../x.gpx'}, None, 404),
                ('POST', '/route/start', {'file': 3}, None, 400),
                ('POST', '/routes?name=huge.gpx', None, b'0' * (50 * 1024 * 1024 + 1), 400)):
            with self.subTest(path=path, body=body), self.assertRaises(HTTPError) as ctx:
                self.call(method, path, body, raw)
            self.assertEqual(ctx.exception.code, code)

    def test_real_trainer_without_gear_control_cannot_ride_routes(self):
        save_upload(self.env.routes_dir, 'climb.gpx', gpx(segments_profile(CLIMB)))
        self.runtime.state.mode = 'WAHOO'          # as WAHOO without gear control: no grade controller
        with self.assertRaises(HTTPError) as ctx:
            self.call('POST', '/route/start', {'file': 'climb.gpx'})
        self.assertEqual(ctx.exception.code, 409)
        self.assertFalse(self.call('GET', '/routes')[1]['available'])

    def test_session_csv_has_the_route_columns(self):
        from coach.session.session import SESSION_FIELDS
        self.assertIn('routeName', SESSION_FIELDS)
        self.assertIn('routeProgressKm', SESSION_FIELDS)


if __name__ == '__main__':
    unittest.main()
