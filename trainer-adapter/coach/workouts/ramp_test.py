"""Ramp FTP test, without ERG: the app shows a target that rises every minute; the rider reaches it with the gears.

Protocol (the usual ramp test, as in Zwift's and TrainerRoad's):
  warm-up  ``warmup_s`` (5 min) easy: no target, the rider settles in
  ramp     steps of ``step_s`` (1 min); the first at ``start_w`` (100 W, or 40 % of a known FTP), then +``step_w``
           (20 W) each minute, until the rider cannot hold it
  end      when the rider stops pedalling (cadence under 40 rpm, or no live data) for ``stop_after_s`` (5 s), or
           presses «He terminado»
Result: FTP = 75 % of the best 60 s average power of the ramp (the standard ramp-test estimate). Without ERG the
target is a guide only: the result depends on the best minute actually ridden, not on matching the target. A ramp
shorter than ``min_ramp_s`` (3 min) gives no FTP: it would say nothing about the rider.

Never touches the trainer by itself (no power target is sent): it only reads the 1 Hz telemetry.
"""
from time import monotonic
from typing import List, Optional

FTP_FACTOR = 0.75
BEST_WINDOW_S = 60


class RampTest:
    def __init__(self, start_w: int = 100, step_w: int = 20, warmup_s: float = 300, step_s: float = 60,
                 stop_after_s: float = 5, min_ramp_s: float = 180, min_cadence: float = 40, clock=monotonic):
        self.start_w, self.step_w = start_w, step_w
        self.warmup_s, self.step_s = warmup_s, step_s
        self.stop_after_s, self.min_ramp_s, self.min_cadence = stop_after_s, min_ramp_s, min_cadence
        self.clock = clock
        self.started = clock()
        self.phase = 'WARMUP'
        self.ramp_started: Optional[float] = None
        self.ramp_ended: Optional[float] = None
        self.powers: List[Optional[float]] = []     # 1 Hz during the ramp; None = no live data
        self.low_since: Optional[float] = None
        self.reason: Optional[str] = None
        self.best_60s: Optional[float] = None
        self.ftp: Optional[int] = None
        self.max_hr: Optional[float] = None
        self.saved = False           # «Guardar como mi FTP» (coach/history/ftp_log.py: the test was accepted)

    @property
    def running(self) -> bool:
        return self.phase in ('WARMUP', 'RAMP')

    def summary(self) -> dict:
        """What the session summary keeps (session_<stamp>.json → «workout»)."""
        return {'type': 'RAMP_TEST', 'name': 'Test de FTP (rampa)', 'endReason': self.reason,
                'best60sW': _round(self.best_60s), 'ftpW': self.ftp, 'maxHeartRate': self.max_hr,
                'startW': self.start_w, 'stepW': self.step_w, 'savedAsFtp': self.saved}

    # ---- clock ----
    def elapsed(self) -> float:
        return self.clock() - self.started

    def step(self) -> Optional[int]:
        """Ramp step number (1, 2, …) or None outside the ramp."""
        if self.phase != 'RAMP':
            return None
        return int((self.clock() - self.ramp_started) // self.step_s) + 1

    def target_w(self) -> Optional[int]:
        step = self.step()
        return None if step is None else self.start_w + (step - 1) * self.step_w

    # ---- 1 Hz telemetry ----
    def tick(self, reading: dict):
        if self.phase not in ('WARMUP', 'RAMP'):
            return
        now = self.clock()
        if self.phase == 'WARMUP' and now - self.started >= self.warmup_s:
            self.phase, self.ramp_started = 'RAMP', now
        if self.phase != 'RAMP':
            return
        live = bool(reading.get('connected'))
        power = float(reading.get('powerWatts') or 0) if live else None
        self.powers.append(power)
        heart = reading.get('heartRateBpm') if reading.get('heartRateConnected') else None
        if heart:
            self.max_hr = max(self.max_hr or 0, float(heart))
        pedalling = live and (reading.get('cadenceRpm') or 0) >= self.min_cadence
        if pedalling:
            self.low_since = None
        else:
            self.low_since = self.low_since if self.low_since is not None else now
            if now - self.low_since >= self.stop_after_s:
                self.finish('stopped pedalling')

    # ---- end ----
    def finish(self, reason: str = 'rider finished'):
        if self.phase == 'WARMUP':
            self.phase, self.reason = 'ABORTED', reason
            return
        if self.phase != 'RAMP':
            return
        self.phase, self.reason, self.ramp_ended = 'DONE', reason, self.clock()
        self.best_60s = best_average(self.powers, BEST_WINDOW_S)
        ramp_s = self.ramp_ended - self.ramp_started
        if self.best_60s is not None and ramp_s >= self.min_ramp_s:
            self.ftp = int(round(self.best_60s * FTP_FACTOR))

    def _best_so_far(self) -> Optional[int]:
        return _round(self.best_60s if self.phase == 'DONE' else best_average(self.powers, BEST_WINDOW_S))

    def snapshot(self) -> dict:
        running = self.phase in ('WARMUP', 'RAMP')
        now = self.clock()
        if self.phase == 'WARMUP':
            remaining = self.warmup_s - (now - self.started)
        elif self.phase == 'RAMP':
            remaining = self.step_s - ((now - self.ramp_started) % self.step_s)
        else:
            remaining = None
        return {'workoutType': 'RAMP_TEST', 'workoutPhase': self.phase, 'workoutRunning': running,
                'workoutElapsedS': round(self.elapsed()), 'workoutStep': self.step(),
                'workoutStepRemainingS': None if remaining is None else max(0, round(remaining)),
                'targetPowerW': self.target_w(), 'workoutStartW': self.start_w, 'workoutStepW': self.step_w,
                'rampBest60sW': self._best_so_far(),
                'ftpEstimateW': self.ftp, 'workoutEndReason': self.reason,
                'rampMaxHeartRate': self.max_hr}


def _round(value):
    return None if value is None else round(value)


def best_average(values: List[Optional[float]], window: int) -> Optional[float]:
    """Best mean of ``window`` consecutive live samples (None breaks the window)."""
    best, run, total = None, [], 0.0
    for value in values:
        if value is None:
            run, total = [], 0.0
            continue
        run.append(value)
        total += value
        if len(run) > window:
            total -= run.pop(0)
        if len(run) == window:
            best = max(best or 0.0, total / window)
    return best
