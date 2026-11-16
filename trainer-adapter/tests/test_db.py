"""coach/app/db.py: the local database (ADR-003), its migrations and the copy of the old history.db."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coach.app import db
from coach.history.store import COLUMNS, HistoryStore

TABLES = {'meta', 'activities', 'profile', 'profile_versions', 'settings', 'sessions', 'routes', 'session_routes',
          'goals', 'event_results', 'ftp_tests', 'ftp_estimates', 'ai_recommendations', 'health_days',
          'availability', 'sharing_consents', 'sharing_exclusions'}


def tables(path):
    with db.opened(path) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def old_history(path: Path, ids):
    """A history.db as v4.3.0 wrote it: only the columns it knew (no uuid, sensations, deleted_utc)."""
    old = [(n, t) for n, t in COLUMNS if n not in ('uuid', 'sensations', 'deleted_utc')]
    with db.opened(path) as conn:
        conn.execute(f"CREATE TABLE activities ({', '.join(f'{n} {t}' for n, t in old)})")
        for i, activity_id in enumerate(ids):
            conn.execute('INSERT INTO activities (id, source, type, start_utc, rpe, feeling) VALUES (?, ?, ?, ?, ?, ?)',
                         (activity_id, 'strava', 'ride', f'2026-10-{i + 1:02d}T08:00:00+00:00', 6, 'nota privada'))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        db._ready.clear()

    def tearDown(self):
        self.temp.cleanup()

    def test_a_new_database_has_every_table_and_its_version(self):
        path = db.migrate(self.folder / 'coach.db')
        self.assertTrue(TABLES <= tables(path))
        self.assertEqual(db.meta(path, 'schema_version'), str(db.SCHEMA_VERSION))
        self.assertEqual(len(db.meta(path, 'install_id')), 36)            # a UUID
        install = db.meta(path, 'install_id')
        db._ready.clear()
        db.migrate(path)                                                   # opening again changes nothing
        self.assertEqual(db.meta(path, 'install_id'), install)

    def test_the_old_history_is_copied_once_and_left_as_it_was(self):
        legacy = self.folder / 'history.db'
        old_history(legacy, ['strava:1', 'strava:2', 'app:session_20261113_130000'])
        before = legacy.read_bytes()
        path = db.migrate(self.folder / 'coach.db')
        with db.opened(path) as conn:
            rows = conn.execute('SELECT id, uuid, rpe, feeling FROM activities ORDER BY id').fetchall()
        self.assertEqual([r[0] for r in rows], ['app:session_20261113_130000', 'strava:1', 'strava:2'])
        self.assertEqual(len({r[1] for r in rows}), 3)                     # each one its own UUID
        self.assertEqual((rows[1][2], rows[1][3]), (6, 'nota privada'))   # local keeps everything, notes too
        self.assertEqual(legacy.read_bytes(), before)
        self.assertIn('3 activities', db.meta(path, 'legacy_history_imported'))
        old_history(self.folder / 'other.db', ['strava:9'])                # a later change of history.db...
        db._ready.clear()
        db.migrate(path)
        with db.opened(path) as conn:                                # ...is not imported again
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM activities').fetchone()[0], 3)

    def test_a_damaged_old_history_does_not_stop_the_app(self):
        (self.folder / 'history.db').write_bytes(b'not a database at all' * 100)
        path = db.migrate(self.folder / 'coach.db')
        self.assertIn('0 activities', db.meta(path, 'legacy_history_imported'))
        self.assertEqual((self.folder / 'history.db').read_bytes()[:21], b'not a database at all')

    def test_the_history_store_uses_the_new_database(self):
        old_history(self.folder / 'history.db', ['strava:1'])
        store = HistoryStore(self.folder / 'coach.db')
        self.assertTrue(store.has('strava:1'))
        store.add({'id': 'app:session_20261116_100000', 'source': 'app', 'type': 'virtual_ride',
                   'start_utc': '2026-11-16T10:00:00+00:00'})
        added = [a for a in store.list() if a['id'] == 'app:session_20261116_100000'][0]
        self.assertEqual(len(added['uuid']), 36)

    def test_a_database_from_an_older_version_is_copied_before_migrating(self):
        path = db.migrate(self.folder / 'coach.db')

        current, following = db.SCHEMA_VERSION, db.SCHEMA_VERSION + 1

        def next_one(conn):
            conn.execute('CREATE TABLE extra (id TEXT PRIMARY KEY)')
        with mock.patch.dict(db.MIGRATIONS, {following: next_one}), mock.patch.object(db, 'SCHEMA_VERSION', following):
            db._ready.clear()
            db.migrate(path)
        self.assertIn('extra', tables(path))
        self.assertEqual(db.meta(path, 'schema_version'), str(following))
        backups = list(self.folder.glob(f'coach.db.bak-v{current}-*'))
        self.assertEqual(len(backups), 1)
        self.assertNotIn('extra', tables(backups[0]))                      # the copy is the database before

    def test_a_failed_migration_leaves_the_database_as_it_was(self):
        path = db.migrate(self.folder / 'coach.db')

        def broken(conn):
            conn.execute('CREATE TABLE half (id TEXT)')
            raise RuntimeError('boom')
        following = db.SCHEMA_VERSION + 1
        with mock.patch.dict(db.MIGRATIONS, {following: broken}), mock.patch.object(db, 'SCHEMA_VERSION', following):
            db._ready.clear()
            with self.assertRaises(RuntimeError):
                db.migrate(path)
        self.assertEqual(db.meta(path, 'schema_version'), str(following - 1))
        self.assertNotIn('half', tables(path))

    def test_a_database_from_a_newer_app_is_not_touched(self):
        path = db.migrate(self.folder / 'coach.db')
        with db.opened(path) as conn:
            conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
        db._ready.clear()
        with self.assertRaises(db.NewerDatabase):
            db.migrate(path)

    def test_deleting_an_activity_takes_its_session_rows_with_it(self):
        path = db.migrate(self.folder / 'coach.db')
        with db.opened(path) as conn:
            conn.execute("INSERT INTO activities (id, uuid, source, type) VALUES ('app:s', 'u', 'app', 'virtual_ride')")
            conn.execute("INSERT INTO sessions (activity_id, csv) VALUES ('app:s', 's.csv')")
            conn.execute("INSERT INTO sharing_exclusions VALUES ('app:s', '2026-11-16T10:00:00+00:00')")
            conn.execute("DELETE FROM activities WHERE id = 'app:s'")
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sharing_exclusions').fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):               # no session without its activity
                conn.execute("INSERT INTO sessions (activity_id) VALUES ('app:none')")


if __name__ == '__main__':
    unittest.main()
