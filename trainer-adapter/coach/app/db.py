"""The local database, ``coach.db`` in the data home (docs/adr/ADR-003-base-de-datos.md).

Everything the rider does is kept here, complete: only the rider has access. What may leave for the central app
(docs/PENDIENTES-sin-rodillo.md, 10d) is prepared apart, with permission; it never changes what is stored here.

- ``meta.schema_version`` says which migrations have run. Each one runs once, in order, in a transaction, when the
  database is opened; before migrating an existing database a copy is made (``coach.db.bak-v<n>-<time>``).
- A database written by a NEWER version of the app is not touched (it could lose what it does not know).
- Activities keep their stable id (``app:…``, ``strava:…``, ``fit:…``): it is what stops an import from duplicating.
  Every other row has a UUID, so they never clash with other riders' data. The installation has its own
  ``install_id``; the donor id for sharing (10d) is another one, created only when sharing for the first time.
- Until v4.3.0 the history lived in ``history.db``: when ``coach.db`` is created, its activities are copied once
  (``history.db`` is left as it is, as a backup).
"""
import sqlite3
from contextlib import contextmanager
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

DB_NAME = 'coach.db'
LEGACY_HISTORY = 'history.db'

_lock = Lock()
_ready = set()          # paths already migrated by this process


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def new_id() -> str:
    return str(uuid.uuid4())


def default_path() -> Path:
    """``coach.db`` in the data home; COACH_DB (or the old HISTORY_DB) points elsewhere."""
    import os
    from coach.app.paths import data_home
    override = os.environ.get('COACH_DB') or os.environ.get('HISTORY_DB')
    return Path(override).expanduser() if override else data_home() / DB_NAME


def open_default() -> Path:
    """The rider's database, up to date, with the JSON files of earlier versions imported (coach/app/legacy_json.py)."""
    path = migrate(default_path())
    from coach.app.legacy_json import import_all
    from coach.app.paths import data_home
    import_all(data_home(), path)
    return path


def connect(path) -> sqlite3.Connection:
    """A connection with foreign keys on and a wait instead of an error while another thread writes."""
    conn = sqlite3.connect(Path(path), timeout=10)
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def opened(path):
    """``with opened(path) as conn``: commits on success, rolls back on error, and always closes the connection
    (``with sqlite3.connect(…)`` alone commits but leaves it open)."""
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _activity_columns():
    from coach.history.store import COLUMNS       # the history keeps owning the columns of an activity
    return COLUMNS


# ---- migrations: never edit one that has shipped, add the next ----

def _v1(db: sqlite3.Connection):
    """Everything of ADR-003. Tables that have no screen yet stay empty."""
    columns = ', '.join(f'{n} {t}' for n, t in _activity_columns())
    db.execute(f'CREATE TABLE IF NOT EXISTS activities ({columns})')
    present = {r[1] for r in db.execute('PRAGMA table_info(activities)')}
    for name, kind in _activity_columns():                # a history.db of an earlier version
        if name not in present:
            db.execute(f'ALTER TABLE activities ADD COLUMN {name} {kind.replace("PRIMARY KEY", "")}')
    for (activity_id,) in db.execute('SELECT id FROM activities WHERE uuid IS NULL').fetchall():
        db.execute('UPDATE activities SET uuid = ? WHERE id = ?', (new_id(), activity_id))
    _run_script(db, '''
        CREATE UNIQUE INDEX IF NOT EXISTS activities_uuid ON activities(uuid);
        CREATE INDEX IF NOT EXISTS activities_start ON activities(start_utc);

        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            rider_weight_kg REAL, bike_weight_kg REAL, ftp_w INTEGER, ftp_source TEXT,
            bike_type TEXT, drivetrain TEXT,
            resting_hr INTEGER, max_hr INTEGER, threshold_hr INTEGER,
            birth_year INTEGER, height_cm INTEGER, sex TEXT,
            grade_difficulty_pct REAL, grade_descent_factor_pct REAL, max_grade_pct REAL, min_grade_pct REAL,
            grade_transition_m_per_pct REAL,
            updated_utc TEXT
        );
        CREATE TABLE IF NOT EXISTS profile_versions (
            id TEXT PRIMARY KEY, valid_from_utc TEXT NOT NULL, data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

        CREATE TABLE IF NOT EXISTS sessions (
            activity_id TEXT PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
            csv TEXT, raw_capture TEXT, finish_reason TEXT,
            moving_s REAL, work_kj REAL, ftp_w INTEGER, intensity_factor REAL, tss REAL,
            elevation_gain_m REAL, vam_mh REAL, rider_weight_kg REAL,
            trainer_difficulty_pct REAL, trainer_descent_factor_pct REAL,
            sensor_kinds TEXT, best_efforts_w TEXT, gear_seconds TEXT, estimated_ftp_w INTEGER,
            workout_id TEXT, workout_result TEXT,
            summary TEXT
        );
        CREATE TABLE IF NOT EXISTS routes (
            id TEXT PRIMARY KEY, file TEXT NOT NULL UNIQUE, name TEXT, gpx_name TEXT,
            generated INTEGER NOT NULL DEFAULT 0, generator TEXT, recorded INTEGER NOT NULL DEFAULT 0,
            distance_m REAL, gain_m REAL, loss_m REAL,
            created_utc TEXT, deleted_utc TEXT
        );
        CREATE TABLE IF NOT EXISTS session_routes (
            activity_id TEXT NOT NULL REFERENCES sessions(activity_id) ON DELETE CASCADE,
            route_id TEXT NOT NULL REFERENCES routes(id),
            km REAL,
            PRIMARY KEY (activity_id, route_id)
        );

        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY, name TEXT, kind TEXT, event_date TEXT,
            distance_m REAL, gain_m REAL, route_id TEXT REFERENCES routes(id),
            priority TEXT, status TEXT, created_utc TEXT
        );
        CREATE TABLE IF NOT EXISTS event_results (
            id TEXT PRIMARY KEY, goal_id TEXT REFERENCES goals(id) ON DELETE CASCADE,
            activity_id TEXT REFERENCES activities(id) ON DELETE SET NULL,
            finished INTEGER, time_s REAL, rpe REAL, sensations TEXT, note TEXT, created_utc TEXT
        );
        CREATE TABLE IF NOT EXISTS ftp_tests (
            id TEXT PRIMARY KEY, activity_id TEXT REFERENCES activities(id) ON DELETE SET NULL,
            tested_utc TEXT, protocol TEXT, ftp_w INTEGER, best_minute_w INTEGER, max_hr INTEGER,
            indoor INTEGER, accepted INTEGER
        );
        CREATE TABLE IF NOT EXISTS ftp_estimates (
            id TEXT PRIMARY KEY, computed_utc TEXT NOT NULL,
            trigger_activity_id TEXT REFERENCES activities(id) ON DELETE SET NULL,
            indoor_ftp_w INTEGER, outdoor_ftp_w INTEGER, method TEXT, cp_w REAL, w_prime_j REAL,
            efforts TEXT, algo_version TEXT, advice TEXT, accepted INTEGER
        );
        CREATE TABLE IF NOT EXISTS ai_recommendations (
            id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, kind TEXT, for_date TEXT, payload TEXT,
            status TEXT, activity_id TEXT REFERENCES activities(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS health_days (
            id TEXT PRIMARY KEY, day TEXT NOT NULL, kind TEXT, note TEXT
        );
        CREATE TABLE IF NOT EXISTS availability (
            id TEXT PRIMARY KEY, weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
            start_min INTEGER, end_min INTEGER
        );

        CREATE TABLE IF NOT EXISTS sharing_consents (
            id TEXT PRIMARY KEY, category TEXT NOT NULL, granted INTEGER NOT NULL,
            text_version TEXT, at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sharing_exclusions (
            activity_id TEXT PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE, at_utc TEXT NOT NULL
        );
    ''')


def _run_script(db: sqlite3.Connection, script: str):
    """Statement by statement: ``executescript`` would COMMIT first and break the migration's transaction."""
    for statement in script.split(';'):
        if statement.strip():
            db.execute(statement)


def _v2(db: sqlite3.Connection):
    """Routes: the same file name can come back (a route deleted, another GPX uploaded with its name), so ``file`` is
    no longer unique; a row belongs to the GPX whose fingerprint (``sha256``) it has. Deleted routes keep their row
    for the sessions ridden on them."""
    _run_script(db, '''
        CREATE TABLE routes_v2 (
            id TEXT PRIMARY KEY, file TEXT NOT NULL, sha256 TEXT, name TEXT, gpx_name TEXT,
            generated INTEGER NOT NULL DEFAULT 0, generator TEXT, recorded INTEGER NOT NULL DEFAULT 0,
            distance_m REAL, gain_m REAL, loss_m REAL,
            created_utc TEXT, deleted_utc TEXT
        );
        INSERT INTO routes_v2 (id, file, name, gpx_name, generated, generator, recorded, distance_m, gain_m, loss_m,
                               created_utc, deleted_utc)
            SELECT id, file, name, gpx_name, generated, generator, recorded, distance_m, gain_m, loss_m,
                   created_utc, deleted_utc FROM routes;
        DROP TABLE routes;
        ALTER TABLE routes_v2 RENAME TO routes;
        CREATE INDEX routes_file ON routes(file, sha256)
    ''')


def _v3(db: sqlite3.Connection):
    """Routes: what the list shows (summary and small profile, ``listing``) with the size and time of the GPX it
    came from, so listing the routes does not read every GPX again (1 s for six race GPX the first time)."""
    _run_script(db, '''
        ALTER TABLE routes ADD COLUMN listing TEXT;
        ALTER TABLE routes ADD COLUMN file_size INTEGER;
        ALTER TABLE routes ADD COLUMN file_mtime REAL
    ''')


def _v4(db: sqlite3.Connection):
    """FTP estimates: what was proposed and the FTP the rider had then (to see how good the estimate is and what
    the rider did with it)."""
    _run_script(db, '''
        ALTER TABLE ftp_estimates ADD COLUMN suggested_ftp_w INTEGER;
        ALTER TABLE ftp_estimates ADD COLUMN profile_ftp_w INTEGER;
        CREATE INDEX IF NOT EXISTS ftp_estimates_time ON ftp_estimates(computed_utc);
        CREATE INDEX IF NOT EXISTS ftp_tests_time ON ftp_tests(tested_utc)
    ''')


def _v5(db: sqlite3.Connection):
    """Races in stages: each stage with its date and its GPX, and a result per stage (``stage_id``; empty for the
    result of a one-day race)."""
    _run_script(db, '''
        CREATE TABLE goal_stages (
            id TEXT PRIMARY KEY, goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
            stage_no INTEGER NOT NULL, name TEXT, stage_date TEXT NOT NULL,
            distance_m REAL, gain_m REAL, route_id TEXT REFERENCES routes(id),
            UNIQUE (goal_id, stage_no)
        );
        ALTER TABLE event_results ADD COLUMN stage_id TEXT REFERENCES goal_stages(id) ON DELETE CASCADE;
        CREATE INDEX goal_stages_date ON goal_stages(stage_date)
    ''')


MIGRATIONS = {1: _v1, 2: _v2, 3: _v3, 4: _v4, 5: _v5}
SCHEMA_VERSION = max(MIGRATIONS)


class NewerDatabase(RuntimeError):
    """The database was written by a newer version of the app."""


def schema_version(db: sqlite3.Connection) -> int:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone():
        return 0
    row = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row[0]) if row else 0


def meta(path, key: str):
    with opened(path) as db:
        row = db.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
        return row[0] if row else None


def _backup(path: Path, version: int) -> Path:
    target = path.with_name(f'{path.name}.bak-v{version}-{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    source, copy = sqlite3.connect(path), sqlite3.connect(target)
    try:
        source.backup(copy)                    # consistent even while another connection is open
    finally:
        copy.close()
        source.close()
    return target


def _import_legacy_history(db: sqlite3.Connection, legacy: Path) -> int:
    """Copy the activities of the old history.db (once; history.db is not modified). Inside the caller's transaction."""
    try:
        if not db.execute("SELECT 1 FROM legacy.sqlite_master WHERE type = 'table' AND name = 'activities'").fetchone():
            return 0
        theirs = {r[1] for r in db.execute('PRAGMA legacy.table_info(activities)')}
        common = [n for n, _ in _activity_columns() if n in theirs and n != 'uuid']
        names = ', '.join(common)
        before = db.execute('SELECT COUNT(*) FROM activities').fetchone()[0]
        db.execute(f'INSERT OR IGNORE INTO activities ({names}) SELECT {names} FROM legacy.activities')
        for (activity_id,) in db.execute('SELECT id FROM activities WHERE uuid IS NULL').fetchall():
            db.execute('UPDATE activities SET uuid = ? WHERE id = ?', (new_id(), activity_id))
        return db.execute('SELECT COUNT(*) FROM activities').fetchone()[0] - before
    except sqlite3.DatabaseError:
        return 0                                          # a damaged history.db: start without it, it stays there


@contextmanager
def _transaction(conn: sqlite3.Connection):
    conn.execute('BEGIN')
    try:
        yield
    except BaseException:
        conn.execute('ROLLBACK')
        raise
    conn.execute('COMMIT')


def migrate(path=None) -> Path:
    """Open (create or bring up to date) the database at ``path`` and return its path. Cheap after the first call."""
    path = Path(path).expanduser() if path else default_path()
    key = str(path.resolve()) if path.exists() else str(path)
    if key in _ready and path.exists():
        return path
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists() and path.stat().st_size > 0
        conn = connect(path)
        conn.isolation_level = None       # transactions by hand: BEGIN … COMMIT, DDL included
        try:
            version = schema_version(conn)
            if version > SCHEMA_VERSION:
                raise NewerDatabase(f'{path} is schema v{version}; this app knows up to v{SCHEMA_VERSION}. '
                                    'Update the app: the database is left untouched.')
            if version < SCHEMA_VERSION:
                if existed and version > 0:
                    conn.close()
                    _backup(path, version)
                    conn = connect(path)
                    conn.isolation_level = None
                conn.execute('PRAGMA journal_mode = WAL')    # readers do not wait for the writer (server threads)
                conn.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
                for step in range(version + 1, SCHEMA_VERSION + 1):
                    with _transaction(conn):                    # one per migration: all of it or nothing
                        MIGRATIONS[step](conn)
                        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(step),))
                with _transaction(conn):
                    conn.execute("INSERT OR IGNORE INTO meta VALUES ('install_id', ?)", (new_id(),))
                    conn.execute("INSERT OR IGNORE INTO meta VALUES ('created_utc', ?)", (now_utc(),))
            legacy = path.with_name(LEGACY_HISTORY)
            if (legacy.is_file() and legacy.resolve() != path.resolve()
                    and conn.execute("SELECT 1 FROM meta WHERE key = 'legacy_history_imported'").fetchone() is None):
                try:
                    conn.execute('ATTACH DATABASE ? AS legacy', (str(legacy),))
                except sqlite3.DatabaseError:       # a damaged history.db: start without it, it stays there
                    attached, note = False, 'damaged, not imported'
                else:
                    attached, note = True, ''
                try:
                    with _transaction(conn):
                        copied = _import_legacy_history(conn, legacy) if attached else 0
                        conn.execute("INSERT INTO meta VALUES ('legacy_history_imported', ?)",
                                     (f'{now_utc()} · {copied} activities from {LEGACY_HISTORY} {note}'.strip(),))
                finally:
                    if attached:
                        conn.execute('DETACH DATABASE legacy')
        finally:
            conn.close()
        _ready.add(str(path.resolve()))
    return path

