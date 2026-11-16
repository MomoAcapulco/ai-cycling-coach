"""Activity history: every ride, run or workout, from this app and from outside (Strava export, FIT files).

A local SQLite database (``history.db`` in the data home, override with HISTORY_DB), never in the repository. One
row per activity with its summary; the original file is copied next to it (``history/files``) so the numbers can
be recomputed if a formula changes. Importing again never duplicates: the id is stable (``strava:<id>``,
``app:<session>``, ``fit:<hash>``).

Summaries from the 1 Hz records use the same rules as the sessions (coach/session/metrics.py): NP over 30 s,
moving time, work, a dropout is a gap. Records are put on a 1 s grid (the last value within 3 s; older means a
gap), so devices recording every 2-5 s or with auto-pause are summarised the same way.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from coach.session.metrics import SessionMetrics

COLUMNS = (
    ('id', 'TEXT PRIMARY KEY'), ('source', 'TEXT'), ('start_utc', 'TEXT'), ('type', 'TEXT'), ('name', 'TEXT'),
    ('elapsed_s', 'REAL'), ('moving_s', 'REAL'), ('distance_m', 'REAL'), ('ascent_m', 'REAL'),
    ('avg_power', 'REAL'), ('max_power', 'REAL'), ('np', 'REAL'), ('device_np', 'REAL'), ('work_kj', 'REAL'),
    ('avg_hr', 'REAL'), ('max_hr', 'REAL'), ('avg_cadence', 'REAL'), ('has_power', 'INTEGER'),
    ('has_hr', 'INTEGER'), ('device', 'TEXT'), ('strava_relative_effort', 'REAL'), ('file', 'TEXT'),
    ('imported_utc', 'TEXT'),
    # read once from the activity file (coach/history/load.py), so the load can be recomputed instantly when the
    # rider's FTP or heart-rate thresholds change: seconds at each heart rate, and the best 20 min power
    ('hr_hist', 'TEXT'), ('best20_w', 'REAL'), ('enriched', 'INTEGER'),
)
TYPES = ('ride', 'virtual_ride', 'run', 'strength', 'workout', 'other')
GAP_S = 3


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.files = self.path.parent / 'history' / 'files'
        self.lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(f"CREATE TABLE IF NOT EXISTS activities ({', '.join(f'{n} {t}' for n, t in COLUMNS)})")
            present = {r[1] for r in db.execute('PRAGMA table_info(activities)')}
            for name, kind in COLUMNS:                      # databases created by an earlier version
                if name not in present:
                    db.execute(f'ALTER TABLE activities ADD COLUMN {name} {kind}')

    @classmethod
    def default(cls):
        from coach.app.paths import data_file
        return cls(data_file('history.db', 'HISTORY_DB'))

    def _db(self):
        return sqlite3.connect(self.path)

    def has(self, activity_id: str) -> bool:
        with self.lock, self._db() as db:
            return db.execute('SELECT 1 FROM activities WHERE id = ?', (activity_id,)).fetchone() is not None

    def add(self, row: dict) -> bool:
        """Insert ``row`` unless its id is already there. True when inserted."""
        if row.get('type') not in TYPES:
            raise ValueError(f"unknown activity type {row.get('type')}")
        row = {**{name: None for name, _ in COLUMNS}, **row,
               'imported_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        names = [name for name, _ in COLUMNS]
        with self.lock, self._db() as db:
            cursor = db.execute(f"INSERT OR IGNORE INTO activities ({', '.join(names)}) VALUES "
                                f"({', '.join('?' for _ in names)})", [row[n] for n in names])
            return cursor.rowcount == 1

    def list(self, limit: int = 500, since: Optional[str] = None):
        with self.lock, self._db() as db:
            db.row_factory = sqlite3.Row
            query = 'SELECT * FROM activities'
            args = []
            if since:
                query += ' WHERE start_utc >= ?'
                args.append(since)
            query += ' ORDER BY start_utc DESC LIMIT ?'
            args.append(limit)
            return [dict(r) for r in db.execute(query, args)]

    def update(self, activity_id: str, values: dict):
        names = [n for n in values if n in {c for c, _ in COLUMNS} and n != 'id']
        if not names:
            return
        with self.lock, self._db() as db:
            db.execute(f"UPDATE activities SET {', '.join(f'{n} = ?' for n in names)} WHERE id = ?",
                       [values[n] for n in names] + [activity_id])

    def count_by(self):
        with self.lock, self._db() as db:
            return dict(db.execute('SELECT source, COUNT(*) FROM activities GROUP BY source').fetchall())

    def copy_file(self, name: str, data: bytes) -> str:
        """Keep the original file (gzip or not) and return its path relative to the data home."""
        self.files.mkdir(parents=True, exist_ok=True)
        target = self.files / name
        if not target.exists():
            target.write_bytes(data)
        return str(target.relative_to(self.path.parent))


def summarize_records(records, sessions=()) -> dict:
    """Summary of a FIT activity from its records (and the device's session totals when they exist)."""
    session = sessions[0] if sessions else {}
    timed = [r for r in records if r.get('timestamp') is not None]
    has_power = any(r.get('power') is not None for r in timed)
    has_hr = any(r.get('heart_rate') for r in timed)
    metrics = SessionMetrics()
    if timed:
        start, end = timed[0]['timestamp'], timed[-1]['timestamp']
        i, last = 0, None
        second = start
        while second <= end:
            while i < len(timed) and timed[i]['timestamp'] <= second:
                last = timed[i]
                i += 1
            fresh = last is not None and (second - last['timestamp']).total_seconds() <= GAP_S
            sample = {'connected': fresh}
            if fresh:
                sample.update({'powerWatts': last.get('power') or 0, 'cadenceRpm': last.get('cadence') or 0,
                               'heartRateBpm': last.get('heart_rate'), 'heartRateConnected': bool(last.get('heart_rate')),
                               'speedKph': (last.get('speed') or 0) * 3.6,
                               'rideDistanceKm': last['distance'] / 1000 if last.get('distance') is not None else None})
            metrics.add(sample, 1.0)
            second += timedelta(seconds=1)
    summary = metrics.summary()
    distance = session.get('total_distance')
    if distance is None:
        distance = next((r['distance'] for r in reversed(timed) if r.get('distance') is not None), None)
    return {
        'elapsed_s': session.get('total_elapsed_time') or (metrics.elapsed or None),
        'moving_s': session.get('total_timer_time') or (metrics.moving or None),
        'distance_m': distance if distance is not None else summary['distanceKm'] * 1000,
        'ascent_m': session.get('total_ascent'),
        'avg_power': summary['avgPowerW'] if has_power else None,
        'max_power': summary['maxPowerW'] if has_power else None,
        'np': summary['normalizedPowerW'] if has_power else None,
        'device_np': session.get('normalized_power'),
        'work_kj': summary['workKj'] if has_power else None,
        'avg_hr': summary['avgHeartRateBpm'] if has_hr else session.get('avg_heart_rate'),
        'max_hr': summary['maxHeartRateBpm'] if has_hr else session.get('max_heart_rate'),
        'avg_cadence': summary['avgCadenceRpm'],
        'has_power': int(has_power), 'has_hr': int(has_hr),
    }


def app_session_row(summary: dict) -> dict:
    """A finished session of this app (its summary JSON) as a history row."""
    return {
        'id': f"app:{summary['session']}", 'source': 'app', 'start_utc': summary.get('startedAtUtc'),
        'type': 'virtual_ride', 'name': 'Sesión en el rodillo',
        'elapsed_s': summary.get('elapsedSeconds'), 'moving_s': summary.get('movingSeconds'),
        'distance_m': (summary.get('distanceKm') or 0) * 1000, 'ascent_m': summary.get('elevationGainM'),
        'avg_power': summary.get('avgPowerW'), 'max_power': summary.get('maxPowerW'),
        'np': summary.get('normalizedPowerW'), 'work_kj': summary.get('workKj'),
        'avg_hr': summary.get('avgHeartRateBpm'), 'max_hr': summary.get('maxHeartRateBpm'),
        'avg_cadence': summary.get('avgCadenceRpm'), 'has_power': 1,
        'has_hr': int(summary.get('avgHeartRateBpm') is not None), 'device': 'ai-cycling-coach',
        'file': summary.get('csv'),
    }


def import_app_sessions(store: HistoryStore, recordings: Path) -> int:
    """Add the finished sessions of this app that are not in the history yet (idempotent)."""
    added = 0
    for path in sorted(Path(recordings).glob('session_*.json')):
        try:
            summary = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if summary.get('session') and not store.has(f"app:{summary['session']}"):
            added += store.add(app_session_row(summary))
    return added
