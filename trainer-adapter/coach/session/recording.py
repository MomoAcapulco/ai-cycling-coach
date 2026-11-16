"""Local CSV session capture and offline replay; no Bluetooth dependencies."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from time import monotonic
from threading import Lock

FIELDS = [
    'recordedAtUtc', 'elapsedSeconds', 'source', 'powerWatts',
    'cadenceRpm', 'speedKph', 'connected', 'status',
    'heartRateBpm', 'heartRateConnected', 'heartRateStatus',
    'cyclingPowerWatts', 'averagePowerWatts', 'averageCadenceRpm',
    'resistanceLevel', 'totalDistanceMeters', 'totalEnergyKcal',
    'machineElapsedSeconds', 'ftmsFlags', 'gradePercent',
    'estimatedDistanceKm', 'mechanicalWorkKj', 'targetGradePercent', 'controlStatus', 'experimentPhase',
]


def _capture_started(trainer):
    """Start when the first *moving* Wahoo reading arrives, not when app launches."""
    return trainer.get('connected') and (
        (trainer.get('powerWatts') or 0) > 0
        or (trainer.get('cadenceRpm') or 0) > 0
        or (trainer.get('speedKph') or 0) > 0
    )


def record_once(trainer_snapshot, hr_snapshot, stop: Event, directory: Path,
                seconds: int = 300, interval: float = 1.0,
                clock=monotonic, now=None):
    """Capture exactly one session (default 5 minutes) then exit.

    The file is created only after the first non-zero BLE telemetry reading.
    Returns the CSV path, or None if stopped before recording began.
    """
    if seconds <= 0 or interval <= 0:
        raise ValueError('seconds and interval must be positive')
    if now is None:
        now = lambda: datetime.now(timezone.utc)

    print('Grabación CSV: esperando a que empieces a pedalear...', flush=True)
    while not stop.is_set():
        if _capture_started(trainer_snapshot()):
            break
        stop.wait(min(interval, 0.25))
    if stop.is_set():
        return None

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime('%Y%m%d_%H%M%S_%f')
    path = directory / f'ride_{stamp}.csv'
    started = clock()
    next_sample = started
    estimated_distance_km = 0.0
    mechanical_work_kj = 0.0
    previous_elapsed = None
    print(f'Grabando {seconds} segundos en: {path}', flush=True)

    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        while not stop.is_set():
            elapsed = clock() - started
            if elapsed >= seconds:
                break
            t = trainer_snapshot()
            h = hr_snapshot()
            delta = 0.0 if previous_elapsed is None else max(0, elapsed - previous_elapsed)
            previous_elapsed = elapsed
            if t.get('connected'):
                estimated_distance_km += max(0, t.get('speedKph') or 0) * delta / 3600
                mechanical_work_kj += max(0, t.get('powerWatts') or 0) * delta / 1000
            from coach.devices.control import experiment_phase
            phase = experiment_phase(elapsed)[0] if seconds == 600 else 'UNSPECIFIED'
            row = {
                'recordedAtUtc': now().isoformat(timespec='milliseconds'),
                'elapsedSeconds': round(elapsed, 3),
                'source': t.get('source'),
                'powerWatts': t.get('powerWatts') if t.get('connected') else '',
                'cadenceRpm': t.get('cadenceRpm') if t.get('connected') else '',
                'speedKph': t.get('speedKph') if t.get('connected') else '',
                'connected': bool(t.get('connected')),
                'status': t.get('status'),
                'heartRateBpm': h.get('heartRateBpm') if h.get('heartRateConnected') else '',
                'heartRateConnected': bool(h.get('heartRateConnected')),
                'heartRateStatus': h.get('heartRateStatus'),
                'cyclingPowerWatts': t.get('cyclingPowerWatts') if t.get('connected') else '',
                'averagePowerWatts': t.get('averagePowerWatts') if t.get('connected') else '',
                'averageCadenceRpm': t.get('averageCadenceRpm') if t.get('connected') else '',
                'resistanceLevel': t.get('resistanceLevel') if t.get('connected') else '',
                'totalDistanceMeters': t.get('totalDistanceMeters') if t.get('connected') else '',
                'totalEnergyKcal': t.get('totalEnergyKcal') if t.get('connected') else '',
                'machineElapsedSeconds': t.get('machineElapsedSeconds') if t.get('connected') else '',
                'ftmsFlags': t.get('ftmsFlags') if t.get('connected') else '',
                'gradePercent': t.get('gradePercent') if t.get('connected') and t.get('gradePercent') is not None else '',
                'estimatedDistanceKm': round(estimated_distance_km, 5),
                'mechanicalWorkKj': round(mechanical_work_kj, 3),
                'targetGradePercent': t.get('targetGradePercent') if t.get('targetGradePercent') is not None else '',
                'controlStatus': t.get('controlStatus', 'DISABLED'),
                'experimentPhase': phase,
            }
            writer.writerow(row)
            file.flush()  # Do not lose all samples if the process is interrupted.
            next_sample += interval
            stop.wait(max(0, next_sample - clock()))

    print(f'Grabación finalizada: {path}', flush=True)
    return path


def _numeric(value, cast, default):
    if value is None or value == '':
        return default
    if cast is int:
        # Replays of converted GPX activities may carry '103.0' (sensor values are decimals in GPX).
        return int(round(float(value)))
    return cast(value)


def _bool(value):
    return str(value).lower() in ('true', '1', 'yes')


class CsvReplay:
    """Thread-safe local recording playback with seek, pause and speed.

    Nothing in this class touches the trainer or Bluetooth devices.
    """
    def __init__(self, filename, clock=monotonic, db_path=None):
        from bisect import bisect_right
        self.db_path = db_path          # where the summary of a session is (None: the rider's database)
        self.clock = clock
        self.lock = Lock()
        path = Path(filename).expanduser()
        with path.open(newline='', encoding='utf-8') as file:
            self.rows = list(csv.DictReader(file))
        required = {'elapsedSeconds', 'source', 'powerWatts', 'cadenceRpm', 'speedKph',
                    'connected', 'status', 'heartRateBpm', 'heartRateConnected'}
        if not self.rows or not required.issubset(self.rows[0]):
            raise ValueError(f'CSV vacío o incompatible: {path}')
        self.timeline = [_numeric(r['elapsedSeconds'], float, 0) for r in self.rows]
        if any(b < a for a, b in zip(self.timeline, self.timeline[1:])):
            raise ValueError('Replay timestamps must be ascending')
        self.duration = self.timeline[-1]
        self.gains = self._elevation_gains()
        self.offset = 0.0
        self.started = clock()
        self.paused = True        # waits at 0:00 for «Reproducir»: nothing plays until the rider asks
        self.speed = 1.0
        self.filename = path

    def _elevation_gains(self):
        """Climbing so far at each row: the recorded «elevationGainM» of a session, or, for a converted GPX
        activity (no such column), the sum of the rises of its altitude (already smoothed like the Routes page)."""
        if any(r.get('elevationGainM') not in (None, '') for r in self.rows):
            return [_numeric(r.get('elevationGainM'), float, None) for r in self.rows]
        gains, total, last = [], 0.0, None
        for row in self.rows:
            altitude = _numeric(row.get('altitudeM'), float, None)
            if altitude is not None:
                if last is not None and altitude > last:
                    total += altitude - last
                last = altitude
            gains.append(round(total, 1) if last is not None else None)
        return gains

    def _position(self):
        if self.paused:
            return self.offset
        return min(self.duration, self.offset + (self.clock() - self.started) * self.speed)

    def state(self):
        with self.lock:
            return {'positionSeconds': round(self._position(), 2),
                    'durationSeconds': self.duration, 'playing': not self.paused and self._position() < self.duration,
                    'speed': self.speed}

    def control(self, action, value=None):
        with self.lock:
            current = self._position()
            if action == 'pause':
                self.offset, self.paused = current, True
            elif action == 'play':
                self.offset, self.paused = (0.0, False) if current >= self.duration else (current, False)
            elif action == 'restart':
                self.offset, self.paused = 0.0, True
            elif action == 'seek':
                if value is None or not isinstance(value, (float, int)):
                    raise ValueError('seek requires numeric value')
                self.offset = min(self.duration, max(0.0, float(value)))
            elif action == 'speed':
                if value not in (0.5, 1, 1.0, 2, 2.0, 4, 4.0, 8, 8.0, 16, 16.0):   # 8–16×: rides of hours
                    raise ValueError('speed must be 0.5, 1, 2 or 4')
                self.offset, self.speed = current, float(value)
            else:
                raise ValueError('Unknown replay action')
            self.started = self.clock()
            return {'positionSeconds': round(self._position(), 2),
                    'durationSeconds': self.duration, 'playing': not self.paused and self._position() < self.duration,
                    'speed': self.speed}

    def series(self):
        """Sessions recorded with the virtual road (v4.3.0+) carry the road grade, physics speed, distance and
        altitude; older recordings only the trainer speed and the ordered grade."""
        samples = []
        first_altitude = next((_numeric(r.get('altitudeM'), float, None) for r in self.rows
                               if r.get('altitudeM') not in (None, '')), None)
        for row, t in zip(self.rows, self.timeline):
            road = _numeric(row.get('roadGradePercent'), float, None)
            ride_speed = _numeric(row.get('rideSpeedKph'), float, None)
            altitude = _numeric(row.get('altitudeM'), float, None)
            samples.append({
                't': t,
                'power': _numeric(row.get('powerWatts'), float, None),
                'target': _numeric(row.get('targetPowerW'), float, None),   # a workout's target (newer sessions)
                'heart': _numeric(row.get('heartRateBpm'), float, None),
                'cadence': _numeric(row.get('cadenceRpm'), float, None),
                'speed': ride_speed if ride_speed is not None else _numeric(row.get('speedKph'), float, None),
                'grade': road if road is not None else _numeric(row.get('targetGradePercent'), float, None),
                'effective': _numeric(row.get('effectiveGradePercent'), float, None),
                'distance': _numeric(row.get('estimatedDistanceKm'), float, None) if road is not None else None,
                'altitude': round(altitude - first_altitude, 1) if altitude is not None and first_altitude is not None else None,
            })
        kind = 'ROAD' if any(s['distance'] is not None for s in samples) else 'ORDERED_NOT_MEASURED'
        return {'durationSeconds': self.duration, 'samples': samples, 'gradeKind': kind, 'routes': self._routes()}

    def _routes(self):
        """The routes ridden in the session (its summary in the database; a converted GPX ride: the JSON of its
        conversion, next to the CSV), to draw them in the replay."""
        if self.filename.name.startswith('session_'):
            try:
                from coach.session.session_store import SessionStore
                summary = SessionStore(self.db_path).get(self.filename.stem, include_deleted=True) or {}
                return summary.get('routes') or []
            except Exception:                              # the replay goes on without its route
                return []
        try:
            summary = json.loads(self.filename.with_suffix('.json').read_text(encoding='utf-8'))
            return summary.get('routes') or []
        except (OSError, ValueError):
            return []

    def snapshot(self):
        from bisect import bisect_right
        with self.lock:
            elapsed = self._position()
            paused = self.paused
            speed = self.speed
        pos = max(0, bisect_right(self.timeline, elapsed) - 1)
        row = self.rows[pos]
        active = _bool(row['connected'])
        hr_active = _bool(row['heartRateConnected'])
        return {
            'source': 'REPLAY',
            'powerWatts': _numeric(row['powerWatts'], int, 0) if active else 0,
            'cadenceRpm': _numeric(row['cadenceRpm'], float, 0.0) if active else 0.0,
            'speedKph': _numeric(row['speedKph'], float, 0.0) if active else 0.0,
            'elapsedSeconds': round(elapsed), 'connected': active,
            'status': 'REPLAY_FINISHED' if elapsed >= self.duration else 'REPLAY',
            'replayPlaying': not paused and elapsed < self.duration,
            'replaySpeed': speed, 'replayDurationSeconds': self.duration, 'replayFile': self.filename.name,
            'lastUpdateSeconds': 0.0, 'error': None,
            'heartRateBpm': _numeric(row['heartRateBpm'], int, None) if hr_active else None,
            'routeName': row.get('routeName') or None,                         # a session ridden on a route
            'routeProgressKm': _numeric(row.get('routeProgressKm'), float, None),
            'heartRateConnected': hr_active,
            'heartRateStatus': 'REPLAY' if hr_active else 'WAITING',
            'heartRateLastUpdateSeconds': 0.0 if hr_active else None,
            'heartRateError': None,
            'targetGradePercent': _numeric(row.get('targetGradePercent'), float, None),
            'gradePercent': _numeric(row.get('gradePercent'), float, None),
            'estimatedDistanceKm': _numeric(row.get('estimatedDistanceKm'), float, None),
            'rideDistanceKm': _numeric(row.get('rideDistanceKm'), float, None),
            'altitudeM': _numeric(row.get('altitudeM'), float, None),
            'elevationGainM': self.gains[pos],
            'mechanicalWorkKj': _numeric(row.get('mechanicalWorkKj'), float, None),
            'roadGradePercent': _numeric(row.get('roadGradePercent'), float, None),
            'rideSpeedKph': _numeric(row.get('rideSpeedKph'), float, None) if active else None,
            'wattsPerKg': _numeric(row.get('wattsPerKg'), float, None) if active else None,
            'vamMh': _numeric(row.get('vamMh'), float, None) if active else None,
            'controlStatus': row.get('controlStatus') or 'REPLAY',
            'experimentPhase': row.get('experimentPhase') or None,
        }
