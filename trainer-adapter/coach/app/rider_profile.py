"""Rider profile: the per-user numbers that physics, safety limits and metrics depend on.

Stored in the ``profile`` table of the local database (coach/app/db.py, ``coach.db`` in the data home), with every
saved version in ``profile_versions`` (how FTP and weight change over time, for the AI). Until 16-11 it was
``profile.json``: coach/app/legacy_json.py imports it once. Editing it never restarts the Bluetooth workers. Values outside realistic ranges are
rejected rather than clamped, so a typo (800 kg) is reported instead of silently used.
"""
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

DRIVETRAINS = ('ZWIFT_COG', 'CASSETTE')
BIKE_TYPES = ('ROAD', 'MTB')   # physics of the virtual road and rolling resistance sent to the trainer (virtual_ride.BIKE_PHYSICS)
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
    # Heart rate (training load without power, coach/history/load.py): all optional, estimated when missing
    'resting_heart_rate': (30, 100),
    'max_heart_rate': (120, 230),
    'threshold_heart_rate': (100, 220),
}
OPTIONAL_WHOLE = ('ftp_watts', 'resting_heart_rate', 'max_heart_rate', 'threshold_heart_rate')
FIELDS = {'riderWeightKg': 'rider_weight_kg', 'bikeWeightKg': 'bike_weight_kg', 'ftpWatts': 'ftp_watts',
          'drivetrain': 'drivetrain', 'gradeDifficultyPercent': 'grade_difficulty_percent',
          'gradeDescentFactorPercent': 'grade_descent_factor_percent', 'maxGradePercent': 'max_grade_percent',
          'minGradePercent': 'min_grade_percent', 'gradeTransitionMetersPerPercent': 'grade_transition_m_per_percent',
          'bikeType': 'bike_type', 'restingHeartRate': 'resting_heart_rate', 'maxHeartRate': 'max_heart_rate',
          'thresholdHeartRate': 'threshold_heart_rate'}
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
    bike_type: str = 'ROAD'
    resting_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    threshold_heart_rate: Optional[int] = None

    @property
    def total_mass_kg(self) -> float:
        return round(self.rider_weight_kg + self.bike_weight_kg, 2)

    def to_json(self):
        return {'riderWeightKg': self.rider_weight_kg, 'bikeWeightKg': self.bike_weight_kg,
                'ftpWatts': self.ftp_watts, 'drivetrain': self.drivetrain, 'totalMassKg': self.total_mass_kg,
                'gradeDifficultyPercent': self.grade_difficulty_percent,
                'gradeDescentFactorPercent': self.grade_descent_factor_percent,
                'maxGradePercent': self.max_grade_percent, 'minGradePercent': self.min_grade_percent,
                'gradeTransitionMetersPerPercent': self.grade_transition_m_per_percent, 'bikeType': self.bike_type,
                'restingHeartRate': self.resting_heart_rate, 'maxHeartRate': self.max_heart_rate,
                'thresholdHeartRate': self.threshold_heart_rate}

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
            elif field == 'bike_type':
                if value not in BIKE_TYPES:
                    raise ValueError(f'bikeType must be one of {", ".join(BIKE_TYPES)}')
            elif field in OPTIONAL_WHOLE:
                if value is not None and (type(value) is not int):
                    raise ValueError(f'{key} must be a whole number or empty')
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
        if self.bike_type not in BIKE_TYPES:
            raise ValueError(f'bikeType must be one of {", ".join(BIKE_TYPES)}')
        return self


# RiderProfile field → column of the profile table (ADR-003)
COLUMNS = {'rider_weight_kg': 'rider_weight_kg', 'bike_weight_kg': 'bike_weight_kg', 'ftp_watts': 'ftp_w',
           'drivetrain': 'drivetrain', 'grade_difficulty_percent': 'grade_difficulty_pct',
           'grade_descent_factor_percent': 'grade_descent_factor_pct', 'max_grade_percent': 'max_grade_pct',
           'min_grade_percent': 'min_grade_pct', 'grade_transition_m_per_percent': 'grade_transition_m_per_pct',
           'bike_type': 'bike_type', 'resting_heart_rate': 'resting_hr', 'max_heart_rate': 'max_hr',
           'threshold_heart_rate': 'threshold_hr'}
JSON_KEY = {field: key for key, field in FIELDS.items()}


class ProfileStore:
    """The rider profile in the local database (one row), and its history of versions."""

    def __init__(self, path):
        from coach.app import db
        self.path = db.migrate(path)
        self.lock = Lock()

    @classmethod
    def default(cls):
        from coach.app import db
        return cls(db.open_default())

    def _db(self):
        from coach.app import db
        return db.opened(self.path)

    def load(self):
        """(profile, saved?) — defaults when nothing was saved or the saved row is not valid."""
        with self.lock, self._db() as conn:
            row = conn.execute(f"SELECT {', '.join(COLUMNS.values())} FROM profile WHERE id = 1").fetchone()
        if row is None:
            return RiderProfile(), False
        data = {}
        for (field, _column), value in zip(COLUMNS.items(), row):
            if value is None and field not in OPTIONAL_WHOLE:
                continue                                   # a column added later: the default
            if value is not None and field in OPTIONAL_WHOLE + WHOLE_NUMBERS:
                value = int(value)                         # SQLite may hand back 50.0
            data[JSON_KEY[field]] = value
        try:
            return RiderProfile().updated(data), True
        except (ValueError, AttributeError) as exc:
            print(f'WARNING: ignoring invalid profile in {self.path}: {exc}', flush=True)
            return RiderProfile(), False

    def update(self, changes: dict, ftp_source: str = None):
        """Save the changed profile. When the FTP changes, where it came from: 'test' (the ramp test), 'estimate'
        (the FTP notice) or, by default, 'manual' (typed in the profile)."""
        profile, _ = self.load()
        new = profile.updated(changes)
        source = None
        if new.ftp_watts != profile.ftp_watts:
            source = ftp_source or ('manual' if new.ftp_watts is not None else None)
        self._write(new, datetime.now(timezone.utc).isoformat(timespec='seconds'), source, keep_source=source is None)
        return new

    def ftp_source(self):
        with self.lock, self._db() as conn:
            row = conn.execute('SELECT ftp_source FROM profile WHERE id = 1').fetchone()
        return row[0] if row else None

    def import_saved(self, data: dict, saved_utc: str = None) -> RiderProfile:
        """A profile saved by an earlier version (profile.json), as if it had been saved at ``saved_utc``."""
        new = RiderProfile().updated(data)
        self._write(new, saved_utc or datetime.now(timezone.utc).isoformat(timespec='seconds'))
        return new

    def versions(self):
        """Every saved profile, oldest first: [(valid_from_utc, profile json)]."""
        with self.lock, self._db() as conn:
            rows = conn.execute('SELECT valid_from_utc, data FROM profile_versions ORDER BY valid_from_utc, rowid').fetchall()
        return [(at, json.loads(data)) for at, data in rows]

    def _write(self, profile: RiderProfile, at: str, ftp_source: str = None, keep_source: bool = False):
        from coach.app import db
        values = [getattr(profile, field) for field in COLUMNS]
        columns = ', '.join(COLUMNS.values())
        with self.lock, self._db() as conn:
            if keep_source:
                row = conn.execute('SELECT ftp_source FROM profile WHERE id = 1').fetchone()
                ftp_source = row[0] if row else None
            conn.execute(f"INSERT OR REPLACE INTO profile (id, {columns}, ftp_source, updated_utc) VALUES "
                         f"(1, {', '.join('?' for _ in values)}, ?, ?)", values + [ftp_source, at])
            conn.execute('INSERT INTO profile_versions (id, valid_from_utc, data) VALUES (?, ?, ?)',
                         (db.new_id(), at, json.dumps({**profile.to_json(), 'ftpSource': ftp_source}, ensure_ascii=False)))
