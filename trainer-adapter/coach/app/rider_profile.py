"""Rider profile: the per-user numbers that physics, safety limits and metrics depend on.

Stored in ``profile.json`` in the data home (coach/app/paths.py) (override with PROFILE_FILE), outside the version
folders. Editing it never restarts the Bluetooth workers. Values outside realistic ranges are
rejected rather than clamped, so a typo (800 kg) is reported instead of silently used.
"""
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

DRIVETRAINS = ('ZWIFT_COG', 'CASSETTE')
LIMITS = {
    'rider_weight_kg': (30.0, 250.0),
    'bike_weight_kg': (3.0, 40.0),
    'ftp_watts': (50, 600),
    # Grade on the trainer (coach/devices/grade_controller.py): like Zwift's "trainer difficulty".
    'grade_difficulty_percent': (0, 100),
    'grade_descent_factor_percent': (0, 100),
    'max_grade_percent': (0.5, 20.0),
    'min_grade_percent': (-10.0, 0.0),
    # Road grade transitions by distance (coach/session/virtual_ride.py): metres for each 1 % of change.
    'grade_transition_m_per_percent': (5.0, 100.0),
}
FIELDS = {'riderWeightKg': 'rider_weight_kg', 'bikeWeightKg': 'bike_weight_kg', 'ftpWatts': 'ftp_watts',
          'drivetrain': 'drivetrain', 'gradeDifficultyPercent': 'grade_difficulty_percent',
          'gradeDescentFactorPercent': 'grade_descent_factor_percent', 'maxGradePercent': 'max_grade_percent',
          'minGradePercent': 'min_grade_percent', 'gradeTransitionMetersPerPercent': 'grade_transition_m_per_percent'}
WHOLE_NUMBERS = ('grade_difficulty_percent', 'grade_descent_factor_percent')
DECIMALS = ('rider_weight_kg', 'bike_weight_kg', 'max_grade_percent', 'min_grade_percent',
            'grade_transition_m_per_percent')


@dataclass(frozen=True)
class RiderProfile:
    rider_weight_kg: float = 75.0
    bike_weight_kg: float = 9.0
    ftp_watts: Optional[int] = None  # unknown until measured: metrics that need it say so
    drivetrain: str = 'CASSETTE'
    grade_difficulty_percent: int = 50      # 50 % = Zwift's default: a 10 % climb feels like 5 %
    grade_descent_factor_percent: int = 50  # downhill: a further 50 %, so descents never pull too hard
    max_grade_percent: float = 10.0         # effective grade caps, after difficulty
    min_grade_percent: float = -5.0
    grade_transition_m_per_percent: float = 20.0  # 0 → 5 % over ~100 m, like a real road

    @property
    def total_mass_kg(self) -> float:
        return round(self.rider_weight_kg + self.bike_weight_kg, 2)

    def to_json(self):
        return {'riderWeightKg': self.rider_weight_kg, 'bikeWeightKg': self.bike_weight_kg,
                'ftpWatts': self.ftp_watts, 'drivetrain': self.drivetrain, 'totalMassKg': self.total_mass_kg,
                'gradeDifficultyPercent': self.grade_difficulty_percent,
                'gradeDescentFactorPercent': self.grade_descent_factor_percent,
                'maxGradePercent': self.max_grade_percent, 'minGradePercent': self.min_grade_percent,
                'gradeTransitionMetersPerPercent': self.grade_transition_m_per_percent}

    def updated(self, data: dict) -> 'RiderProfile':
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
        unknown = set(data) - set(FIELDS) - {'totalMassKg'}
        if unknown:
            raise ValueError(f'Unknown profile fields: {", ".join(sorted(unknown))}')
        changes = {}
        for key, value in data.items():
            if key == 'totalMassKg':
                continue  # derived, ignored on input
            field = FIELDS[key]
            if field == 'drivetrain':
                if value not in DRIVETRAINS:
                    raise ValueError(f'drivetrain must be one of {", ".join(DRIVETRAINS)}')
            elif field == 'ftp_watts':
                if value is not None and (type(value) is not int):
                    raise ValueError('ftpWatts must be a whole number of watts or empty')
            elif field in WHOLE_NUMBERS:
                if type(value) is not int:
                    raise ValueError(f'{key} must be a whole number')
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f'{key} must be a number')
            changes[field] = float(value) if field in DECIMALS else value
        return replace(self, **changes).validate()

    def validate(self):
        for field, (low, high) in LIMITS.items():
            value = getattr(self, field)
            if value is None:
                continue
            if not low <= value <= high:
                raise ValueError(f'{field} must be between {low:g} and {high:g}')
        if self.drivetrain not in DRIVETRAINS:
            raise ValueError(f'drivetrain must be one of {", ".join(DRIVETRAINS)}')
        return self


class ProfileStore:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.lock = Lock()

    @classmethod
    def default(cls):
        from coach.app.paths import data_file
        return cls(data_file('profile.json', 'PROFILE_FILE'))

    def load(self):
        """(profile, saved?) — defaults when there is no usable file."""
        with self.lock:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
            except FileNotFoundError:
                return RiderProfile(), False
            except (OSError, ValueError) as exc:
                print(f'WARNING: ignoring unreadable profile {self.path}: {exc}', flush=True)
                return RiderProfile(), False
        try:
            return RiderProfile().updated(data.get('profile', {})), True
        except (ValueError, AttributeError) as exc:
            print(f'WARNING: ignoring invalid profile {self.path}: {exc}', flush=True)
            return RiderProfile(), False

    def update(self, changes: dict):
        profile, _ = self.load()
        new = profile.updated(changes)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + '.tmp')
            tmp.write_text(json.dumps({'version': 1, 'profile': new.to_json(),
                                       'updatedAtUtc': datetime.now(timezone.utc).isoformat(timespec='seconds')},
                                      indent=2), encoding='utf-8')
            os.replace(tmp, self.path)
        return new
