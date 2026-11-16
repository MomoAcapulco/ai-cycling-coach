"""The route catalogue in the local database (coach/app/routes_store.py, ADR-003): names, deletions, generated routes."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coach.app import db
from coach.app.legacy_json import import_all
from coach.app.routes_store import delete_route, generate, list_routes, load_route, rename, save_upload
from tests.test_routes import CLIMB, gpx, segments_profile

OTHER = [(800, 0), (1200, 4)]


class RouteCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.routes = self.home / 'routes'
        self.db = db.migrate(self.home / 'coach.db')

    def tearDown(self):
        self.temp.cleanup()

    def rows(self):
        with db.opened(self.db) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute('SELECT * FROM routes ORDER BY created_utc, rowid')]

    def test_an_upload_is_catalogued_and_its_name_kept_in_the_database(self):
        save_upload(self.routes, 'climb.gpx', gpx(segments_profile(CLIMB)), self.db)
        [row] = self.rows()
        self.assertEqual((row['file'], row['gpx_name'], row['generated'], row['recorded']), ('climb.gpx', 'Test climb', 0, 0))
        self.assertAlmostEqual(row['distance_m'], 2500, delta=30)
        self.assertEqual(len(row['sha256']), 64)
        rename(self.routes, 'climb.gpx', 'Mi puerto', self.db)
        self.assertEqual(load_route(self.routes, 'climb.gpx', self.db).name, 'Mi puerto')
        self.assertEqual([r['name'] for r in list_routes(self.routes, self.db)], ['Mi puerto'])
        self.assertFalse((self.routes / 'names.json').exists())                # no file any more
        rename(self.routes, 'climb.gpx', '', self.db)                           # empty: the GPX's name again
        self.assertEqual(load_route(self.routes, 'climb.gpx', self.db).name, 'Test climb')
        self.assertEqual(len(self.rows()), 1)

    def test_a_new_gpx_with_the_name_of_a_deleted_one_starts_clean(self):
        save_upload(self.routes, 'ruta.gpx', gpx(segments_profile(CLIMB)), self.db)
        rename(self.routes, 'ruta.gpx', 'La antigua', self.db)
        delete_route(self.routes, 'ruta.gpx', self.db)
        save_upload(self.routes, 'ruta.gpx', gpx(segments_profile(OTHER), name='Otra'), self.db)
        self.assertEqual(load_route(self.routes, 'ruta.gpx', self.db).name, 'Otra')    # not «La antigua»
        old, new = self.rows()
        self.assertEqual((old['name'], old['deleted_utc'] is not None), ('La antigua', True))   # kept for its sessions
        self.assertEqual((new['name'], new['deleted_utc']), (None, None))

    def test_listing_catalogues_gpx_files_put_there_by_hand_once(self):
        self.routes.mkdir()
        (self.routes / 'a_mano.gpx').write_bytes(gpx(segments_profile(CLIMB)))
        list_routes(self.routes, self.db)
        list_routes(self.routes, self.db)
        self.assertEqual([r['file'] for r in self.rows()], ['a_mano.gpx'])

    def test_a_generated_route_keeps_its_settings(self):
        out = generate(self.routes, {'mode': 'custom', 'distanceKm': 10, 'gainM': 100, 'climbs': 1, 'avgGrade': 5, 'maxGrade': 8, 'save': True,
                                     'name': 'Prueba'}, self.db)
        [row] = self.rows()
        self.assertEqual((row['file'], row['generated']), (out['file'], 1))
        generator = json.loads(row['generator'])
        self.assertEqual((generator['mode'], generator['distanceKm'], generator['seed']), ('custom', 10, out['seed']))

    def test_names_json_of_the_previous_version_is_imported(self):
        save_upload(self.routes, 'cuna.gpx', gpx(segments_profile(CLIMB)), self.db)
        (self.routes / 'names.json').write_text(json.dumps({'cuna.gpx': 'Cuna de la Legión', 'gone.gpx': 'Borrada'}))
        with mock.patch.dict(os.environ, {'AI_COACH_HOME': str(self.home)}):
            for name in ('ROUTES_DIR', 'PROFILE_FILE', 'SETTINGS_FILE'):
                os.environ.pop(name, None)
            done = import_all(self.home, self.db)
        self.assertIn('imported 1 names, 1 without their GPX', done['route_names'])
        self.assertEqual(load_route(self.routes, 'cuna.gpx', self.db).name, 'Cuna de la Legión')
        self.assertFalse((self.routes / 'names.json').exists())
        self.assertEqual(len(list(self.home.glob('backup-json-*/routes/names.json'))), 1)


class SchemaV2Tests(unittest.TestCase):
    def test_a_v1_database_gets_the_new_routes_table_with_its_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'coach.db'
            with mock.patch.dict(db.MIGRATIONS, {1: db.MIGRATIONS[1]}, clear=True), mock.patch.object(db, 'SCHEMA_VERSION', 1):
                db._ready.clear()
                db.migrate(path)
            with db.opened(path) as conn:
                conn.execute("INSERT INTO routes (id, file, name) VALUES ('r1', 'cuna.gpx', 'Cuna')")
            db._ready.clear()
            db.migrate(path)
            self.assertEqual(db.meta(path, 'schema_version'), str(db.SCHEMA_VERSION))
            with db.opened(path) as conn:
                self.assertEqual(conn.execute('SELECT id, file, name, sha256 FROM routes').fetchall(),
                                 [('r1', 'cuna.gpx', 'Cuna', None)])
                conn.execute("INSERT INTO routes (id, file) VALUES ('r2', 'cuna.gpx')")   # same file: allowed now
            self.assertEqual(len(list(Path(folder).glob('coach.db.bak-v1-*'))), 1)


if __name__ == '__main__':
    unittest.main()
