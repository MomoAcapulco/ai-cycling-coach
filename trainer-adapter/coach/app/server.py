"""HTTP API of the trainer adapter. Started by trainer-adapter/server.py."""
import os
import signal
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import dumps, loads
from math import sin
from threading import Lock, Thread
from time import monotonic
from types import SimpleNamespace
from typing import Optional
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


def trainer_reading(state: 'AdapterState') -> dict:
    """The trainer (or simulator, or replay) alone, without HR, controllers or the virtual road."""
    if state.mode == 'SIMULATOR':
        return telemetry(monotonic() - state.started)
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
            ride = state.ride
            self.respond({'routes': list_routes(self.admin.env.routes_dir), 'folder': str(self.admin.env.routes_dir),
                          'current': ride.route.file if ride is not None and ride.route is not None else None,
                          'available': self.route_unavailable() is None})
            return
        if path.startswith('/routes/') and self.admin is not None:
            # one route's profile, to look at it before choosing it
            from coach.app.routes_store import load_route
            from coach.session.route import RouteError
            from urllib.parse import unquote
            try:
                route = load_route(self.admin.env.routes_dir, unquote(path[len('/routes/'):]))
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
        if path == '/sessions' and self.admin is not None:
            from coach.session.session import list_sessions
            self.respond({'sessions': list_sessions(self.admin.env.record_dir)})
            return
        if path.startswith('/sessions/') and self.admin is not None:
            self.send_session_file(path[len('/sessions/'):])
            return
        if path in ('/admin/settings', '/admin/recordings', '/admin/profile'):
            if self.admin is None or (path == '/admin/profile' and self.admin.profile_store is None):
                self.send_error(404)
                return
            if path == '/admin/profile':
                profile, saved = self.admin.profile_store.load()
                self.respond({'profile': profile.to_json(), 'saved': saved,
                              'profileFile': str(self.admin.profile_store.path)})
            elif path == '/admin/settings':
                self.respond(self.admin.describe())
            else:
                from coach.app.recordings_store import list_recordings
                self.respond({'recordings': list_recordings(self.admin.env.record_dir),
                              'current': self.admin.settings.replay_file})
            return
        if path not in ('/telemetry', '/health', '/replay/session', '/replay/state'):
            self.send_error(404)
            return
        if path in ('/replay/session', '/replay/state'):
            if state.mode != 'REPLAY':
                self.send_error(409, 'Only available in REPLAY mode')
                return
            self.respond(state.replay.series() if path == '/replay/session' else state.replay.state())
            return
        reading = current_reading(state)
        session = self.session
        reading.update(session.snapshot() if session is not None else {'sessionState': 'UNAVAILABLE'})
        data = reading if path == '/telemetry' else {
            'status': 'UP', 'mode': state.mode, 'trainerConnected': reading['connected'],
            'trainerStatus': reading['status']}
        self.respond(data)

    def history_json(self, weeks: bool):
        """Every activity (this app's sessions are added on the fly), or totals per week (Monday to Sunday)."""
        from coach.history.store import HistoryStore, import_app_sessions
        env = self.admin.env
        store = HistoryStore(env.history_db) if env.history_db else HistoryStore.default()
        import_app_sessions(store, env.record_dir)
        rows = store.list(5000)
        if not weeks:
            return {'activities': rows[:500], 'counts': store.count_by(), 'database': str(store.path)}
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
        if re.fullmatch(r'session_\d{8}_\d{6}\.fit', name):
            # the FIT activity is built on request from the session's CSV and summary (coach/session/fit_export.py)
            from coach.session.fit_export import session_fit
            try:
                body = session_fit(self.admin.env.record_dir, name[:-len('.fit')])
            except (OSError, ValueError, KeyError) as exc:
                self.send_error(404, f'No FIT for this session: {exc}')
                return
            kind = 'application/vnd.ant.fit'
        elif not re.fullmatch(r'session_\d{8}_\d{6}(_ble_raw\.jsonl|\.csv|\.json)', name):
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
                profile = self.admin.profile_store.update(self.read_json())
                self.admin.profile_changed(profile)  # new grade difficulty/limits apply at once
                self.respond({'profile': profile.to_json(), 'saved': True,
                              'profileFile': str(self.admin.profile_store.path)})
                return
            if path == '/admin/settings/reset' and self.admin is not None:
                self.respond(self.admin.reset_to_env())
                return
            if path == '/routes' and self.admin is not None:
                from coach.app.routes_store import MAX_UPLOAD_BYTES as MAX_GPX, save_upload as save_route
                name = (parse_qs(urlsplit(self.path).query).get('name') or [''])[0]
                self.respond(save_route(self.admin.env.routes_dir, name, self.read_body(MAX_GPX)), 201)
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
                    route = load_route(self.admin.env.routes_dir, file)
                except FileNotFoundError:
                    self.send_error(404, 'Route not found')
                    return
                except RouteError as exc:
                    raise ValueError(f'Not a usable GPX route: {exc}')
                self.state.ride.start_route(route)
                self.respond({'active': True, **route.summary()})
                return
            if path == '/admin/recordings' and self.admin is not None:
                from coach.app.recordings_store import MAX_UPLOAD_BYTES, save_upload
                name = (parse_qs(urlsplit(self.path).query).get('name') or [''])[0]
                self.respond(save_upload(self.admin.env.record_dir, name, self.read_body(MAX_UPLOAD_BYTES)), 201)
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
        prefix = '/devices/'
        role = path[len(prefix):] if path.startswith(prefix) else None
        registry = self.state.registry
        if role not in ROLES or registry is None:
            self.send_error(404)
            return
        address = (parse_qs(urlsplit(self.path).query).get('address') or [None])[0]
        registry.forget(role, address)  # one device (?address=…) or every device of the role
        self.respond({'forgotten': role, 'address': address, **self.devices_json()})


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
    mode = os.environ.get('TRAINER_MODE', 'SIMULATOR').upper()
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
