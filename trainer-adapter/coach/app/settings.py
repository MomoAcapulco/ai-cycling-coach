"""User settings that can change while the adapter runs (admin page).

``.env`` gives the defaults. Saving from the admin page writes the ``settings`` table of the local database
(coach/app/db.py), which then wins over ``.env`` until it is reset (until 16-11 it was ``settings.json``:
coach/app/legacy_json.py imports it once). Ports, device IDs,
name hints and the experimental physical control stay in ``.env`` only: none of them should be one
click away.
"""
import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Optional

from coach.app.paths import PROJECT_ROOT

MODES = ('SIMULATOR', 'WAHOO', 'REPLAY')
MIN_RECORD_SECONDS, MAX_RECORD_SECONDS = 60, 4 * 3600


def _flag(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes')


@dataclass(frozen=True)
class Settings:
    mode: str = 'SIMULATOR'
    replay_file: Optional[str] = None
    hr_enabled: bool = False
    zwift_enabled: bool = False
    record_enabled: bool = False
    record_seconds: int = 600
    # Native virtual shifting on the trainer (Zwift Cog): only with TRAINER_MODE=WAHOO. Off unless chosen.
    gear_control_enabled: bool = False

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(mode=(env.get('TRAINER_MODE') or 'WAHOO').strip().upper(),   # the simulator is for development
                   replay_file=(env.get('REPLAY_FILE') or '').strip() or None,
                   hr_enabled=_flag(env.get('HR_ENABLED')),
                   zwift_enabled=_flag(env.get('ZWIFT_ENABLED')),
                   record_enabled=_flag(env.get('RECORD_ENABLED'), default=True),
                   record_seconds=int(env.get('RECORD_SECONDS') or 600),
                   gear_control_enabled=_flag(env.get('GEAR_CONTROL_ENABLED')))

    def to_json(self):
        return {'mode': self.mode, 'replayFile': self.replay_file, 'hrEnabled': self.hr_enabled,
                'zwiftEnabled': self.zwift_enabled, 'recordEnabled': self.record_enabled,
                'recordSeconds': self.record_seconds, 'gearControlEnabled': self.gear_control_enabled}

    def updated(self, data: dict) -> 'Settings':
        """A copy with the given camelCase fields changed; unknown fields and wrong types are errors."""
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
        names = {'mode': 'mode', 'replayFile': 'replay_file', 'hrEnabled': 'hr_enabled',
                 'zwiftEnabled': 'zwift_enabled', 'recordEnabled': 'record_enabled',
                 'recordSeconds': 'record_seconds', 'gearControlEnabled': 'gear_control_enabled'}
        unknown = set(data) - set(names)
        if unknown:
            raise ValueError(f'Unknown settings: {", ".join(sorted(unknown))}')
        changes = {}
        for key, value in data.items():
            field = names[key]
            if field in ('hr_enabled', 'zwift_enabled', 'record_enabled', 'gear_control_enabled') and type(value) is not bool:
                raise ValueError(f'{key} must be true or false')
            if field == 'record_seconds' and type(value) is not int:
                raise ValueError('recordSeconds must be an integer')
            if field == 'mode' and not isinstance(value, str):
                raise ValueError('mode must be a string')
            if field == 'replay_file' and value is not None and not isinstance(value, str):
                raise ValueError('replayFile must be a string or null')
            changes[field] = value.strip().upper() if field == 'mode' else value
        return replace(self, **changes)

    def replay_path(self, recordings_dir: Optional[Path] = None) -> Optional[Path]:
        """An absolute path as given. A relative one is looked up in the recordings folder, then from the
        project root, then by file name in the recordings folder (so an old .env value such as
        trainer-adapter/recordings/ride.csv still works after the recordings moved)."""
        if not self.replay_file:
            return None
        path = Path(self.replay_file).expanduser()
        if path.is_absolute():
            return path
        candidates = []
        if recordings_dir is not None:
            candidates.append(Path(recordings_dir) / path)
        candidates.append(PROJECT_ROOT / path)
        if recordings_dir is not None:
            candidates.append(Path(recordings_dir) / path.name)
        return next((c for c in candidates if c.is_file()), candidates[0])

    def validate(self, control_test=False, recordings_dir: Optional[Path] = None):
        if self.mode not in MODES:
            raise ValueError(f'mode must be one of {", ".join(MODES)}')
        if not MIN_RECORD_SECONDS <= self.record_seconds <= MAX_RECORD_SECONDS:
            raise ValueError(f'recordSeconds must be between {MIN_RECORD_SECONDS} and {MAX_RECORD_SECONDS}')
        if self.mode == 'REPLAY':
            path = self.replay_path(recordings_dir)
            if path is None:
                raise ValueError('REPLAY needs a recording (replayFile)')
            if not path.is_file():
                raise ValueError(f'Recording not found: {self.replay_file}')
        if control_test and (self.mode != 'WAHOO' or not self.record_enabled or self.record_seconds != 600):
            raise PermissionError('CONTROL_TEST_ENABLED (in .env) requires WAHOO, recording on and 600 s')
        if control_test and self.gear_control_enabled:
            raise PermissionError('CONTROL_TEST_ENABLED (in .env) and gear control cannot be on together')
        return self


class SettingsStore:
    """The saved settings in the local database: one row per setting, its value as JSON."""

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

    def saved(self) -> dict:
        with self.lock, self._db() as conn:
            rows = conn.execute('SELECT key, value FROM settings').fetchall()
        out = {}
        for key, value in rows:
            try:
                out[key] = json.loads(value)
            except (TypeError, ValueError):
                print(f'WARNING: ignoring unreadable setting {key} in {self.path}', flush=True)
        return out

    def load(self, defaults: Settings):
        """(settings, source): the saved settings over the .env defaults, or the defaults alone."""
        data = self.saved()
        if not data:
            return defaults, 'env'
        try:
            return defaults.updated(data), 'saved'
        except (ValueError, AttributeError) as exc:
            print(f'WARNING: ignoring invalid settings in {self.path}: {exc}', flush=True)
            return defaults, 'env'

    def save(self, settings: Settings):
        self.save_raw(settings.to_json())

    def save_raw(self, values: dict):
        with self.lock, self._db() as conn:
            conn.execute('DELETE FROM settings')
            conn.executemany('INSERT INTO settings (key, value) VALUES (?, ?)',
                             [(k, json.dumps(v)) for k, v in values.items()])

    def reset(self):
        with self.lock, self._db() as conn:
            conn.execute('DELETE FROM settings')
