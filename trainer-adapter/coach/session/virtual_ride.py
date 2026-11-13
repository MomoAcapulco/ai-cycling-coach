"""The virtual road the rider is on: speed from power (physics), distance, altitude and elevation gain.

Why compute the speed: in Zwift mode the trainer reports its own virtual speed, physics with inertia, but for
the grade the trainer APPLIES, which is the road grade after the difficulty (50 % by default): on an 8 % climb
it rides a 4 % one, and its speed would be too high for the real climb. Without native control (free mode) its
speed is just the flywheel's. Zwift likewise takes the speed from the power and the real grade (as documented
publicly; its code is closed).
Validated in the grade test (diagnostics/zwift_grade_test_20261113_123554.json): at the same power and grade the
speeds below are within ~1 km/h of the trainer's own in steady riding, and CdA 0.40 fits best of 0.25-0.40.
Cross-checked with Incyclist (MIT, incyclist/devices src/utils/calculations.ts @07e0035): same equation; it uses
cwA 0.35 (an average 1.80 m / 75 kg rider), Crr 0.0036, rho 1.2041 and no inertia. Same speeds on climbs
(200 W, 89.5 kg, 8 %: 9.6 km/h both), ours ~5 % slower on the flat (CdA 0.40, chosen by the trainer data).

Model (forces along the road, SI units):
  drive   P / max(v, 1 m/s)                        (the floor keeps the start-up force finite)
  gravity m·g·sin(θ)
  rolling m·g·Crr·cos(θ)                          Crr 0.004, the value we send to the trainer
  air     ½·ρ·CdA·v²                              ρ 1.225 kg/m³, CdA 0.40 m² (hoods, a tall rider)
  a = (drive − gravity − rolling − air) / (m + 1.5 kg of rotating wheels)
Power comes from the trainer, which measures after the drivetrain: no drivetrain loss is added.
Example: 200 W with 89 kg in total gives ~32 km/h on the flat, ~14 km/h at 5 % and ~10 km/h at 8 %.
No pedalling: the rider coasts (and slows down on the flat or a climb, speeds up downhill); never rolls back.

Grade, like a real road: the rider chooses a TARGET grade; the ROAD grade moves towards it by at most 1 % every
``meters_per_percent`` metres travelled (20 m by default: 0 → 5 % takes ~100 m). Stopped, it does not change.
The elevation uses the road grade (the real climb), not the grade the trainer applies after the difficulty —
as Zwift does: with 50 % difficulty you feel half the climb, but you have climbed all of it.

Routes (coach/session/route.py): choosing a GPX route is choosing the grade. While it is active the TARGET is the
route's grade at the distance ridden since it started (the transition by distance still applies), manual grade
requests are refused, and at its end the target becomes flat. Leaving it keeps the current road grade as target.
"""
import math
from threading import Lock
from typing import Optional

G = 9.80665
RHO = 1.225
CDA_M2 = 0.40
CRR = 0.004
WHEELS_KG = 1.5
SPEED_FLOOR_MS = 1.0
MAX_STEP_S = 0.25


class VirtualRide:
    def __init__(self, rider_kg: float = 75.0, bike_kg: float = 9.0, meters_per_percent: float = 20.0):
        self.lock = Lock()
        self.rider_kg, self.bike_kg = rider_kg, bike_kg
        self.meters_per_percent = meters_per_percent
        self.target_grade: Optional[float] = None   # None: the rider has not chosen (flat start)
        self.road_grade = 0.0
        self.speed_ms = 0.0
        self.distance_m = 0.0
        self.altitude_m = 0.0
        self.gain_m = 0.0
        self.vertical_ms = 0.0
        self.route = None
        self.route_start_m = 0.0
        self.route_finished = False

    # ---- rider ----
    def request(self, grade_percent) -> float:
        from coach.devices.grade_controller import validate_target
        value = validate_target(grade_percent)
        with self.lock:
            if self.route is not None and not self.route_finished:
                raise PermissionError('A route is being ridden: leave it to choose the grade by hand')
            self.route = None if self.route_finished else self.route
            self.target_grade = value
        return value

    def start_route(self, route):
        """Ride ``route`` (coach/session/route.Route) from here: its distance 0 is the current position."""
        with self.lock:
            self.route, self.route_start_m, self.route_finished = route, self.distance_m, False
            self.target_grade = route.grade_at(0)

    def stop_route(self):
        with self.lock:
            if self.route is not None:
                self.route = None
                self.route_finished = False
                self.target_grade = round(self.road_grade, 1)   # no change felt when leaving the route

    def route_progress_m(self) -> float:
        return 0.0 if self.route is None else min(self.distance_m - self.route_start_m, self.route.distance_m)

    def set_profile(self, rider_kg: float, bike_kg: float, meters_per_percent: float):
        with self.lock:
            self.rider_kg, self.bike_kg, self.meters_per_percent = rider_kg, bike_kg, meters_per_percent

    @property
    def mass_kg(self) -> float:
        return self.rider_kg + self.bike_kg

    # ---- physics ----
    def step(self, dt: float, power_w: float):
        """Advance ``dt`` seconds with ``power_w`` (0 when not pedalling or no live data)."""
        dt = min(max(float(dt), 0.0), 2.0)  # a stalled caller never makes the rider jump far
        power = max(0.0, float(power_w or 0))
        with self.lock:
            while dt > 1e-9:
                h = min(dt, MAX_STEP_S)
                self._substep(h, power)
                dt -= h

    def _substep(self, h, power):
        if self.route is not None and not self.route_finished:
            grade = self.route.grade_at(self.distance_m - self.route_start_m)
            if grade is None:
                self.route_finished, self.target_grade = True, 0.0   # end of the route: flat
            else:
                self.target_grade = grade
        theta = math.atan(self.road_grade / 100)
        mass = self.mass_kg
        drive = power / max(self.speed_ms, SPEED_FLOOR_MS) if power > 0 else 0.0
        gravity = mass * G * math.sin(theta)
        rolling = mass * G * CRR * math.cos(theta)
        air = 0.5 * RHO * CDA_M2 * self.speed_ms ** 2
        push = drive - gravity - air
        if self.speed_ms <= 0 and push <= rolling:
            new_speed = 0.0                         # standing still: rolling resistance holds it, no roll-back
        else:
            new_speed = max(0.0, self.speed_ms + (push - rolling) / (mass + WHEELS_KG) * h)
        moved = (self.speed_ms + new_speed) / 2 * h
        self.speed_ms = new_speed
        rise = moved * math.sin(theta)
        self.distance_m += moved
        self.altitude_m += rise
        self.gain_m += max(0.0, rise)
        self.vertical_ms = rise / h if h else 0.0
        # the road grade moves towards the target by the metres actually ridden in this step
        goal = 0.0 if self.target_grade is None else self.target_grade
        if goal != self.road_grade:
            change = moved / self.meters_per_percent
            if abs(goal - self.road_grade) <= change:
                self.road_grade = goal
            else:
                self.road_grade += math.copysign(change, goal - self.road_grade)

    @staticmethod
    def steady_speed_ms(power_w: float, grade_percent: float, mass_kg: float) -> float:
        """Speed where the forces balance (for tests and documentation)."""
        theta = math.atan(grade_percent / 100)
        resist = mass_kg * G * (math.sin(theta) + CRR * math.cos(theta))

        def excess(v):
            return power_w - v * (resist + 0.5 * RHO * CDA_M2 * v * v)
        low, high = 0.0, 40.0
        if excess(1e-6) <= 0:
            return 0.0
        for _ in range(80):
            mid = (low + high) / 2
            low, high = (mid, high) if excess(mid) > 0 else (low, mid)
        return low

    # ---- telemetry ----
    def snapshot(self, power_w: Optional[float] = None) -> dict:
        with self.lock:
            return {
                'targetGradePercent': None if self.target_grade is None else round(self.target_grade, 2),
                'roadGradePercent': round(self.road_grade, 2),
                'rideSpeedKph': round(self.speed_ms * 3.6, 2),
                'rideDistanceKm': round(self.distance_m / 1000, 4),
                'altitudeM': round(self.altitude_m, 1),
                'elevationGainM': round(self.gain_m, 1),
                'vamMh': round(max(0.0, self.vertical_ms) * 3600),
                'wattsPerKg': round(power_w / self.rider_kg, 2) if power_w and self.rider_kg else None,
                'gradeTransitionMetersPerPercent': self.meters_per_percent,
                'routeFile': self.route.file if self.route else None,
                'routeName': self.route.name if self.route else None,
                'routeDistanceKm': round(self.route.distance_m / 1000, 3) if self.route else None,
                'routeProgressKm': round(self.route_progress_m() / 1000, 3) if self.route else None,
                'routeFinished': self.route_finished if self.route else None,
            }
