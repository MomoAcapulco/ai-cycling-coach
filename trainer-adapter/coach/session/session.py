"""Training sessions started and finished by the rider (no fixed duration).

- start → a 1 Hz sampler writes ``session_<UTC stamp>.csv`` in the recordings folder (same columns as the
  older recordings plus the gear, so the file can be replayed), and the raw Bluetooth capture runs too if
  enabled. pause/resume stop and restart the clock: paused time is not recorded and does not count.
- finish (button, settings change, app exit, or the safety limit of 4 h) → CSV closed and
  ``session_<stamp>.json`` written with the summary (coach/session/metrics.py).
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from typing import Callable, Optional

from coach.session.metrics import SessionMetrics
from coach.session.recording import FIELDS

SESSION_FIELDS = FIELDS + ['trainerGear', 'requestedGear', 'gearStatus', 'virtualGear',
                           'effectiveGradePercent', 'sentGradePercent', 'gradeStatus',
                           'roadGradePercent', 'rideSpeedKph', 'rideDistanceKm', 'altitudeM', 'elevationGainM',
                           'vamMh', 'wattsPerKg', 'routeName', 'routeProgressKm', 'targetPowerW']
MAX_SESSION_SECONDS = 4 * 3600
SAMPLE_SECONDS = 1.0


class SessionError(Exception):
    """An action that does not fit the current state (e.g. pause while idle)."""


class SessionManager:
    def __init__(self, reading: Callable[[], dict], folder: Path, ftp: Callable[[], Optional[int]] = lambda: None,
                 capture=None, clock=monotonic, now=lambda: datetime.now(timezone.utc),
                 max_seconds=MAX_SESSION_SECONDS, sample_seconds=SAMPLE_SECONDS,
                 rider_kg: Callable[[], Optional[float]] = lambda: None,
                 extra: Callable[[], dict] = lambda: {}):
        self.reading, self.folder, self.ftp, self.capture = reading, Path(folder), ftp, capture
        self.extra = extra          # more for the summary at the end (the workout ridden and how it went)
        self.rider_kg = rider_kg
        self.clock, self.now, self.max_seconds, self.sample_seconds = clock, now, max_seconds, sample_seconds
        self.lock = Lock()
        self.state = 'IDLE'
        self.stem = None
        self.started_utc = None
        self.metrics = None
        self.last_summary = None
        self._file = self._writer = self._thread = None
        self._wake = Event()
        self._last_tick = None

    # ---- actions ----
    def start(self):
        with self.lock:
            if self.state != 'IDLE':
                raise SessionError('A session is already running')
            self.folder.mkdir(parents=True, exist_ok=True)
            stamp = self.now().strftime('%Y%m%d_%H%M%S')
            self.stem = f'session_{stamp}'
            self.started_utc = self.now().isoformat(timespec='seconds')
            self._file = (self.folder / f'{self.stem}.csv').open('w', newline='', encoding='utf-8')
            self._writer = csv.DictWriter(self._file, fieldnames=SESSION_FIELDS, extrasaction='ignore')
            self._writer.writeheader()
            self.metrics = SessionMetrics()
            self.state = 'RUNNING'
            self._last_tick = self.clock()
            if self.capture is not None:
                self.capture.begin(f'{self.stem}_ble_raw')
            self._wake.clear()
            self._thread = Thread(target=self._run, daemon=True, name='session-sampler')
            self._thread.start()
            return self.snapshot_unlocked()

    def pause(self):
        with self.lock:
            if self.state != 'RUNNING':
                raise SessionError('Only a running session can be paused')
            self._sample_unlocked()  # account the time up to now
            self.state = 'PAUSED'
            return self.snapshot_unlocked()

    def resume(self):
        with self.lock:
            if self.state != 'PAUSED':
                raise SessionError('Only a paused session can be resumed')
            self.state = 'RUNNING'
            self._last_tick = self.clock()
            self.metrics.restart_counters()
            return self.snapshot_unlocked()

    def finish(self, reason='finished by the rider'):
        with self.lock:
            if self.state == 'IDLE':
                raise SessionError('No session to finish')
            if self.state == 'RUNNING':
                self._sample_unlocked()
            self.state = 'IDLE'
            self._wake.set()
            self._file.close()
            self._file = self._writer = None
            if self.capture is not None:
                self.capture.end()
            summary = {'session': self.stem, 'startedAtUtc': self.started_utc,
                       'finishedAtUtc': self.now().isoformat(timespec='seconds'), 'finishReason': reason,
                       'csv': f'{self.stem}.csv',
                       'rawCapture': f'{self.stem}_ble_raw.jsonl' if self.capture is not None else None,
                       **self.metrics.summary(self.ftp(), self.rider_kg())}
            try:
                summary.update(self.extra() or {})
            except Exception as exc:  # the summary must be written whatever happens
                print(f'WARNING: session summary extra failed: {exc}', flush=True)
            (self.folder / f'{self.stem}.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
            self.last_summary = summary
            return summary

    def finish_if_active(self, reason):
        try:
            return self.finish(reason)
        except SessionError:
            return None

    # ---- sampling ----
    def _run(self):
        while not self._wake.wait(self.sample_seconds):
            with self.lock:
                if self.state == 'RUNNING':
                    self._sample_unlocked()
                    over = self.metrics.elapsed >= self.max_seconds
                else:
                    over = False
            if over:
                self.finish_if_active('safety limit of 4 h reached')
                return

    def _sample_unlocked(self):
        now = self.clock()
        dt = now - self._last_tick
        self._last_tick = now
        reading = dict(self.reading())
        self.metrics.add(reading, dt)
        connected = bool(reading.get('connected'))
        row = {key: reading.get(key) for key in SESSION_FIELDS}
        row.update({'recordedAtUtc': self.now().isoformat(timespec='milliseconds'),
                    'elapsedSeconds': round(self.metrics.elapsed, 3),
                    'connected': connected,
                    'estimatedDistanceKm': round(self.metrics.distance_km, 5),
                    'mechanicalWorkKj': round(self.metrics.work_j / 1000, 3),
                    'experimentPhase': 'SESSION'})
        if not connected:
            for key in ('powerWatts', 'cadenceRpm', 'speedKph'):
                row[key] = ''
        self._writer.writerow({k: ('' if v is None else v) for k, v in row.items()})
        self._file.flush()

    # ---- status ----
    def snapshot_unlocked(self):
        m = self.metrics
        active = self.state != 'IDLE' and m is not None
        return {'sessionState': self.state, 'session': self.stem if active else None,
                'sessionElapsedSeconds': round(m.elapsed, 1) if active else None,
                'sessionDistanceKm': round(m.distance_km, 3) if active else None,
                'sessionWorkKj': round(m.work_j / 1000, 1) if active else None,
                'sessionElevationGainM': round(m.gain_m, 1) if active else None,
                'sessionAvgPowerW': m.summary()['avgPowerW'] if active else None}

    def snapshot(self):
        with self.lock:
            return self.snapshot_unlocked()


def list_sessions(folder: Path):
    """Finished sessions, newest first: their summary plus the files that exist."""
    folder = Path(folder)
    out = []
    for path in sorted(folder.glob('session_*.json'), reverse=True):
        try:
            summary = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        files = [name for name in (summary.get('csv'), summary.get('rawCapture'), path.name)
                 if name and (folder / name).is_file()]
        out.append({**summary, 'files': files})
    return out
