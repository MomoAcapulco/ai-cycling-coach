"""Grade (slope) on the trainer over the native Zwift channel, chosen ONLY by the rider.

The grade never changes by itself: until the rider picks one, the trainer stays at the start grade that
``GearShifter`` sends (0.4 %). Chain from the rider's choice to the trainer:

  target     what the rider asked for (Panel): ``VirtualRide.target_grade``
  road       the road grade, moving towards the target by DISTANCE (1 % every 20 m by default), like a real
             road (coach/session/virtual_ride.py): no 0 → 5 % wall, and stopped it does not change
  effective  road × difficulty (uphill) or × difficulty × descent factor (downhill), clipped to the rider's
             [min, max] — the rider profile holds these, like Zwift's "trainer difficulty"
  applied    the effective grade, but never more than ``max_rise_per_s`` (1 %/s) harder per second: a safety
             net (e.g. a reconnect, or a difficulty raised while climbing); easier follows at once
  sent       what was written: only if it moved >= 0.1 % and >= 1 s passed since the last write; re-sent
             every 10 s even if unchanged (Serpentine); an exact 0 is sent as 0.01 %

Safety (each rule has a test in tests/test_grade_controller.py):
- Never harder without a live, pedalling trainer (FTMS fresh and cadence >= 40 rpm): the applied grade
  holds; easier is always allowed.
- After a (re)connect the trainer is at 0.4 % (GearShifter.start): the applied grade restarts from there and
  rises at most 1 %/s, so a reconnect never jumps straight to the old grade.
- On exit GearShifter.finish leaves 0.4 % and gear 12; this controller only marks itself stopped.
- Every write goes through ``SafeZwiftWriter`` with ``incline_limits`` = the rider's [min, max].

Confirmation (measured in the supervised grade test, diagnostics/zwift_grade_test_20261113_123554.json):
every grade written is followed by HubRequest 512, whose answer carries the grade the trainer APPLIED
(zwift_hub.decode_hub_response → ``inclineX100``). The UI shows "applied" only when that answer matches; without
an answer within ``confirm_timeout_s`` the grade is written again, up to ``max_retries``, then the status is
UNCONFIRMED (the 10 s refresh keeps trying). An exact 0 % is sent as 0: the test showed it is applied and that
gears keep working at 0 % on this trainer.
"""
import math
from dataclasses import dataclass
from time import monotonic
from typing import Optional

from coach.devices.zwift_hub import (DATA_ID_SIMULATION, Simulation, decode_hub_response, encode_hub_command,
                                     encode_hub_request)

START_INCLINE_X100 = 40          # 0.4 %: what GearShifter.start/finish send
ZERO_INCLINE_X100 = 0            # 0 % is sent as 0: measured safe for gears (Incyclist sends 0.01 % instead)
TARGET_RANGE = (-15.0, 20.0)     # what the rider may ask for, in %
HARD_LIMITS_X100 = (-1000, 2000)  # never written whatever the profile says: -10 % .. +20 %


@dataclass(frozen=True)
class GradePrefs:
    difficulty_percent: int = 50       # Zwift's default trainer difficulty
    descent_factor_percent: int = 50
    max_grade_percent: float = 10.0
    min_grade_percent: float = -5.0
    crr_x100000: int = 400             # rolling resistance sent with every grade: the bike type's (road 0.004)

    @classmethod
    def from_profile(cls, profile):
        from coach.session.virtual_ride import BIKE_PHYSICS
        return cls(profile.grade_difficulty_percent, profile.grade_descent_factor_percent,
                   profile.max_grade_percent, profile.min_grade_percent,
                   round(BIKE_PHYSICS[profile.bike_type][1] * 100000))

    def limits_x100(self):
        return round(self.min_grade_percent * 100), round(self.max_grade_percent * 100)

    def effective(self, target: float) -> float:
        factor = self.difficulty_percent / 100
        if target < 0:
            factor *= self.descent_factor_percent / 100
        return min(self.max_grade_percent, max(self.min_grade_percent, target * factor))


def validate_target(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('gradePercent must be a number')
    low, high = TARGET_RANGE
    if not low <= value <= high:
        raise ValueError(f'gradePercent must be between {low:g} and {high:g}')
    return round(float(value), 1)


class GradeController:
    def __init__(self, prefs: GradePrefs = GradePrefs(), ride=None, clock=monotonic, min_cadence=40,
                 max_rise_per_s=1.0, min_step_x100=10, min_interval_s=1.0, refresh_s=10.0,
                 confirm_timeout_s=1.5, max_retries=3):
        from coach.session.virtual_ride import VirtualRide
        self.prefs = prefs
        self.ride = ride if ride is not None else VirtualRide()
        self.clock = clock
        self.min_cadence, self.max_rise_per_s = min_cadence, max_rise_per_s
        self.min_step_x100, self.min_interval_s, self.refresh_s = min_step_x100, min_interval_s, refresh_s
        self.applied = START_INCLINE_X100 / 100
        self.sent_x100: Optional[int] = None
        self.sent_at = 0.0
        self.last_tick: Optional[float] = None
        self.status = 'STARTING'
        self.held = False
        self.confirm_timeout_s, self.max_retries = confirm_timeout_s, max_retries
        self.confirmed_x100: Optional[int] = None   # what the trainer said it applied (answer to 512)
        self.retries = 0
        self.unconfirmed = False

    # ---- rider ----
    def set_prefs(self, prefs: GradePrefs):
        self.prefs = prefs

    def limits_x100(self):
        return self.prefs.limits_x100()

    def effective(self) -> Optional[float]:
        """What the trainer should apply now: the road grade after difficulty and limits."""
        if self.ride.target_grade is None:
            return None
        return round(self.prefs.effective(self.ride.road_grade), 2)

    # ---- messages from the trainer ----
    def on_message(self, raw: bytes):
        response = decode_hub_response(raw)
        if response and response.get('dataId') == DATA_ID_SIMULATION and 'inclineX100' in response:
            self.confirmed_x100 = response['inclineX100']
            if self.confirmed_x100 == self.sent_x100:
                self.retries, self.unconfirmed = 0, False

    def confirmed(self) -> bool:
        return self.sent_x100 is not None and self.confirmed_x100 == self.sent_x100

    # ---- trainer worker ----
    def start(self):
        """After GearShifter.start (connect or reconnect): the trainer is at 0.4 %, rise from there."""
        self.applied = START_INCLINE_X100 / 100
        self.sent_x100 = START_INCLINE_X100
        self.sent_at = self.clock()
        self.last_tick = None
        self.confirmed_x100, self.retries, self.unconfirmed = None, 0, False
        self.status = 'FLAT_START' if self.ride.target_grade is None else 'RAMPING'

    async def tick(self, writer, trainer: dict):
        now = self.clock()
        dt = 0.0 if self.last_tick is None else min(max(now - self.last_tick, 0.0), 0.5)
        self.last_tick = now
        if self.ride.target_grade is None:
            self.status = 'FLAT_START'
            return
        goal = self.prefs.effective(self.ride.road_grade)
        self.held = False
        if goal > self.applied:
            if self._pedalling(trainer):
                self.applied = min(goal, self.applied + self.max_rise_per_s * dt)
            else:
                self.held = True  # never harder without a live, pedalling trainer
        else:
            self.applied = goal  # easier: at once (the road already changes gradually)
        settled = self.applied == goal and self.ride.road_grade == self.ride.target_grade
        self.status = 'HOLD_NOT_PEDALLING' if self.held else ('SET' if settled else 'RAMPING')

        x100 = self._to_x100(self.applied)
        since = now - self.sent_at
        changed = self.sent_x100 is None or x100 != self.sent_x100
        due = (changed and since >= self.min_interval_s
               and (self.sent_x100 is None or abs(x100 - self.sent_x100) >= self.min_step_x100
                    or settled))  # a change below 0.1 % only once the road has reached the target
        if not due and since >= self.refresh_s:
            due = True  # periodic re-send of the same (or settled) value
        if not due and not changed and not self.confirmed() and since >= self.confirm_timeout_s:
            if self.retries < self.max_retries:
                self.retries += 1  # the trainer did not confirm it: write the same grade again
                due = True
            else:
                self.unconfirmed = True  # keep riding; the 10 s refresh keeps trying
        if self.unconfirmed and self.status == 'SET':
            self.status = 'UNCONFIRMED'   # movement states (HOLD_NOT_PEDALLING, RAMPING) say more
        if not due:
            return
        if self.sent_x100 is not None and x100 > self.sent_x100 and not self._pedalling(trainer):
            return  # belt and braces: a harder write is never made while not pedalling
        if x100 != self.sent_x100:
            self.retries, self.unconfirmed = 0, False
        await writer.write(encode_hub_command(simulation=Simulation(incline_x100=x100, crr_x100000=self.prefs.crr_x100000)))
        await writer.write(encode_hub_request(DATA_ID_SIMULATION))   # ask what the trainer applied
        self.sent_x100, self.sent_at = x100, now

    def stopped(self):
        """GearShifter.finish has left the trainer at 0.4 %."""
        self.sent_x100 = START_INCLINE_X100
        self.applied = START_INCLINE_X100 / 100
        self.status = 'STOPPED'

    def disconnected(self):
        self.sent_x100 = None
        self.status = 'DISCONNECTED'

    # ---- helpers ----
    def _to_x100(self, grade: float) -> int:
        low, high = self.limits_x100()
        x100 = max(low, min(high, round(grade * 100)))
        return ZERO_INCLINE_X100 if x100 == 0 else x100

    def _pedalling(self, trainer: dict) -> bool:
        return bool(trainer.get('connected')) and (trainer.get('cadenceRpm') or 0) >= self.min_cadence

    def snapshot(self):
        return {'gradeControlMode': 'TRAINER',
                'effectiveGradePercent': self.effective(),
                'sentGradePercent': None if self.sent_x100 is None else self.sent_x100 / 100,
                'appliedGradePercent': None if self.confirmed_x100 is None else self.confirmed_x100 / 100,
                'gradeConfirmed': self.confirmed(),
                'gradeStatus': self.status,
                'gradeDifficultyPercent': self.prefs.difficulty_percent,
                'gradeDescentFactorPercent': self.prefs.descent_factor_percent,
                'gradeMinPercent': self.prefs.min_grade_percent, 'gradeMaxPercent': self.prefs.max_grade_percent}
