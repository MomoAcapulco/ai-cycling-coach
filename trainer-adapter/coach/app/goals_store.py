"""The race calendar: the events the rider prepares (``goals``), their stages (``goal_stages``) and how each one
went (``event_results``), in the local database (ADR-003). What the AI plans towards, and what it learns from.

An event has a name, a kind (marathon MTB, 24 h…), a priority (A: the main one of the season, B: important, C: part
of the preparation) and a status. A one-day race has its date, distance, climbing and GPX; a race in stages has two or
more stages, each with its own date, distance, climbing and GPX, and the race goes from the first to the last stage,
adding them up. After a day of racing, «¿Cómo fue?» keeps the result (of the race, or of each stage): finished or
not, time, perceived effort, a note, and the activity of that day from the history. The result of a race in stages
is the sum of its stages: finished if every stage was, and the total time.
"""
import re
from datetime import date, datetime, timedelta
from typing import Optional

from coach.app import db

KINDS = {'MTB_MARATHON': 'Maratón BTT', 'MTB_STAGES': 'BTT por etapas', 'MTB_ENDURANCE': 'Resistencia BTT (12 h, 24 h…)',
         'MTB_XC': 'Rally / XC BTT', 'GRAVEL': 'Gravel', 'ROAD': 'Carretera / gran fondo', 'OTHER': 'Otra'}
PRIORITIES = ('A', 'B', 'C')
STATUSES = ('planned', 'done', 'cancelled')
MAX_NAME, MAX_NOTE, MAX_STAGES = 80, 500, 30
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
FIELDS = {'name', 'eventDate', 'kind', 'distanceKm', 'gainM', 'routeFile', 'priority', 'status', 'stages'}


def _day(value, field='eventDate') -> str:
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise ValueError(f'{field} must be a date YYYY-MM-DD')
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{field} must be a real date')
    return value


def _number(body, key, low, high, whole=False):
    value = body.get(key)
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (whole and int(value) != value):
        raise ValueError(f'{key} must be a {"whole " if whole else ""}number')
    if not low <= value <= high:
        raise ValueError(f'{key} must be between {low} and {high}')
    return int(value) if whole else float(value)


def _km(body):
    km = _number(body, 'distanceKm', 0.1, 2000)
    return None if km is None else km * 1000


class GoalsStore:
    def __init__(self, db_path=None):
        self.path = db.migrate(db_path) if db_path else db.open_default()

    # ---- events ----
    def _route_id(self, file) -> Optional[str]:
        if not file:
            return None
        with db.opened(self.path) as conn:
            row = conn.execute('SELECT id FROM routes WHERE file = ? ORDER BY deleted_utc IS NOT NULL, created_utc DESC '
                               'LIMIT 1', (file,)).fetchone()
        if row is None:
            raise ValueError('routeFile must be one of your routes')
        return row[0]

    def _validated(self, body: dict, current: Optional[dict] = None):
        """(goal columns, stages or None) of ``body`` over ``current``."""
        if not isinstance(body, dict):
            raise ValueError('Expected an object')
        unknown = set(body) - FIELDS
        if unknown:
            raise ValueError(f'Unknown fields: {", ".join(sorted(unknown))}')
        merged = {**(current or {}), **body}
        name = (merged.get('name') or '').strip()
        if not name or len(name) > MAX_NAME:
            raise ValueError(f'name must be a text of 1 to {MAX_NAME} characters')
        kind = merged.get('kind') or 'MTB_MARATHON'
        if kind not in KINDS:
            raise ValueError(f'kind must be one of {", ".join(KINDS)}')
        priority = merged.get('priority') or 'B'
        if priority not in PRIORITIES:
            raise ValueError('priority must be A, B or C')
        status = merged.get('status') or 'planned'
        if status not in STATUSES:
            raise ValueError(f'status must be one of {", ".join(STATUSES)}')
        stages = self._stages(merged.get('stages'))
        if stages:                                  # the race goes from the first stage to the last, adding them up
            known = [s for s in stages if s['distance_m'] is not None]
            climbs = [s for s in stages if s['gain_m'] is not None]
            values = {'event_date': stages[0]['stage_date'],
                      'distance_m': sum(s['distance_m'] for s in known) if known else None,
                      'gain_m': sum(s['gain_m'] for s in climbs) if climbs else None, 'route_id': None}
        else:
            values = {'event_date': _day(merged.get('eventDate')), 'distance_m': _km(merged),
                      'gain_m': _number(merged, 'gainM', 0, 30000), 'route_id': self._route_id(merged.get('routeFile'))}
        return {'name': name, 'kind': kind, 'priority': priority, 'status': status, **values}, stages

    def _stages(self, stages):
        """The stages of a race in stages (two or more, in date order), or None for a one-day race."""
        if not stages:
            return None
        if not isinstance(stages, list) or len(stages) < 2 or len(stages) > MAX_STAGES:
            raise ValueError(f'stages must be a list of 2 to {MAX_STAGES} stages (one day: no stages)')
        out = []
        for number, stage in enumerate(stages, 1):
            if not isinstance(stage, dict) or set(stage) - {'name', 'date', 'distanceKm', 'gainM', 'routeFile'}:
                raise ValueError(f'stage {number}: name, date, distanceKm, gainM and routeFile only')
            name = (stage.get('name') or '').strip() or None
            if name and len(name) > MAX_NAME:
                raise ValueError(f'stage {number}: name of at most {MAX_NAME} characters')
            out.append({'stage_no': number, 'name': name, 'stage_date': _day(stage.get('date'), f'stage {number} date'),
                        'distance_m': _km(stage), 'gain_m': _number(stage, 'gainM', 0, 30000),
                        'route_id': self._route_id(stage.get('routeFile'))})
        if any(b['stage_date'] < a['stage_date'] for a, b in zip(out, out[1:])):
            raise ValueError('stages must be in date order (two stages on the same day are fine)')
        return out

    def _write_stages(self, conn, goal_id: str, stages):
        """Replace the stages of ``goal_id``, keeping the result of a stage whose number is kept."""
        old = {no: sid for sid, no in conn.execute('SELECT id, stage_no FROM goal_stages WHERE goal_id = ?', (goal_id,))}
        new_numbers = {s['stage_no'] for s in (stages or [])}
        for no, sid in old.items():
            if no not in new_numbers:
                conn.execute('DELETE FROM goal_stages WHERE id = ?', (sid,))          # its result goes with it
        for stage in stages or []:
            sid = old.get(stage['stage_no']) or db.new_id()
            conn.execute('INSERT INTO goal_stages (id, goal_id, stage_no, name, stage_date, distance_m, gain_m, route_id) '
                         'VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name = excluded.name, '
                         'stage_date = excluded.stage_date, distance_m = excluded.distance_m, gain_m = excluded.gain_m, '
                         'route_id = excluded.route_id',
                         (sid, goal_id, stage['stage_no'], stage['name'], stage['stage_date'], stage['distance_m'],
                          stage['gain_m'], stage['route_id']))
        if stages:
            conn.execute('DELETE FROM event_results WHERE goal_id = ? AND stage_id IS NULL', (goal_id,))
        else:
            conn.execute('DELETE FROM event_results WHERE goal_id = ? AND stage_id IS NOT NULL', (goal_id,))

    def create(self, body: dict) -> dict:
        values, stages = self._validated(body)
        goal_id = db.new_id()
        names = list(values)
        with db.opened(self.path) as conn:
            conn.execute(f"INSERT INTO goals (id, created_utc, {', '.join(names)}) VALUES (?, ?, {', '.join('?' for _ in names)})",
                         [goal_id, db.now_utc()] + [values[n] for n in names])
            self._write_stages(conn, goal_id, stages)
        return self.get(goal_id)

    def update(self, goal_id: str, body: dict) -> dict:
        current = self.get(goal_id)
        if current is None:
            raise KeyError(goal_id)
        keep = {k: current[k] for k in ('name', 'eventDate', 'kind', 'distanceKm', 'gainM', 'routeFile', 'priority', 'status')}
        keep['stages'] = [{'name': s['name'], 'date': s['date'], 'distanceKm': s['distanceKm'], 'gainM': s['gainM'],
                           'routeFile': s['routeFile']} for s in current['stages']] or None
        values, stages = self._validated(body, keep)
        with db.opened(self.path) as conn:
            conn.execute(f"UPDATE goals SET {', '.join(f'{n} = ?' for n in values)} WHERE id = ?",
                         list(values.values()) + [goal_id])
            self._write_stages(conn, goal_id, stages)
        return self.get(goal_id)

    def delete(self, goal_id: str):
        with db.opened(self.path) as conn:
            if conn.execute('DELETE FROM goals WHERE id = ?', (goal_id,)).rowcount == 0:
                raise KeyError(goal_id)

    # ---- results ----
    def save_result(self, goal_id: str, body: dict) -> dict:
        """The result of a one-day race, or of one stage (``stageNo``) of a race in stages."""
        goal = self.get(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        if not isinstance(body, dict):
            raise ValueError('Expected an object')
        stage_id = None
        if goal['stages']:
            stage = next((s for s in goal['stages'] if s['stageNo'] == body.get('stageNo')), None)
            if stage is None:
                raise ValueError(f'stageNo must be one of the stages (1 to {len(goal["stages"])})')
            stage_id = stage['id']
        elif body.get('stageNo') is not None:
            raise ValueError('this race has no stages')
        finished = body.get('finished')
        if not isinstance(finished, bool):
            raise ValueError('finished must be true or false')
        rpe = _number(body, 'rpe', 1, 10, whole=True)
        time_s = _number(body, 'timeSeconds', 60, 7 * 24 * 3600)
        note = (body.get('note') or '').strip() or None
        if note and len(note) > MAX_NOTE:
            raise ValueError(f'note must be at most {MAX_NOTE} characters')
        activity = body.get('activityId') or None
        with db.opened(self.path) as conn:
            if activity and not conn.execute('SELECT 1 FROM activities WHERE id = ?', (activity,)).fetchone():
                raise ValueError('activityId must be one of your activities')
            conn.execute('DELETE FROM event_results WHERE goal_id = ? AND stage_id IS ?', (goal_id, stage_id))
            conn.execute('INSERT INTO event_results (id, goal_id, stage_id, activity_id, finished, time_s, rpe, note, '
                         'created_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (db.new_id(), goal_id, stage_id, activity, int(finished), time_s, rpe, note, db.now_utc()))
        done = self.get(goal_id)
        if done['result'] is not None and done['status'] == 'planned':  # the race (every stage) has its result
            with db.opened(self.path) as conn:
                conn.execute("UPDATE goals SET status = 'done' WHERE id = ?", (goal_id,))
            done = self.get(goal_id)
        return done

    # ---- reading ----
    def get(self, goal_id: str) -> Optional[dict]:
        found = [g for g in self.list() if g['id'] == goal_id]
        return found[0] if found else None

    def list(self, today: Optional[date] = None) -> list:
        """Every event by date, with its stages, results and the days left (negative: already past)."""
        today = today or datetime.now().astimezone().date()
        with db.opened(self.path) as conn:
            goals = conn.execute(
                'SELECT g.id, g.name, g.event_date, g.kind, g.distance_m, g.gain_m, g.priority, g.status, '
                'r.file, COALESCE(r.name, r.gpx_name) FROM goals g LEFT JOIN routes r ON r.id = g.route_id '
                'ORDER BY g.event_date, g.name').fetchall()
            stages = conn.execute(
                'SELECT s.goal_id, s.id, s.stage_no, s.name, s.stage_date, s.distance_m, s.gain_m, r.file, '
                'COALESCE(r.name, r.gpx_name) FROM goal_stages s LEFT JOIN routes r ON r.id = s.route_id '
                'ORDER BY s.goal_id, s.stage_no').fetchall()
            results = conn.execute('SELECT goal_id, stage_id, finished, time_s, rpe, note, activity_id FROM event_results').fetchall()
        by_goal, result_of = {}, {}
        for goal_id, stage_id, finished, time_s, rpe, note, activity in results:
            result_of[(goal_id, stage_id)] = {'finished': bool(finished), 'timeSeconds': time_s, 'rpe': rpe,
                                              'note': note, 'activityId': activity}
        for goal_id, sid, no, name, day, distance, gain, file, route_name in stages:
            by_goal.setdefault(goal_id, []).append({
                'id': sid, 'stageNo': no, 'name': name, 'date': day, 'daysTo': (date.fromisoformat(day) - today).days,
                'distanceKm': None if distance is None else round(distance / 1000, 1), 'gainM': gain,
                'routeFile': file, 'routeName': route_name, 'result': result_of.get((goal_id, sid))})
        out = []
        for goal_id, name, day, kind, distance, gain, priority, status, route_file, route_name in goals:
            own = by_goal.get(goal_id, [])
            last_day = own[-1]['date'] if own else day
            for stage in own:
                stage['needsResult'] = stage['daysTo'] < 0 and stage['result'] is None and status != 'cancelled'
            if own:
                result = None
                if all(s['result'] for s in own):          # the race: every stage, added up
                    times = [s['result']['timeSeconds'] for s in own]
                    rpes = [s['result']['rpe'] for s in own if s['result']['rpe']]
                    result = {'finished': all(s['result']['finished'] for s in own),
                              'timeSeconds': sum(times) if all(t is not None for t in times) else None,
                              'rpe': max(rpes) if rpes else None, 'note': None, 'activityId': None}
                needs = any(s['needsResult'] for s in own)
            else:
                result = result_of.get((goal_id, None))
                needs = (date.fromisoformat(day) - today).days < 0 and result is None and status != 'cancelled'
            out.append({
                'id': goal_id, 'name': name, 'eventDate': day, 'endDate': last_day, 'kind': kind,
                'kindLabel': KINDS.get(kind, kind), 'distanceKm': None if distance is None else round(distance / 1000, 1),
                'gainM': gain, 'priority': priority, 'status': status, 'routeFile': route_file, 'routeName': route_name,
                'daysTo': (date.fromisoformat(day) - today).days, 'daysToEnd': (date.fromisoformat(last_day) - today).days,
                'stages': own, 'needsResult': needs, 'result': result})
        return out

    def month(self, month: str, today: Optional[date] = None) -> dict:
        """The days of ``month`` (YYYY-MM): the race days (a one-day race, or each stage) and what was done each day."""
        if not isinstance(month, str) or not re.fullmatch(r'\d{4}-\d{2}', month):
            raise ValueError('month must be YYYY-MM')
        first = date.fromisoformat(f'{month}-01')
        following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        start, end = first.isoformat(), following.isoformat()
        goals = [g for g in self.list(today) if g['eventDate'] < end and g['endDate'] >= start]
        race_days = []
        for g in goals:
            days = [(s['date'], s['stageNo']) for s in g['stages']] or [(g['eventDate'], None)]
            for day, number in days:
                if start <= day < end:
                    race_days.append({'date': day, 'goalId': g['id'], 'name': g['name'], 'priority': g['priority'],
                                      'stageNo': number, 'stages': len(g['stages'])})
        with db.opened(self.path) as conn:
            rows = conn.execute(
                'SELECT id, start_utc, type, name, COALESCE(moving_s, elapsed_s), distance_m FROM activities '
                'WHERE deleted_utc IS NULL AND start_utc >= ? AND start_utc < ? ORDER BY start_utc',
                ((first - timedelta(days=1)).isoformat(), (following + timedelta(days=1)).isoformat())).fetchall()
        days = {}
        for activity_id, started, kind, name, seconds, distance in rows:
            local = datetime.fromisoformat(started).astimezone().date()     # the rider's day, not UTC
            if first <= local < following:
                days.setdefault(local.isoformat(), []).append(
                    {'id': activity_id, 'type': kind, 'name': name, 'seconds': seconds,
                     'distanceKm': None if not distance else round(distance / 1000, 1)})
        return {'month': month, 'today': (today or datetime.now().astimezone().date()).isoformat(),
                'activities': days, 'goals': goals, 'raceDays': race_days}

    def activities_on(self, day: str) -> list:
        """The activities of one day, to pick the race (or the stage) among them for its result."""
        _day(day, 'day')
        return self.month(day[:7])['activities'].get(day, [])
