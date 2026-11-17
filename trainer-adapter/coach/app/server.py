"""HTTP API of the trainer adapter. Started by trainer-adapter/server.py."""
import os
import re
import signal
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import dumps, loads
from math import sin
from threading import Lock, Thread
from time import monotonic
from types import SimpleNamespace
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

from coach.bluetooth.device_registry import DeviceRegistry
from coach.bluetooth.discovery import ROLES
from coach.session.recording import CsvReplay
from coach.app.settings import MODES
from coach.devices.zwift_controllers import ControllerState

START = monotonic()
STALENESS_SECONDS = 4.0
MAX_JSON_BYTES = 4096


def telemetry(seconds: float) -> dict:
    return {
        'source': 'SIMULATOR', 'powerWatts': round(165 + 45 * sin(seconds / 9)),
        'cadenceRpm': round(82 + 8 * sin(seconds / 6)),
        'speedKph': round(25 + 3 * sin(seconds / 13), 1),
        'elapsedSeconds': round(seconds), 'connected': True,
        'status': 'STREAMING', 'lastUpdateSeconds': 0.0, 'error': None,
    }


class ReadingStore:
    """Share BLE callbacks with the HTTP server; never return stale watts as live."""
    def __init__(self):
        self.lock = Lock()
        self.values = {}
        self.aux_values = {}
        self.last_update = None
        self.message = 'Buscando rodillo...'
        self.started = monotonic()
        self.target_grade = None
        self.control_status = 'DISABLED'

    def update(self, values):
        with self.lock:
            self.values = dict(values)
            self.last_update = monotonic()
            self.message = None

    def update_aux(self, values):
        with self.lock:
            self.aux_values = dict(values)

    def set_control(self, status, grade):
        with self.lock:
            self.control_status = status
            self.target_grade = grade

    def waiting(self, message):
        with self.lock:
            self.last_update = None
            self.values = {}
            self.aux_values = {}
            self.message = message

    def note_error(self, message):
        with self.lock:
            self.message = message

    def snapshot(self):
        with self.lock:
            age = None if self.last_update is None else round(monotonic() - self.last_update, 2)
            streaming = age is not None and age <= STALENESS_SECONDS
            data = dict(self.values) if streaming else {}
            return {
                'source': 'WAHOO', 'powerWatts': data.get('powerWatts', 0),
                'cadenceRpm': data.get('cadenceRpm', 0.0),
                'speedKph': data.get('speedKph', 0.0),
                'cyclingPowerWatts': self.aux_values.get('cyclingPowerWatts') if streaming else None,
                'averagePowerWatts': data.get('averagePowerWatts'),
                'averageCadenceRpm': data.get('averageCadenceRpm'),
                'resistanceLevel': data.get('resistanceLevel'),
                'totalDistanceMeters': data.get('totalDistanceMeters'),
                'totalEnergyKcal': data.get('totalEnergyKcal'),
                'machineElapsedSeconds': data.get('machineElapsedSeconds'),
                'ftmsFlags': data.get('ftmsFlags'),
                'gradePercent': None,  # No measured terrain gradient.
                'targetGradePercent': self.target_grade,
                'controlStatus': self.control_status,
                'elapsedSeconds': round(monotonic() - self.started),
                'connected': streaming, 'status': 'STREAMING' if streaming else ('STALE' if age is not None else 'WAITING'),
                'lastUpdateSeconds': age,
                'error': self.message if not streaming else None,
            }


class HeartRateStore(ReadingStore):
    def snapshot(self):
        with self.lock:
            age = None if self.last_update is None else round(monotonic() - self.last_update, 2)
            fresh = age is not None and age <= STALENESS_SECONDS
            return {
                'heartRateBpm': self.values.get('heartRateBpm') if fresh else None,
                'rrIntervalsMs': self.values.get('rrIntervalsMs') if fresh else None,
                'heartRateConnected': fresh,
                'heartRateStatus': 'STREAMING' if fresh else ('STALE' if age is not None else 'WAITING'),
                'heartRateLastUpdateSeconds': age,
                'heartRateError': None if fresh else self.message,
            }


@dataclass
class AdapterState:
    """Everything the HTTP handler needs; built once in main() or directly by tests."""
    mode: str = 'SIMULATOR'
    replay: Optional[CsvReplay] = None
    hr_enabled: bool = False
    store: ReadingStore = field(default_factory=ReadingStore)
    hr_store: HeartRateStore = field(default_factory=HeartRateStore)
    controllers: ControllerState = field(default_factory=ControllerState)
    registry: Optional[DeviceRegistry] = None
    started: float = field(default_factory=monotonic)
    # coach.devices.grade_controller.GradeController: only with native gear control on the real trainer.
    grade: Optional[object] = None
    # coach.session.virtual_ride.VirtualRide: the virtual road (physics speed, distance, elevation); not in REPLAY.
    ride: Optional[object] = None
    # coach.workouts.ramp_test.RampTest (the FTP test) while one is running or its result is shown.
    workout: Optional[object] = None
    # The training session's state ('IDLE', 'RUNNING', 'PAUSED'); set by the runtime. In SIMULATOR the simulated
    # rider only pedals while a session is RUNNING: nothing moves until the rider presses «Iniciar sesión».
    session_state: Optional[Callable[[], str]] = None
    # (FTP, source) of the rider: the profile's or the estimated one (AdapterRuntime.workout_ftp); for the zones.
    rider_ftp: Optional[Callable[[], tuple]] = None

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f'mode must be one of {MODES}')
        if self.mode == 'REPLAY' and self.replay is None:
            raise ValueError('REPLAY mode needs a CsvReplay')


HR_DISABLED = {
    'heartRateBpm': None, 'heartRateConnected': False,
    'heartRateStatus': 'DISABLED', 'heartRateLastUpdateSeconds': None,
    'heartRateError': None,
}


REPLAY_MIN_SECONDS = 60     # a route session shorter than this, or with less of the route ridden, is not replayed:
REPLAY_MIN_KM = 0.2         # «datos insuficientes»
SIMULATED_RIDER_LIMIT_W = 260   # in SIMULATOR the simulated rider follows a workout target up to this power


def trainer_reading(state: 'AdapterState') -> dict:
    """The trainer (or simulator, or replay) alone, without HR, controllers or the virtual road."""
    if state.mode == 'SIMULATOR':
        reading = telemetry(monotonic() - state.started)
        if state.session_state is not None and state.session_state() != 'RUNNING':
            reading.update(powerWatts=0, cadenceRpm=0, speedKph=0.0)   # the simulated rider waits, sat on the bike
        workout = state.workout
        idle = state.session_state is not None and state.session_state() != 'RUNNING'
        if workout is not None and workout.running and not idle:
            # a simulated rider for trying the FTP test without a trainer: easy warm-up, follows the target up
            # to SIMULATED_RIDER_LIMIT_W, then gives up (stops pedalling)
            target = workout.target_w()
            if target is None:
                reading.update(powerWatts=120, cadenceRpm=85)
            elif target <= SIMULATED_RIDER_LIMIT_W:
                block = workout.block() if hasattr(workout, 'block') else None   # a structured workout's cadence
                reading.update(powerWatts=target, cadenceRpm=getattr(block, 'cadence', None) or 85)
            else:
                reading.update(powerWatts=0, cadenceRpm=0)
        return reading
    if state.mode == 'REPLAY':
        return state.replay.snapshot()
    return state.store.snapshot()


def live_power(reading: dict) -> float:
    """Power that moves the virtual rider: 0 without live data (it coasts, nothing is invented)."""
    return float(reading.get('powerWatts') or 0) if reading.get('connected') else 0.0


def current_reading(state: 'AdapterState') -> dict:
    """What /telemetry shows (and what a training session records each second)."""
    reading = trainer_reading(state)
    if state.mode != 'REPLAY':
        # Replay already includes the HR samples of the original session.
        reading.update(state.hr_store.snapshot() if state.hr_enabled else HR_DISABLED)
    reading.update(state.controllers.snapshot())
    if state.ride is not None:
        # target/road grade, physics speed, distance, altitude, elevation gain, VAM, W/kg
        reading.update(state.ride.snapshot(live_power(reading)))
        reading['gradeControlMode'] = 'SIMULATED' if state.mode == 'SIMULATOR' else None
    if state.grade is not None:
        reading.update(state.grade.snapshot())  # gradeControlMode TRAINER, effective/sent grade
    if state.workout is not None:
        reading.update(state.workout.snapshot())  # the workout: phase, target, block / step, results
    if state.rider_ftp is not None:
        reading['ftpW'], reading['ftpSource'] = state.rider_ftp()
    reading['mode'] = state.mode
    return reading


class Handler(BaseHTTPRequestHandler):
    """Reads the CURRENT state from ``self.server.runtime`` (it changes when settings are applied)."""

    @property
    def runtime(self):
        return self.server.runtime

    @property
    def state(self) -> AdapterState:
        return self.runtime.state

    @property
    def admin(self):
        """The AdapterRuntime, or None when the server was built around a fixed state (tests)."""
        return self.runtime if hasattr(self.runtime, 'update') else None

    @property
    def session(self):
        """The SessionManager of the running configuration (None in REPLAY or without a runtime)."""
        return getattr(self.runtime, 'session', None)

    def route(self):
        # Ignore query strings: /telemetry?x=1 is still /telemetry.
        return urlsplit(self.path).path

    def do_GET(self):
        path = self.route()
        state = self.state
        if path == '/devices':
            self.respond(self.devices_json())
            return
        if path == '/session':
            self.respond(self.session.snapshot() if self.session is not None else {'sessionState': 'UNAVAILABLE'})
            return
        if path == '/routes' and self.admin is not None:
            from coach.app.routes_store import list_routes
            from coach.session.session import list_sessions
            self.sessions_ready()
            ride = state.ride
            routes = list_routes(self.admin.env.routes_dir, db_path=self.admin.env.history_db)
            rides = {}                                    # route file -> its sessions, newest first
            for session in list_sessions(self.admin.env.record_dir, self.admin.env.history_db):
                for ridden in session.get('routes') or []:
                    seconds, km = session.get('elapsedSeconds') or 0, ridden.get('km') or 0
                    why = ('falta el CSV de la sesión' if session.get('csv') not in session.get('files', [])
                           else f'la sesión duró solo {seconds:.0f} s' if seconds < REPLAY_MIN_SECONDS
                           else f'solo se rodaron {km * 1000:.0f} m de la ruta' if km < REPLAY_MIN_KM else None)
                    rides.setdefault(ridden['file'], []).append(
                        {'session': session['session'], 'date': session.get('startedAtUtc'), 'km': km,
                         'seconds': seconds, 'csv': session.get('csv'), 'replayable': why is None, 'why': why,
                         'rpe': (session.get('feedback') or {}).get('rpe')})
            for route in routes:
                ridden = rides.get(route['file'], [])
                route['rides'] = len(ridden)
                route['lastRide'] = ridden[0] if ridden else None
                route['replayRide'] = next((r for r in ridden if r['replayable']), None)   # the newest that can be replayed
            limit, offset = self.page()
            total = len(routes)
            # the races for «like my race» in the generator: all of them, whatever page is shown
            races = [{k: r.get(k) for k in ('file', 'name', 'distanceKm', 'elevationGainM', 'maxGradePercent')}
                     for r in routes if r.get('valid') and not r.get('generated')]
            routes = routes[offset:] if limit is None else routes[offset:offset + limit]
            self.respond({'routes': routes, 'races': races, 'total': total, 'limit': limit, 'offset': offset,
                          'current': ride.route.file if ride is not None and ride.route is not None else None,
                          'available': self.route_unavailable() is None})
            return
        if path.startswith('/routes/') and self.admin is not None:
            # one route's profile, to look at it before choosing it
            from coach.app.routes_store import load_route
            from coach.session.route import RouteError
            from urllib.parse import unquote
            try:
                route = load_route(self.admin.env.routes_dir, unquote(path[len('/routes/'):]), self.admin.env.history_db)
            except (FileNotFoundError, RouteError):
                self.send_error(404, 'Route not found or not usable')
                return
            self.respond({**route.summary(), 'profile': route.profile()})
            return
        if path == '/route':
            ride = state.ride
            if ride is None or ride.route is None:
                self.respond({'active': False})
                return
            snap = ride.snapshot()
            self.respond({'active': True, **ride.route.summary(), 'profile': ride.route.profile(),
                          'progressKm': snap['routeProgressKm'], 'finished': snap['routeFinished']})
            return
        if path in ('/history', '/history/weeks') and self.admin is not None:
            self.respond(self.history_json(path.endswith('/weeks')))
            return
        if path in ('/goals', '/calendar', '/calendar/day') and self.admin is not None:
            # the race calendar (coach/app/goals_store.py)
            from coach.app.goals_store import KINDS, GoalsStore
            store = GoalsStore(self.admin.env.history_db)
            query = parse_qs(urlsplit(self.path).query)
            try:
                if path == '/goals':
                    self.respond({'goals': store.list(), 'kinds': KINDS})
                elif path == '/calendar':
                    from datetime import datetime
                    self.respond(store.month((query.get('month') or [datetime.now().strftime('%Y-%m')])[0]))
                else:
                    self.respond({'activities': store.activities_on((query.get('day') or [''])[0])})
            except ValueError as exc:
                self.send_error(400, str(exc))
            return
        if path == '/workout/library' and self.admin is not None:
            self.respond(self.admin.workout_library())
            return
        if path == '/history/load' and self.admin is not None:
            self.respond(self.load_json())
            return
        if path == '/history/ftp' and self.admin is not None:
            self.respond(self.ftp_json())
            return
        if path == '/sessions' and self.admin is not None:
            from coach.session.session import count_tests, sessions_page
            self.sessions_ready()
            limit, offset = self.page()
            hide = (parse_qs(urlsplit(self.path).query).get('tests') or [''])[0] == 'hide'
            sessions, total = sessions_page(self.admin.env.record_dir, self.admin.env.history_db, limit, offset, hide)
            self.respond({'sessions': sessions, 'total': total, 'limit': limit, 'offset': offset,
                          'tests': count_tests(self.admin.env.history_db)})
            return
        if path.startswith('/sessions/') and self.admin is not None:
            self.send_session_file(path[len('/sessions/'):])
            return
        if path in ('/admin/settings', '/admin/profile'):
            if self.admin is None or (path == '/admin/profile' and self.admin.profile_store is None):
                self.send_error(404)
                return
            if path == '/admin/profile':
                profile, saved = self.admin.profile_store.load()
                self.respond({'profile': profile.to_json(), 'saved': saved,
                              'profileFile': str(self.admin.profile_store.path)})
            else:
                self.respond(self.admin.describe())
            return
        if path not in ('/telemetry', '/health', '/replay/session', '/replay/state'):
            self.send_error(404)
            return
        if path in ('/replay/session', '/replay/state'):
            if state.mode != 'REPLAY':
                self.send_error(409, 'Only available in REPLAY mode')
                return
            if path == '/replay/session' and self.admin is not None:
                self.sessions_ready()                 # the routes of the session come from its summary
            self.respond(state.replay.series() if path == '/replay/session' else state.replay.state())
            return
        reading = current_reading(state)
        session = self.session
        reading.update(session.snapshot() if session is not None else {'sessionState': 'UNAVAILABLE'})
        data = reading if path == '/telemetry' else {
            'status': 'UP', 'mode': state.mode, 'trainerConnected': reading['connected'],
            'trainerStatus': reading['status']}
        self.respond(data)

    def history_store(self):
        from coach.history.store import HistoryStore
        env = self.admin.env
        self.sessions_ready()
        return HistoryStore(env.history_db) if env.history_db else HistoryStore.default()

    def sessions_ready(self):
        """Session summaries left as JSON next to the CSVs (earlier versions, or a database failure when a session
        finished) go into the database before anything reads the sessions (coach/app/legacy_json.py)."""
        from coach.app import db
        from coach.app.legacy_json import import_session_files
        env = self.admin.env
        if any(env.record_dir.glob('session_*.json')):
            import_session_files(env.record_dir, db.migrate(env.history_db) if env.history_db else db.open_default())

    def page(self, default_limit=20, max_limit=200):
        """``?limit=&offset=`` of a list: (limit, offset); ``limit=all`` gives everything (limit None)."""
        query = parse_qs(urlsplit(self.path).query)
        raw = (query.get('limit') or [str(default_limit)])[0]
        try:
            limit = None if raw == 'all' else max(1, min(max_limit, int(raw)))
            offset = max(0, int((query.get('offset') or ['0'])[0]))
        except ValueError:
            limit, offset = default_limit, 0
        return limit, offset

    def load_json(self):
        """Training load per activity and fitness / fatigue / form (coach/history/load.py)."""
        from coach.app.rider_profile import RiderProfile
        from coach.history.load import enrich_missing, load_report
        store = self.history_store()
        enrich_missing(store, store.path.parent, self.admin.env.record_dir)   # only what is new (or a first time)
        profile = self.admin.profile_store.load()[0] if self.admin.profile_store else RiderProfile()
        days = int((parse_qs(urlsplit(self.path).query).get('days') or ['180'])[0])
        return load_report(store.list(100000), profile, days=max(7, min(days, 3650)))

    def ftp_json(self):
        """The FTP estimated from recent hard efforts and what to do about it (coach/history/ftp_model.py)."""
        from coach.app.rider_profile import RiderProfile
        from coach.history.ftp_model import ftp_advice
        from coach.history.load import enrich_missing
        store = self.history_store()
        enrich_missing(store, store.path.parent, self.admin.env.record_dir)
        profile = self.admin.profile_store.load()[0] if self.admin.profile_store else RiderProfile()
        rows = store.list(100000)
        advice = ftp_advice(profile, rows)
        from coach.history.ftp_log import record_estimate
        record_estimate(store.path, advice, rows[0]['id'] if rows else None)   # only when it changed
        return advice

    def history_json(self, weeks: bool):
        """Every activity (this app's sessions are added on the fly), or totals per week (Monday to Sunday)."""
        from coach.history.store import TYPES
        store = self.history_store()
        kind = (parse_qs(urlsplit(self.path).query).get('type') or [None])[0]
        kind = kind if kind in TYPES else None                    # ?type=run: the list AND the weekly totals
        if not weeks:
            limit, offset = self.page(default_limit=25)
            return {'activities': store.list(limit, offset=offset, kind=kind), 'total': store.total(kind=kind),
                    'limit': limit, 'offset': offset, 'type': kind, 'counts': store.count_by(),
                    'types': store.count_by_type()}
        rows = store.list(None, kind=kind)
        from datetime import datetime, timedelta
        totals = {}
        for row in rows:
            if not row.get('start_utc'):
                continue
            day = datetime.fromisoformat(row['start_utc']).date()
            monday = (day - timedelta(days=day.weekday())).isoformat()
            week = totals.setdefault(monday, {'week': monday, 'hours': {}, 'activities': 0, 'distanceKm': 0.0,
                                              'ascentM': 0.0, 'workKj': 0.0})
            week['activities'] += 1
            kind = row['type']
            week['hours'][kind] = round(week['hours'].get(kind, 0) + (row.get('moving_s') or row.get('elapsed_s') or 0) / 3600, 2)
            if kind in ('ride', 'virtual_ride'):
                week['distanceKm'] = round(week['distanceKm'] + (row.get('distance_m') or 0) / 1000, 1)
                week['ascentM'] = round(week['ascentM'] + (row.get('ascent_m') or 0))
                week['workKj'] = round(week['workKj'] + (row.get('work_kj') or 0))
        return {'weeks': sorted(totals.values(), key=lambda w: w['week'])}

    def route_unavailable(self):
        """Why the grade (by hand or from a route) cannot be chosen now, or None."""
        state = self.state
        if state.ride is None or (state.mode != 'SIMULATOR' and state.grade is None):
            return 'Grade control needs the simulator, or the real trainer with gear control on'
        return None

    def devices_json(self):
        """Known devices per role (best first), candidates waiting for a choice, and .env filters."""
        registry = self.state.registry
        known = registry.load() if registry is not None else {}
        env = getattr(self.admin, 'env', None)
        return {'registryFile': str(registry.path) if registry is not None else None,
                'known': known,
                'remembered': {role: entries[0] for role, entries in known.items()},  # the one chosen first
                'pending': registry.pending_json() if registry is not None else {},
                # a device fixed by ID in .env: only that one is used for the role
                'envFilters': {'trainer': {'id': getattr(env, 'wahoo_device_id', None)},
                               'heart_rate': {'id': getattr(env, 'hr_device_id', None)},
                               'zwift_left': {'id': getattr(env, 'zwift_left_id', None)},
                               'zwift_right': {'id': getattr(env, 'zwift_right_id', None)}},
                'controllers': self.state.controllers.snapshot()}

    def respond(self, data, status=200):
        body = dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_session_file(self, name):
        """Download of a finished session's file: only session_* names inside the recordings folder."""
        import re
        self.sessions_ready()
        if re.fullmatch(r'session_\d{8}_\d{6}\.fit', name):
            # the FIT activity is built on request from the session's CSV and summary (coach/session/fit_export.py)
            from coach.session.fit_export import session_fit
            try:
                body = session_fit(self.admin.env.record_dir, name[:-len('.fit')], self.admin.env.history_db)
            except (OSError, ValueError, KeyError) as exc:
                self.send_error(404, f'No FIT for this session: {exc}')
                return
            kind = 'application/vnd.ant.fit'
        elif re.fullmatch(r'session_\d{8}_\d{6}\.json', name):
            # the summary is in the database (coach/session/session_store.py): downloaded as it was saved
            from coach.session.session_store import SessionStore
            summary = SessionStore(self.admin.env.history_db).get(name[:-len('.json')])
            if summary is None:
                self.send_error(404)
                return
            body = dumps(summary, indent=2, ensure_ascii=False).encode('utf-8')
            kind = 'application/json'
        elif not re.fullmatch(r'session_\d{8}_\d{6}(_ble_raw\.jsonl|\.csv)', name):
            self.send_error(404)
            return
        else:
            path = self.admin.env.record_dir / name
            if not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            kind = 'text/csv' if name.endswith('.csv') else 'application/json'
        self.send_response(200)
        self.send_header('Content-Type', kind if kind.endswith('.fit') else f'{kind}; charset=utf-8')  # FIT is binary
        self.send_header('Content-Disposition', f'attachment; filename="{name}"')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, limit):
        length = int(self.headers.get('Content-Length', '0'))
        if length <= 0:
            raise ValueError('Empty request')
        if length > limit:
            # read (and drop) what the client is sending before answering: closing mid-upload would look like a
            # broken connection ("adapter offline") instead of this clear message
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 1024 * 1024))
                if not chunk:
                    break
                remaining -= len(chunk)
            raise ValueError(f'File too large: {length / 1024 / 1024:.1f} MB (maximum {limit // (1024 * 1024)} MB)'
                             if limit >= 1024 * 1024 else f'Request too large ({length} bytes, maximum {limit})')
        return self.rfile.read(length)

    def read_json(self):
        body = loads(self.read_body(MAX_JSON_BYTES).decode('utf-8'))
        if not isinstance(body, dict):
            raise ValueError('Expected object')
        return body

    def do_POST(self):
        path = self.route()
        try:
            if path == '/admin/settings' and self.admin is not None:
                self.respond(self.admin.update(self.read_json()))
                return
            if path == '/admin/profile' and self.admin is not None and self.admin.profile_store is not None:
                body = self.read_json()
                source = body.pop('ftpSource', None) if isinstance(body, dict) else None
                source = source if source in ('estimate',) else None          # 'test' only from the ramp test
                profile = self.admin.profile_store.update(body, ftp_source=source)
                if source == 'estimate' and profile.ftp_watts is not None:   # the rider took the FTP notice
                    from coach.history.ftp_log import mark_estimate_accepted
                    mark_estimate_accepted(self.admin.profile_store.path, profile.ftp_watts)
                self.admin.profile_changed(profile)  # new grade difficulty/limits apply at once
                self.respond({'profile': profile.to_json(), 'saved': True,
                              'profileFile': str(self.admin.profile_store.path)})
                return
            goal = re.fullmatch(r'/goals(?:/([0-9a-f-]{36})(/result)?)?', path)
            if goal and self.admin is not None:
                from coach.app.goals_store import GoalsStore
                store = GoalsStore(self.admin.env.history_db)
                goal_id, result = goal.group(1), goal.group(2)
                try:
                    if goal_id is None:
                        self.respond(store.create(self.read_json()), 201)
                    elif result:
                        self.respond(store.save_result(goal_id, self.read_json()))
                    else:
                        self.respond(store.update(goal_id, self.read_json()))
                except KeyError:
                    self.send_error(404, 'No such event')
                return
            if path == '/admin/settings/reset' and self.admin is not None:
                self.respond(self.admin.reset_to_env())
                return
            feedback = re.fullmatch(r'/sessions/(session_\d{8}_\d{6})/feedback', path)
            if feedback and self.admin is not None:
                from coach.session.session import save_feedback
                self.sessions_ready()
                try:
                    saved = save_feedback(self.admin.env.record_dir, feedback.group(1), self.read_json(),
                                          self.admin.env.history_db)
                except FileNotFoundError:
                    self.send_error(404, 'No such session')
                    return
                self.respond(saved)                   # its activity (history, AI) is updated with it
                return
            replay = re.fullmatch(r'/routes/([^/]+\.gpx)/replay', path)
            if replay and self.admin is not None:
                # a recorded GPX (one of your rides) played like a session (coach/session/gpx_activity.py)
                from coach.app.routes_store import load_route
                from coach.session.gpx_activity import NotEnoughData, build_replay
                try:
                    route = load_route(self.admin.env.routes_dir, replay.group(1), self.admin.env.history_db)
                except FileNotFoundError:
                    self.send_error(404, 'No such route')
                    return
                try:
                    csv_name = build_replay(route, self.admin.env.routes_dir / route.file, self.admin.env.record_dir)
                except NotEnoughData as exc:
                    self.send_error(409, f'Datos insuficientes: {exc}')
                    return
                self.respond({'replayFile': csv_name})
                return
            if path == '/routes/rename' and self.admin is not None:
                from coach.app.routes_store import rename
                body = self.read_json()
                try:
                    self.respond(rename(self.admin.env.routes_dir, body.get('file'), body.get('name'), self.admin.env.history_db))
                except FileNotFoundError:
                    self.send_error(404, 'No such route')
                return
            if path == '/routes/generate' and self.admin is not None:
                from coach.app.routes_store import generate
                self.respond(generate(self.admin.env.routes_dir, self.read_json(), self.admin.env.history_db))
                return
            if path == '/routes' and self.admin is not None:
                from coach.app.routes_store import MAX_UPLOAD_BYTES as MAX_GPX, save_upload as save_route
                name = (parse_qs(urlsplit(self.path).query).get('name') or [''])[0]
                self.respond(save_route(self.admin.env.routes_dir, name, self.read_body(MAX_GPX), self.admin.env.history_db), 201)
                return
            if path in ('/workout/ramp/start', '/workout/structured/start', '/workout/stop', '/workout/ftp/save',
                        '/workout/clear') and self.admin is not None:
                body = self.read_json() if path.endswith('/start') and int(self.headers.get('Content-Length', '0')) else {}
                action = {'/workout/ramp/start': lambda: self.admin.start_ramp_test(body),
                          '/workout/structured/start': lambda: self.admin.start_structured(body),
                          '/workout/stop': self.admin.stop_workout, '/workout/ftp/save': self.admin.save_test_ftp,
                          '/workout/clear': self.admin.clear_workout}[path]
                self.respond(action())
                return
            if path in ('/route/start', '/route/stop') and self.admin is not None:
                reason = self.route_unavailable()
                if reason:
                    self.send_error(409, reason)
                    return
                if path == '/route/stop':
                    self.state.ride.stop_route()
                    self.respond({'active': False})
                    return
                from coach.app.routes_store import load_route
                from coach.session.route import RouteError
                file = self.read_json().get('file')
                if not isinstance(file, str):
                    raise ValueError('file must be the name of a route')
                try:
                    route = load_route(self.admin.env.routes_dir, file, self.admin.env.history_db)
                except FileNotFoundError:
                    self.send_error(404, 'Route not found')
                    return
                except RouteError as exc:
                    raise ValueError(f'Not a usable GPX route: {exc}')
                self.state.ride.start_route(route)
                self.respond({'active': True, **route.summary()})
                return
            if path in ('/session/start', '/session/pause', '/session/resume', '/session/finish'):
                from coach.session.session import SessionError
                session = self.session
                if session is None:
                    self.send_error(409, 'Sessions are available with the real trainer or the simulator, not in REPLAY')
                    return
                action = path.rsplit('/', 1)[1]
                try:
                    result = session.finish() if action == 'finish' else getattr(session, action)()
                except SessionError as exc:
                    self.send_error(409, str(exc))
                    return
                self.respond(result)
                return
            if path.startswith('/devices/') and path.endswith('/use'):
                # "Usar este": a known device or one of the candidates found nearby
                role = path[len('/devices/'):-len('/use')]
                registry = self.state.registry
                if role not in ROLES or registry is None:
                    self.send_error(404)
                    return
                address = self.read_json().get('address')
                if not isinstance(address, str) or not address:
                    raise ValueError('address must be a non-empty string')
                try:
                    registry.prefer(role, address)
                except KeyError:
                    self.send_error(404, 'Unknown device for this role')
                    return
                self.respond(self.devices_json())
                return
            state = self.state
            if path == '/grade':
                # The ONLY way the grade changes: the rider chooses it (Panel). In SIMULATOR it only moves
                # the virtual road (to try it without the trainer); on the trainer it needs native control.
                if state.ride is None or (state.mode != 'SIMULATOR' and state.grade is None):
                    self.send_error(409, 'Grade control needs the simulator, or the real trainer with gear control on')
                    return
                target = state.ride.request(self.read_json().get('gradePercent'))
                self.respond({'targetGradePercent': target})
                return
            if path == '/gear':
                # UI shift buttons: display-only in REPLAY, a real request when the trainer shifts natively.
                if state.mode != 'REPLAY' and state.controllers.snapshot().get('gearControlMode') != 'TRAINER':
                    self.send_error(409, 'Shifting needs REPLAY or gear control on the trainer')
                    return
                delta = self.read_json().get('delta')
                if type(delta) is not int:
                    raise ValueError('delta must be integer')
                snapshot = state.controllers.snapshot()
                state.controllers.simulate_shift(delta)
                self.respond({'requestedGear': state.controllers.requested_gear(),
                              'gearControlMode': snapshot.get('gearControlMode')})
                return
            if path not in ('/replay/control', '/replay/gear'):
                self.send_error(404)
                return
            if state.mode != 'REPLAY':
                self.send_error(409, 'Control only allowed in REPLAY mode')
                return
            body = self.read_json()
            if path == '/replay/control':
                result = state.replay.control(body.get('action'), body.get('value'))
            else:
                delta = body.get('delta')
                if type(delta) is not int:
                    raise ValueError('delta must be integer')
                result = {'virtualGear': state.controllers.simulate_shift(delta),
                          'gearControlMode': 'DISPLAY_ONLY'}
            self.respond(result)
        except PermissionError as exc:
            self.send_error(409, str(exc))
        except (ValueError, TypeError) as exc:
            # JSONDecodeError and UnicodeDecodeError are ValueErrors too.
            self.send_error(400, str(exc))

    def do_DELETE(self):
        path = self.route()
        if self.admin is not None and (path.startswith('/routes/') or path.startswith('/sessions/')):
            self.delete_file(path)
            return
        goal = re.fullmatch(r'/goals/([0-9a-f-]{36})', path)
        if goal and self.admin is not None:
            from coach.app.goals_store import GoalsStore
            try:
                GoalsStore(self.admin.env.history_db).delete(goal.group(1))
                self.respond({'deleted': goal.group(1)})
            except KeyError:
                self.send_error(404, 'No such event')
            return
        prefix = '/devices/'
        role = path[len(prefix):] if path.startswith(prefix) else None
        registry = self.state.registry
        if role not in ROLES or registry is None:
            self.send_error(404)
            return
        address = (parse_qs(urlsplit(self.path).query).get('address') or [None])[0]
        registry.forget(role, address)  # one device (?address=…) or every device of the role
        self.respond({'forgotten': role, 'address': address, **self.devices_json()})


def _delete_file(self, path):
    """DELETE /routes/<file> or /sessions/<session>: to the trash (routes_store.TRASH), never what is in use."""
    from coach.app.routes_store import delete_route
    from coach.session.session import delete_session
    state, env = self.state, self.admin.env
    try:
        if path.startswith('/routes/'):
            file = path[len('/routes/'):]
            ride = state.ride
            if ride is not None and ride.route is not None and ride.route.file == file and not ride.route_finished:
                self.send_error(409, 'You are riding this route: leave it first')
                return
            self.respond(delete_route(env.routes_dir, file, env.history_db))
            return
        stem = path[len('/sessions/'):]
        session = self.session
        if session is not None and session.snapshot().get('session') == stem:
            self.send_error(409, 'This session is being recorded: finish it first')
            return
        if state.mode == 'REPLAY' and state.replay is not None and state.replay.filename.stem == stem:
            self.send_error(409, 'This session is open in the replay: leave the replay first')
            return
        self.sessions_ready()
        self.respond(delete_session(env.record_dir, stem, env.history_db))   # no longer counts in history or load
    except FileNotFoundError:
        self.send_error(404, 'Not found')


Handler.delete_file = _delete_file


def make_server(host: str, port: int, runtime) -> ThreadingHTTPServer:
    """``runtime``: an AdapterRuntime, or a plain AdapterState (fixed configuration, no admin)."""
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.runtime = SimpleNamespace(state=runtime) if isinstance(runtime, AdapterState) else runtime
    return httpd


def server_config():
    host = os.environ.get('TRAINER_HOST', '127.0.0.1')
    port = int(os.environ.get('TRAINER_PORT', '8766'))
    if not 1 <= port <= 65535:
        raise ValueError('TRAINER_PORT must be between 1 and 65535')
    return host, port


def trainer_mode():
    mode = os.environ.get('TRAINER_MODE', 'WAHOO').upper()
    if mode not in MODES:
        raise ValueError('TRAINER_MODE must be SIMULATOR, WAHOO or REPLAY')
    return mode


def main():
    from coach.app.runtime import AdapterRuntime, EnvConfig
    from coach.app.settings import Settings, SettingsStore
    trainer_mode()  # fail early on a wrong TRAINER_MODE in .env
    from coach.app.paths import data_home, migrate_legacy_home
    copied = migrate_legacy_home()
    if copied:
        print(f'Copied {len(copied)} files from ~/.ai-cycling-coach to {data_home()} (originals kept)', flush=True)
    env = EnvConfig.from_env()
    from coach.app.rider_profile import ProfileStore
    runtime = AdapterRuntime(env, Settings.from_env(), store=SettingsStore.default(),
                             registry=DeviceRegistry.default(), profile_store=ProfileStore.default()).start()
    host, port = server_config()
    print(f'Trainer adapter: http://{host}:{port}  (CONTROL_TEST={env.control_test})', flush=True)
    if env.control_test:
        print('ATTENTION: minute 0-5 baseline; minute 5-10 grades 1/2/3/2/0%. Ctrl+C to stop.', flush=True)
    httpd = make_server(host, port, runtime)

    def terminate(_sig, _frame):
        # SIGTERM from start.sh must allow the BLE worker to restore 0%.
        Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, terminate)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.shutdown()
        httpd.server_close()
