"""Generated routes: custom parameters, «like a race», determinism, limits and the API."""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.session.route import parse_gpx
from coach.session.route_generator import GenerationError, find_climbs, generate_custom, generate_like, to_gpx

BASE = dict(distanceKm=60, gainM=1200, climbs=5, avgGrade=6, maxGrade=12, kicks=3, descentGrade=6)


class CustomTests(unittest.TestCase):
    def test_distance_gain_and_grades_as_asked(self):
        route, data, seed = generate_custom(BASE, 42)
        self.assertEqual(seed, 42)
        self.assertAlmostEqual(route.distance_m, 60000, delta=30)
        self.assertAlmostEqual(route.gain_m, 1200, delta=12)                   # as the Rutas page measures it
        self.assertLessEqual(max(route.grades), 12.5)
        self.assertGreater(max(route.grades), 9)                                # the hard ramps are there
        self.assertGreaterEqual(len(find_climbs(route)), 5)
        self.assertEqual(parse_gpx(data).gain_m, route.gain_m)                 # the GPX says the same

    def test_same_seed_same_route_other_seed_other_route(self):
        a, b, c = (generate_custom(BASE, s)[0] for s in (7, 7, 8))
        self.assertEqual(a.elevations, b.elevations)
        self.assertNotEqual(a.elevations, c.elevations)
        self.assertIsInstance(generate_custom(BASE)[2], int)                   # no seed: one is chosen and returned

    def test_flat_and_kicks_only(self):
        flat, _, _ = generate_custom({**BASE, 'gainM': 0, 'climbs': 0, 'kicks': 0}, 1)
        self.assertLess(flat.gain_m / 60, 3.5)                                  # rolling flats: under 3.5 m/km
        kicks, _, _ = generate_custom({**BASE, 'distanceKm': 20, 'gainM': 300, 'climbs': 0, 'kicks': 6}, 1)
        self.assertAlmostEqual(kicks.gain_m, 300, delta=6)

    def test_what_does_not_fit_or_is_wrong(self):
        with self.assertRaises(GenerationError) as ctx:
            generate_custom({**BASE, 'distanceKm': 20, 'gainM': 2000, 'avgGrade': 5}, 1)
        self.assertIn('No cabe', str(ctx.exception))
        for bad in ({'maxGrade': 4}, {'distanceKm': 500}, {'climbs': 2.5}, {'gainM': '1000'},
                    {'climbs': 0, 'kicks': 0}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                generate_custom({**BASE, **bad}, 1)


class LikeTests(unittest.TestCase):
    def setUp(self):
        race_params = dict(distanceKm=90, gainM=2000, climbs=8, avgGrade=7, maxGrade=16, kicks=0, descentGrade=8)
        route, data, _ = generate_custom(race_params, 11)
        self.race = parse_gpx(data, 'race.gpx')

    def test_shorter_with_the_same_character(self):
        route, _, _ = generate_like(self.race, 40, 3)
        self.assertAlmostEqual(route.distance_m, 40000, delta=40)
        per_km = lambda r: r.gain_m / r.distance_m * 1000   # noqa: E731
        self.assertAlmostEqual(per_km(route), per_km(self.race), delta=0.25 * per_km(self.race))
        self.assertAlmostEqual(max(route.grades), max(self.race.grades), delta=1.0)   # its real hardest climb
        self.assertGreaterEqual(len(find_climbs(route)), 2)

    def test_limits(self):
        with self.assertRaises(GenerationError):
            generate_like(self.race, 95, 1)                                        # longer than the race
        with self.assertRaises(GenerationError):
            generate_like(self.race, 5, 1)                                         # its hardest climb does not fit
        flat, _, _ = generate_custom({**BASE, 'gainM': 0, 'climbs': 0, 'kicks': 0}, 1)
        with self.assertRaises(GenerationError):
            generate_like(flat, 20, 1)                                             # nothing to imitate

    def test_find_climbs_ignores_small_dips(self):
        def climbs_with_dip(dip_m):
            segments = [(1000, 0), (1000, 5), (dip_m / 0.08, -8), (1000, 5), (2000, -5), (1000, 0)]
            return len(find_climbs(parse_gpx(to_gpx(segments, 'x'))))
        self.assertEqual(climbs_with_dip(8), 1)                                   # 8 m down in the middle: one climb
        self.assertEqual(climbs_with_dip(30), 2)                                  # 30 m down: two


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
        method = 'GET' if body is None else 'POST'
        data = None if body is None else json.dumps(body).encode()
        with urlopen(Request(self.base + path, data=data, method=method,
                             headers={'Content-Type': 'application/json'}), timeout=20) as r:
            return json.loads(r.read())

    def test_preview_then_save_then_like(self):
        preview = self.call('/routes/generate', {'mode': 'custom', **BASE})
        self.assertFalse(preview['saved'])
        self.assertEqual(self.call('/routes')['routes'], [])                     # a preview saves nothing
        saved = self.call('/routes/generate', {'mode': 'custom', **BASE, 'seed': preview['seed'], 'save': True})
        self.assertEqual((saved['saved'], saved['elevationGainM']), (True, preview['elevationGainM']))
        self.assertEqual(saved['file'], f'generada_60km_1200m_s{preview["seed"]}.gpx')
        again = self.call('/routes/generate', {'mode': 'custom', **BASE, 'seed': preview['seed'], 'save': True})
        self.assertNotEqual(again['file'], saved['file'])                        # never overwrites
        like = self.call('/routes/generate', {'mode': 'like', 'file': saved['file'], 'distanceKm': 30, 'save': True})
        self.assertTrue(like['file'].startswith('como_generada_60km'))
        self.assertEqual(len(self.call('/routes')['routes']), 3)

    def test_errors_are_explained(self):
        for body in ({'mode': 'custom', **BASE, 'distanceKm': 20, 'gainM': 2000, 'avgGrade': 5},
                     {'mode': 'like', 'file': '../etc/passwd.gpx', 'distanceKm': 30}, {'mode': 'other'}):
            with self.subTest(body=body), self.assertRaises(HTTPError) as ctx:
                self.call('/routes/generate', body)
            self.assertEqual(ctx.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
