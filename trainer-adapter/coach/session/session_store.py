"""Finished sessions in the local database (ADR-003, phase 2c).

A session is two rows: its activity in ``activities`` (what the history and the load see, coach/history/store.py)
and its detail in ``sessions``: the whole summary as it was written (``summary``, JSON) plus the columns worth
querying (work, TSS, the trainer difficulty of that day, the workout…). The routes ridden are linked in
``session_routes`` to the catalogue (coach/app/routes_store.py). The second-by-second CSV stays a file.

Until 16-11 the summary was ``session_<stamp>.json`` next to the CSV: coach/app/legacy_json.py imports them once.
Deleting a session marks its activity ``deleted_utc`` (it stops counting in the history and the load); nothing is
removed from the database.
"""
import json
from pathlib import Path
from threading import Lock
from typing import Optional

from coach.app import db

_lock = Lock()

# sessions column → summary key (the rest stays in the summary JSON)
COLUMNS = {'csv': 'csv', 'raw_capture': 'rawCapture', 'finish_reason': 'finishReason', 'moving_s': 'movingSeconds',
           'work_kj': 'workKj', 'ftp_w': 'ftpWatts', 'intensity_factor': 'intensityFactor', 'tss': 'tss',
           'elevation_gain_m': 'elevationGainM', 'vam_mh': 'vamMh', 'rider_weight_kg': 'riderWeightKg',
           'trainer_difficulty_pct': 'trainerDifficultyPercent', 'trainer_descent_factor_pct': 'trainerDescentFactorPercent',
           'estimated_ftp_w': 'estimatedFtpW'}
JSON_COLUMNS = {'best_efforts_w': 'bestEffortsW', 'gear_seconds': 'gearSeconds', 'sensor_kinds': 'sensorKinds'}


def activity_id(stem: str) -> str:
    return f'app:{stem}'


class SessionStore:
    def __init__(self, db_path=None):
        self.path = db.migrate(db_path) if db_path else db.open_default()

    # ---- writing ----
    def save(self, summary: dict):
        """Add or replace the finished session ``summary`` (its activity keeps what the history added to it)."""
        from coach.history.store import HistoryStore, app_session_row
        stem = summary['session']
        history = HistoryStore(self.path)
        row = app_session_row(summary)
        if history.has(row['id']):
            history.update(row['id'], {k: v for k, v in row.items() if k != 'id'})
        else:
            history.add(row)
        workout = summary.get('workout') or {}
        values = {column: summary.get(key) for column, key in COLUMNS.items()}
        values.update({column: _json(summary.get(key)) for column, key in JSON_COLUMNS.items()})
        values.update(workout_id=workout.get('id'), workout_result=_json(workout or None),
                      summary=json.dumps(summary, ensure_ascii=False))
        names = list(values)
        with _lock, db.opened(self.path) as conn:
            conn.execute(f"INSERT OR REPLACE INTO sessions (activity_id, {', '.join(names)}) VALUES "
                         f"(?, {', '.join('?' for _ in names)})", [activity_id(stem)] + [values[n] for n in names])
            conn.execute('DELETE FROM session_routes WHERE activity_id = ?', (activity_id(stem),))
            if workout.get('type') == 'RAMP_TEST' and workout.get('ftpW') is not None and not conn.execute(
                    'SELECT 1 FROM ftp_tests WHERE activity_id = ?', (activity_id(stem),)).fetchone():
                # the test of this session, for the history of the FTP (coach/history/ftp_log.py)
                conn.execute('INSERT INTO ftp_tests (id, activity_id, tested_utc, protocol, ftp_w, best_minute_w, '
                             'max_hr, indoor, accepted) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)',
                             (db.new_id(), activity_id(stem), summary.get('finishedAtUtc') or summary.get('startedAtUtc'),
                              'ramp', workout['ftpW'], workout.get('best60sW'), workout.get('maxHeartRate'),
                              int(bool(workout.get('savedAsFtp')))))
            for ridden in summary.get('routes') or []:
                route = conn.execute('SELECT id FROM routes WHERE file = ? ORDER BY deleted_utc IS NOT NULL, '
                                     'created_utc DESC LIMIT 1', (ridden.get('file'),)).fetchone()
                if route:                                  # a route no longer in the catalogue stays in the summary only
                    conn.execute('INSERT OR REPLACE INTO session_routes (activity_id, route_id, km) VALUES (?, ?, ?)',
                                 (activity_id(stem), route[0], ridden.get('km')))

    def update(self, stem: str, changes: dict) -> dict:
        """Merge ``changes`` into the summary of ``stem`` and save it. KeyError when there is no such session."""
        summary = self.get(stem)
        if summary is None:
            raise KeyError(stem)
        summary.update(changes)
        self.save(summary)
        return summary

    def mark_deleted(self, stem: str):
        with _lock, db.opened(self.path) as conn:
            conn.execute('UPDATE activities SET deleted_utc = ? WHERE id = ?', (db.now_utc(), activity_id(stem)))

    # ---- reading ----
    def get(self, stem: str, include_deleted=False) -> Optional[dict]:
        with db.opened(self.path) as conn:
            row = conn.execute('SELECT s.summary FROM sessions s JOIN activities a ON a.id = s.activity_id '
                               'WHERE s.activity_id = ?' + ('' if include_deleted else ' AND a.deleted_utc IS NULL'),
                               (activity_id(stem),)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, limit: Optional[int] = None, offset: int = 0, where: str = '', args=()):
        """(summaries newest first, total) of the sessions not deleted; ``where`` narrows them (SQL on a and s)."""
        base = ('FROM sessions s JOIN activities a ON a.id = s.activity_id WHERE a.deleted_utc IS NULL'
                + (f' AND ({where})' if where else ''))
        with db.opened(self.path) as conn:
            total = conn.execute(f'SELECT COUNT(*) {base}', args).fetchone()[0]
            query = f'SELECT s.summary {base} ORDER BY a.start_utc DESC, a.id DESC'
            page_args = list(args)
            if limit is not None:
                query += ' LIMIT ? OFFSET ?'
                page_args += [limit, offset]
            rows = conn.execute(query, page_args).fetchall()
        return [json.loads(r[0]) for r in rows], total

    def stems(self):
        with db.opened(self.path) as conn:
            return {r[0][len('app:'):] for r in conn.execute('SELECT activity_id FROM sessions')}


def _json(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


def with_files(summary: dict, folder: Path) -> dict:
    """The summary plus the files of the session that exist (the summary itself is a download from the database)."""
    files = [name for name in (summary.get('csv'), summary.get('rawCapture')) if name and (Path(folder) / name).is_file()]
    return {**summary, 'files': files + [f"{summary['session']}.json"]}
