"""Local HTTP adapter: simulator or read-only Wahoo BLE, configurable in .env."""
import asyncio
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import dumps, loads
from math import sin
from threading import Event, Lock, Thread
from time import monotonic

from wahoo import bluetooth_worker
from hr50 import hr_worker
from pathlib import Path
from recording import CsvReplay, record_once
from diagnostics import RawCapture
from zwift_controllers import ControllerState, controller_worker

START = monotonic()
STALENESS_SECONDS = 4.0


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


STORE = ReadingStore()
HR_STORE = HeartRateStore()
HR_ENABLED = False
MODE = 'SIMULATOR'
REPLAY = None
CONTROLLERS = ControllerState()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/telemetry', '/health', '/replay/session', '/replay/state'):
            self.send_error(404)
            return
        if self.path in ('/replay/session', '/replay/state'):
            if MODE != 'REPLAY':
                self.send_error(409, 'Only available in REPLAY mode'); return
            self.respond(REPLAY.series() if self.path == '/replay/session' else REPLAY.state())
            return
        reading = (telemetry(monotonic() - START) if MODE == 'SIMULATOR'
                   else REPLAY.snapshot() if MODE == 'REPLAY' else STORE.snapshot())
        hr = HR_STORE.snapshot() if HR_ENABLED else {
            'heartRateBpm': None, 'heartRateConnected': False,
            'heartRateStatus': 'DISABLED', 'heartRateLastUpdateSeconds': None,
            'heartRateError': None,
        }
        if MODE == 'REPLAY':
            # Replay already includes HR samples from the original session.
            pass
        else:
            reading.update(hr)
        reading.update(CONTROLLERS.snapshot())
        data = reading if self.path == '/telemetry' else {
            'status': 'UP', 'mode': MODE, 'trainerConnected': reading['connected'],
            'trainerStatus': reading['status']}
        self.respond(data)

    def respond(self, data):
        body = dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ('/replay/control', '/replay/gear'):
            self.send_error(404); return
        if MODE != 'REPLAY':
            self.send_error(409, 'Control only allowed in REPLAY mode'); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 4096:
                raise ValueError('Invalid request size')
            body = loads(self.rfile.read(length).decode('utf-8'))
            if not isinstance(body, dict):
                raise ValueError('Expected object')
            if self.path == '/replay/control':
                result = REPLAY.control(body.get('action'), body.get('value'))
            else:
                delta = body.get('delta')
                if type(delta) is not int:
                    raise ValueError('delta must be integer')
                result = {'virtualGear': CONTROLLERS.simulate_shift(delta),
                          'gearControlMode': 'DISPLAY_ONLY'}
            self.respond(result)
        except (ValueError, TypeError) as exc:
            self.send_error(400, str(exc))


def server_config():
    host = os.environ.get('TRAINER_HOST', '127.0.0.1')
    port = int(os.environ.get('TRAINER_PORT', '8766'))
    if not 1 <= port <= 65535:
        raise ValueError('TRAINER_PORT must be between 1 and 65535')
    return host, port


def trainer_mode():
    mode = os.environ.get('TRAINER_MODE', 'SIMULATOR').upper()
    if mode not in ('WAHOO', 'SIMULATOR', 'REPLAY'):
        raise ValueError('TRAINER_MODE must be SIMULATOR, WAHOO or REPLAY')
    return mode


if __name__ == '__main__':
    MODE = trainer_mode()
    if MODE == 'REPLAY':
        csv_file = os.environ.get('REPLAY_FILE')
        if not csv_file:
            raise ValueError('REPLAY_FILE is required when TRAINER_MODE=REPLAY')
        csv_path = Path(csv_file).expanduser()
        if not csv_path.is_absolute():
            csv_path = Path(__file__).resolve().parent.parent / csv_path
        REPLAY = CsvReplay(csv_path)
    HR_ENABLED = os.environ.get('HR_ENABLED', 'false').lower() in ('1', 'true', 'yes')
    host, port = server_config()
    stop = Event()
    duration = int(os.environ.get('RECORD_SECONDS', '600'))
    if duration <= 0:
        raise ValueError('RECORD_SECONDS must be positive')
    folder = Path(os.environ.get('RECORD_DIR', str(Path(__file__).resolve().parent / 'recordings')))
    recording_enabled = MODE == 'WAHOO' and os.environ.get('RECORD_ENABLED', 'true').lower() in ('true', 'yes', '1')
    control_test = os.environ.get('CONTROL_TEST_ENABLED', 'false').lower() in ('true', 'yes', '1')
    if control_test and (MODE != 'WAHOO' or not recording_enabled or duration != 600):
        raise ValueError('CONTROL_TEST_ENABLED requires WAHOO, RECORD_ENABLED=true, RECORD_SECONDS=600')
    # Zwift button readers remain usable with TRAINER_MODE=REPLAY. No trainer commands.
    zwift_enabled = os.environ.get('ZWIFT_ENABLED', 'false').lower() in ('true', 'yes', '1')
    if zwift_enabled:
        zwift_ids = {
            'left': os.environ.get('ZWIFT_LEFT_DEVICE_ID', '').strip(),
            'right': os.environ.get('ZWIFT_RIGHT_DEVICE_ID', '').strip(),
        }
        for side, device_id in zwift_ids.items():
            if device_id:
                Thread(target=lambda side=side, device_id=device_id: asyncio.run(
                    controller_worker(CONTROLLERS, side, device_id, stop)),
                    daemon=True, name=f'zwift-{side}').start()
            else:
                CONTROLLERS.set_status(side, False, 'NOT_CONFIGURED')
    capture = RawCapture(folder, seconds=duration) if recording_enabled else None
    ble_thread = None
    if MODE == 'WAHOO':
        def run_ble():
            asyncio.run(bluetooth_worker(
                STORE, stop,
                device_name=os.environ.get('WAHOO_DEVICE_NAME', 'KICKR CORE'),
                device_id=os.environ.get('WAHOO_DEVICE_ID') or None,
                capture=capture, capture_dir=folder if recording_enabled else None,
                control_test=control_test))
        ble_thread = Thread(target=run_ble, daemon=False, name='ble-reader')
        ble_thread.start()
    if HR_ENABLED and MODE != 'REPLAY':
        def run_hr():
            asyncio.run(hr_worker(
                HR_STORE, stop,
                device_name=os.environ.get('HR_DEVICE_NAME', 'HR50'),
                device_id=os.environ.get('HR_DEVICE_ID') or None,
                capture=capture))
        Thread(target=run_hr, daemon=True, name='hr-reader').start()
    if recording_enabled:
        Thread(target=lambda: record_once(
            STORE.snapshot, HR_STORE.snapshot, stop, folder, seconds=duration),
            daemon=True, name='csv-recorder').start()
    print(f'Trainer adapter ({MODE}, HR={HR_ENABLED}, CONTROL_TEST={control_test}): http://{host}:{port}', flush=True)
    if control_test:
        print('ATTENTION: minute 0-5 baseline; minute 5-10 grades 1/2/3/2/0%. Ctrl+C to stop.', flush=True)
    httpd = ThreadingHTTPServer((host, port), Handler)
    def terminate(_sig, _frame):
        # SIGTERM from start.sh must allow the BLE worker to restore 0%.
        Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, terminate)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if ble_thread is not None:
            ble_thread.join(timeout=8)
        if capture:
            capture.close()
        httpd.server_close()
