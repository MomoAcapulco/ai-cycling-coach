"""Applies Settings while the adapter runs: stops the current workers and starts the new ones.

A change is validated completely (replay file loads, rules hold) BEFORE anything is stopped, so a
bad request never leaves the adapter without a working configuration. Stopping waits for the BLE
loop (up to 8 s), which lets the trainer worker restore 0 % if a control test was running.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Optional

from coach.bluetooth.ble_runtime import BleRuntime
from coach.bluetooth.device_finder import Claims
from coach.bluetooth.device_registry import DeviceRegistry
from coach.session.diagnostics import RawCapture
from coach.devices.hr50 import hr_worker
from coach.app.rider_profile import ProfileStore
from coach.session.recording import CsvReplay, record_once
from coach.app.paths import recordings_dir, routes_dir
from coach.app.settings import Settings, SettingsStore
from coach.devices.wahoo import bluetooth_worker
from coach.devices.zwift_controllers import controller_worker

STOP_TIMEOUT_SECONDS = 8
RIDE_TICK_SECONDS = 0.25
FTP_CACHE_S = 300          # the FTP estimated from the history, when the profile has none: read every 5 min at most


def workout_ticker(state, test, stop, tick=1.0):
    """Feeds a workout (FTP test or structured) with the 1 Hz telemetry until it ends (or the configuration changes)."""
    from coach.app.server import current_reading
    while not stop.wait(tick):
        if state.workout is not test or not test.running:
            return
        try:
            reading = current_reading(state)
            reading['sessionState'] = state.session_state() if state.session_state is not None else 'RUNNING'
            test.tick(reading)
        except Exception as exc:  # the workout must never take the adapter down
            print(f'WARNING: workout tick failed: {exc}', flush=True)


def ride_ticker(state, stop, tick=RIDE_TICK_SECONDS, clock=None):
    """Moves the virtual rider 4 times a second with the live power (coach/session/virtual_ride.py)."""
    from time import monotonic
    from coach.app.server import live_power, trainer_reading
    clock = clock or monotonic
    last = clock()
    while not stop.wait(tick):
        now = clock()
        try:
            state.ride.step(now - last, live_power(trainer_reading(state)))
        except Exception as exc:  # the ride must never take the adapter down
            print(f'WARNING: virtual ride step failed: {exc}', flush=True)
        last = now


# Name filters of earlier versions. Removed: with every device remembered and no guessing among unknown ones
# (coach/bluetooth/device_finder.py) they only got in the way, e.g. a strap of another brand was never found.
IGNORED_ENV_KEYS = ('WAHOO_DEVICE_NAME', 'HR_DEVICE_NAME')


@dataclass(frozen=True)
class EnvConfig:
    """What stays in .env only."""
    control_test: bool = False
    record_dir: Path = field(default_factory=recordings_dir)
    wahoo_device_id: Optional[str] = None
    hr_device_id: Optional[str] = None
    zwift_left_id: Optional[str] = None
    zwift_right_id: Optional[str] = None
    routes_dir: Path = field(default_factory=routes_dir)
    history_db: Optional[Path] = None   # None: the data home's coach.db (coach/app/db.py)

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env

        def text(name):
            return (env.get(name) or '').strip() or None
        for key in IGNORED_ENV_KEYS:
            if text(key):
                print(f'NOTE: {key} in .env is ignored since v4.3.0: devices are found by type and remembered '
                      f'(choose them in Ajustes). You can delete that line.', flush=True)
        return cls(control_test=(env.get('CONTROL_TEST_ENABLED') or '').strip().lower() in ('1', 'true', 'yes'),
                   record_dir=Path(env.get('RECORD_DIR')).expanduser() if env.get('RECORD_DIR') else recordings_dir(),
                   wahoo_device_id=text('WAHOO_DEVICE_ID'), hr_device_id=text('HR_DEVICE_ID'),
                   zwift_left_id=text('ZWIFT_LEFT_DEVICE_ID'), zwift_right_id=text('ZWIFT_RIGHT_DEVICE_ID'))


class AdapterRuntime:
    def __init__(self, env: EnvConfig, defaults: Settings, store: Optional[SettingsStore] = None,
                 registry: Optional[DeviceRegistry] = None, start_workers=True,
                 profile_store: Optional[ProfileStore] = None):
        from coach.app.server import AdapterState  # local import: server imports this module
        self._state_class = AdapterState
        self.env = env
        self.defaults = defaults
        self.store = store
        self.registry = registry
        self.start_workers = start_workers
        self.profile_store = profile_store
        self.lock = Lock()
        self.state = None
        self.settings = None
        self.source = 'env'
        self._stop = None
        self._ble = None
        self._capture = None
        self.session = None

    # ---- public API -------------------------------------------------------------------------
    def start(self):
        settings, source = self.store.load(self.defaults) if self.store else (self.defaults, 'env')
        try:
            self._apply(settings.validate(self.env.control_test, self.env.record_dir), source)
        except (ValueError, PermissionError) as exc:
            if source != 'saved':
                raise
            print(f'WARNING: saved settings not usable ({exc}); using .env', flush=True)
            self._apply(self.defaults.validate(self.env.control_test, self.env.record_dir), 'env')
        return self

    def update(self, changes: dict):
        """Validate, persist and apply a partial change from the admin page."""
        with self.lock:
            new = self.settings.updated(changes).validate(self.env.control_test, self.env.record_dir)
            replay = self._load_replay(new)
            if self.store:
                self.store.save(new)
            self._switch(new, 'saved', replay)
            return self.describe()

    def reset_to_env(self):
        with self.lock:
            new = self.defaults.validate(self.env.control_test, self.env.record_dir)
            replay = self._load_replay(new)
            if self.store:
                self.store.reset()
            self._switch(new, 'env', replay)
            return self.describe()

    def describe(self):
        return {'settings': self.settings.to_json(), 'source': self.source,
                'envDefaults': self.defaults.to_json(),
                'settingsFile': str(self.store.path) if self.store else None,
                'controlTestEnabled': self.env.control_test,
                'recordingsDir': str(self.env.record_dir),
                'modes': ['SIMULATOR', 'WAHOO', 'REPLAY']}

    def shutdown(self):
        with self.lock:
            if self.session is not None:
                self.session.finish_if_active('application stopped')
            self._stop_workers()

    def profile_changed(self, profile):
        """The rider saved the profile: the grade difficulty and limits apply without restarting."""
        self._ftp_estimate = None
        state = self.state
        if state is not None and state.ride is not None:
            state.ride.set_profile(profile.rider_weight_kg, profile.bike_weight_kg,
                                   profile.grade_transition_m_per_percent, profile.bike_type)
        if state is not None and state.grade is not None:
            from coach.devices.grade_controller import GradePrefs
            state.grade.set_prefs(GradePrefs.from_profile(profile))

    # ---- workouts: FTP test (coach/workouts/ramp_test.py) and structured (coach/workouts/structured.py) ----
    def _can_start_workout(self):
        state = self.state
        if state.mode == 'REPLAY':
            raise PermissionError('Workouts need the trainer or the simulator, not REPLAY')
        if state.workout is not None and state.workout.running:
            raise PermissionError('A workout is already running')
        if state.ride is not None and state.ride.route is not None and not state.ride.route_finished:
            raise PermissionError('Leave the route first: workouts are ridden on the flat')

    def _run_workout(self, workout):
        """Show it, feed it, and record it in a session (one is started if none is running)."""
        state = self.state
        if self.session is not None and self.session.snapshot()['sessionState'] == 'IDLE':
            self.session.start()
        state.workout = workout
        stop = self._stop
        if self.start_workers and stop is not None:
            Thread(target=workout_ticker, args=(state, workout, stop), daemon=True, name='workout').start()
        return workout.snapshot()

    def workout_ftp(self):
        """(FTP, source): the profile's, else the one estimated from the history (coach/history/load.derive_params,
        the same for the training load, the workouts and the zones). The estimate is kept FTP_CACHE_S seconds."""
        ftp = self._ftp()
        if ftp:
            return ftp, 'profile'
        from time import monotonic
        cached = getattr(self, '_ftp_estimate', None)
        if cached is not None and monotonic() - cached[0] < FTP_CACHE_S:
            return cached[1]
        result = self._estimate_ftp()
        self._ftp_estimate = (monotonic(), result)
        return result

    def _estimate_ftp(self):
        try:
            from coach.history.load import derive_params
            from coach.history.store import HistoryStore
            store = HistoryStore(self.env.history_db) if self.env.history_db else HistoryStore.default()
            profile = self.profile_store.load()[0] if self.profile_store is not None else None
            params = derive_params(profile, store.list(100000))
            if params.ftp:
                return params.ftp, params.ftp_source or 'history'
        except Exception as exc:  # no history: no estimate
            print(f'WARNING: no FTP estimate from the history: {exc}', flush=True)
        return None, None

    def workout_library(self):
        from coach.workouts.structured import LIBRARY
        ftp, source = self.workout_ftp()
        return {'ftpW': ftp, 'ftpSource': source, 'workouts': [w.to_json(ftp) for w in LIBRARY.values()]}

    def start_structured(self, options: dict):
        from coach.workouts.structured import LIBRARY, StructuredWorkout
        self._can_start_workout()
        definition = LIBRARY.get(options.get('id'))
        if definition is None:
            raise ValueError(f'id must be one of: {", ".join(LIBRARY)}')
        ftp, source = self.workout_ftp()
        if not ftp:
            raise PermissionError('The targets need an FTP: do the FTP test or enter it in Ajustes')
        return self._run_workout(StructuredWorkout(definition, ftp, source))

    def workout_summary(self) -> dict:
        """For the session summary: the workout ridden in it (ended first if it was still running)."""
        workout = self.state.workout if self.state is not None else None
        if workout is None:
            return {}
        if workout.running:
            workout.finish('session finished')
        return {'workout': workout.summary()}

    def start_ramp_test(self, options: dict):
        """Start the ramp FTP test (and a session to record it, if none is running)."""
        from coach.workouts.ramp_test import RampTest
        self._can_start_workout()
        ftp = self._ftp()
        start_w = options.get('startW', max(50, int(round(ftp * 0.4 / 10) * 10)) if ftp else 100)
        step_w = options.get('stepW', 20)
        for name, value, low, high in (('startW', start_w, 50, 300), ('stepW', step_w, 10, 40)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} must be a whole number between {low} and {high}')
        return self._run_workout(RampTest(start_w=start_w, step_w=step_w))

    def stop_workout(self):
        if self.state.workout is None:
            raise PermissionError('No workout is running')
        self.state.workout.finish('rider finished')
        return self.state.workout.snapshot()

    def save_test_ftp(self):
        test = self.state.workout
        if test is None or test.ftp is None:
            raise PermissionError('There is no FTP result to save')
        if self.profile_store is None:
            raise PermissionError('No rider profile store')
        profile = self.profile_store.update({'ftpWatts': test.ftp})
        self.profile_changed(profile)
        return {'ftpWatts': profile.ftp_watts}

    def clear_workout(self):
        if self.state.workout is not None and self.state.workout.running:
            raise PermissionError('Stop the workout first')
        self.state.workout = None
        return {'workout': None}

    def _rider_kg(self):
        if self.profile_store is None:
            return None
        return self.profile_store.load()[0].rider_weight_kg

    def _ftp(self):
        if self.profile_store is None:
            return None
        profile, _saved = self.profile_store.load()
        return profile.ftp_watts

    # ---- internals ----------------------------------------------------------------------------
    def _apply(self, settings, source):
        with self.lock:
            self._switch(settings, source, self._load_replay(settings))

    def _load_replay(self, settings):
        return CsvReplay(settings.replay_path(self.env.record_dir)) if settings.mode == 'REPLAY' else None

    def _switch(self, settings, source, replay):
        if self.session is not None:
            self.session.finish_if_active('settings changed')
            self.session = None
        self._stop_workers()
        state = self._state_class(mode=settings.mode, replay=replay, hr_enabled=settings.hr_enabled,
                                  registry=self.registry)
        from coach.app.rider_profile import RiderProfile
        profile = self.profile_store.load()[0] if self.profile_store else RiderProfile()
        if settings.mode != 'REPLAY' and not self.env.control_test:
            # The virtual road: physics speed, distance, elevation (the FTMS control test keeps its own grade).
            from coach.session.virtual_ride import VirtualRide
            state.ride = VirtualRide(profile.rider_weight_kg, profile.bike_weight_kg,
                                     profile.grade_transition_m_per_percent, profile.bike_type)
        if settings.mode == 'WAHOO' and settings.gear_control_enabled and state.ride is not None:
            # Grade on the same native channel as the gears; it only moves when the rider picks a grade.
            from coach.devices.grade_controller import GradeController, GradePrefs
            state.grade = GradeController(GradePrefs.from_profile(profile), ride=state.ride)
        stop = Event()
        if self.start_workers:
            self._start_workers(settings, state, stop)
            if state.ride is not None:
                Thread(target=ride_ticker, args=(state, stop), daemon=True, name='virtual-ride').start()
        self._stop = stop
        if settings.mode != 'REPLAY':
            from coach.app.server import current_reading
            from coach.session.session import SessionManager
            self.session = SessionManager(lambda state=state: current_reading(state), self.env.record_dir,
                                          ftp=self._ftp, capture=self._capture, rider_kg=self._rider_kg,
                                          extra=self.workout_summary)
            state.session_state = lambda session=self.session: session.state
        state.rider_ftp = self.workout_ftp
        self.state = state  # one reference swap: HTTP handlers see the old or the new state, never a mix
        self.settings = settings
        self.source = source
        print(f'Adapter settings ({source}): {settings.to_json()}', flush=True)

    def _stop_workers(self):
        if self._stop is not None:
            self._stop.set()
        if self._ble is not None:
            self._ble.join(timeout=STOP_TIMEOUT_SECONDS)
        if self._capture is not None:
            self._capture.close()
        self._stop = self._ble = self._capture = None

    def _start_workers(self, settings, state, stop):
        env = self.env
        # Raw Bluetooth capture: in a training session (begin/end with the session) or, for the supervised
        # FTMS grade test only, the old automatic 600 s recording starting at the first pedal stroke.
        recording = settings.mode == 'WAHOO' and settings.record_enabled
        folder = env.record_dir
        capture = (RawCapture(folder, seconds=settings.record_seconds, manual=not env.control_test)
                   if recording else None)
        ble = BleRuntime(stop)
        if settings.zwift_enabled:
            claims = Claims()
            for side, device_id in (('left', env.zwift_left_id), ('right', env.zwift_right_id)):
                ble.add(f'zwift-{side}', lambda scan_lock, side=side, device_id=device_id: controller_worker(
                    state.controllers, side, device_id, stop, scan_lock=scan_lock,
                    registry=self.registry, claims=claims))
        else:
            for side in ('left', 'right'):
                state.controllers.set_status(side, False, 'DISABLED')
        shifter = None
        if settings.mode == 'WAHOO' and settings.gear_control_enabled:
            from coach.devices.gear_shifter import GearShifter
            profile, _saved = self.profile_store.load() if self.profile_store else (None, False)
            from coach.app.rider_profile import RiderProfile
            profile = profile or RiderProfile()
            from coach.session.virtual_ride import BIKE_PHYSICS
            shifter = GearShifter(state.controllers, rider_kg=profile.rider_weight_kg, bike_kg=profile.bike_weight_kg,
                                  crr_x100000=round(BIKE_PHYSICS[profile.bike_type][1] * 100000))
        if settings.mode == 'WAHOO':
            ble.add('wahoo', lambda scan_lock: bluetooth_worker(
                state.store, stop, device_id=env.wahoo_device_id,
                capture=capture, capture_dir=folder if recording else None,
                control_test=env.control_test, scan_lock=scan_lock, registry=self.registry, shifter=shifter,
                grade=state.grade))
        if settings.hr_enabled and settings.mode != 'REPLAY':
            ble.add('hr', lambda scan_lock: hr_worker(
                state.hr_store, stop, device_id=env.hr_device_id,
                capture=capture, scan_lock=scan_lock, registry=self.registry))
        ble.start()
        if recording and env.control_test:
            Thread(target=lambda: record_once(state.store.snapshot, state.hr_store.snapshot, stop, folder,
                                              seconds=settings.record_seconds),
                   daemon=True, name='csv-recorder').start()
        self._ble, self._capture = ble, capture
