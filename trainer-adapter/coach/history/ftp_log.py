"""The history of the FTP in the local database, for the AI (ADR-003): every ramp test (``ftp_tests``) and every
estimate the app made (``ftp_estimates``), and whether the rider took it.

- An estimate is kept only when something changed since the last one (the FTP notice asks for it on every visit
  to the Panel): the values, the method, what was proposed and the FTP the rider had then.
- A ramp test is kept when its session finishes, linked to that session; «Guardar como mi FTP» marks it accepted,
  before or after the session finishes.
"""
import json
from typing import Optional

from coach.app import db

ALGO_VERSION = 'cp-v1'      # coach/history/ftp_model.py: change it when the estimate changes


def record_estimate(db_path, advice: dict, trigger_activity_id: Optional[str] = None) -> bool:
    """Keep this estimate (coach/history/ftp_model.ftp_advice) if it differs from the last one. True when kept."""
    indoor, outdoor = advice.get('indoor') or {}, advice.get('outdoor') or {}
    used = indoor or outdoor
    row = {'indoor_ftp_w': indoor.get('ftp'), 'outdoor_ftp_w': outdoor.get('ftp'), 'method': used.get('method'),
           'cp_w': used.get('cp'), 'w_prime_j': used.get('wPrime'), 'advice': advice.get('kind'),
           'suggested_ftp_w': advice.get('suggestedFtp'), 'profile_ftp_w': advice.get('ftp'),
           'algo_version': ALGO_VERSION}
    if not used and row['advice'] is None:
        return False
    efforts = {'indoor': indoor.get('efforts'), 'outdoor': outdoor.get('efforts')}
    compared = [k for k in row]
    with db.opened(db_path) as conn:
        last = conn.execute(f"SELECT {', '.join(compared)} FROM ftp_estimates ORDER BY computed_utc DESC, rowid DESC "
                            'LIMIT 1').fetchone()
        if last is not None and tuple(last) == tuple(row[k] for k in compared):
            return False
        conn.execute(f"INSERT INTO ftp_estimates (id, computed_utc, trigger_activity_id, efforts, {', '.join(compared)}) "
                     f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in compared)})",
                     [db.new_id(), db.now_utc(), trigger_activity_id if _exists(conn, trigger_activity_id) else None,
                      json.dumps(efforts)] + [row[k] for k in compared])
    return True


def mark_estimate_accepted(db_path, ftp: int) -> bool:
    """The rider took the proposal of the latest estimate that suggested ``ftp``."""
    with db.opened(db_path) as conn:
        row = conn.execute('SELECT id FROM ftp_estimates WHERE suggested_ftp_w = ? ORDER BY computed_utc DESC, '
                           'rowid DESC LIMIT 1', (ftp,)).fetchone()
        if row:
            conn.execute('UPDATE ftp_estimates SET accepted = 1 WHERE id = ?', (row[0],))
    return row is not None


def record_test(db_path, activity_id: Optional[str], result: dict, accepted: bool, indoor: bool = True) -> Optional[str]:
    """A finished ramp test (coach/workouts/ramp_test.py summary). None when it gave no FTP."""
    if not result or result.get('ftpW') is None:
        return None
    test_id = db.new_id()
    with db.opened(db_path) as conn:
        conn.execute('INSERT INTO ftp_tests (id, activity_id, tested_utc, protocol, ftp_w, best_minute_w, max_hr, '
                     'indoor, accepted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (test_id, activity_id if _exists(conn, activity_id) else None, db.now_utc(), 'ramp',
                      result['ftpW'], result.get('best60sW'), result.get('maxHeartRate'), int(indoor), int(accepted)))
    return test_id


def mark_test_accepted(db_path, activity_id: str) -> bool:
    with db.opened(db_path) as conn:
        cursor = conn.execute('UPDATE ftp_tests SET accepted = 1 WHERE activity_id = ?', (activity_id,))
        return cursor.rowcount > 0


def link_test(db_path, test_id: str, activity_id: str):
    """The session of a test is saved after the test row: link them once it exists."""
    with db.opened(db_path) as conn:
        if _exists(conn, activity_id):
            conn.execute('UPDATE ftp_tests SET activity_id = ? WHERE id = ?', (activity_id, test_id))


def _exists(conn, activity_id) -> bool:
    return bool(activity_id) and conn.execute('SELECT 1 FROM activities WHERE id = ?', (activity_id,)).fetchone() is not None
