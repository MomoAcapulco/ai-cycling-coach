"""The JSON files of earlier versions, imported once into the local database (ADR-003, phase 2).

Each file is read, written to its table and then MOVED (never deleted) to ``backup-json-<date>/`` in the data home,
so no stale copy is left next to the database and the original can still be opened by hand. ``meta`` remembers
what was imported (``json_imported_<name>``): it never runs twice. An unreadable file is moved too and noted.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

from coach.app import db


class _Backup:
    """The backup folder, created only when there is something to move."""

    def __init__(self, home: Path):
        self.home, self.folder = home, None

    def move(self, path: Path) -> Path:
        if self.folder is None:
            self.folder = self.home / f'backup-json-{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        target = self.folder / path.relative_to(self.home) if path.is_relative_to(self.home) else self.folder / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        return target


def _done(db_path, name: str) -> bool:
    return db.meta(db_path, f'json_imported_{name}') is not None


def _note(db_path, name: str, text: str):
    with db.opened(db_path) as conn:
        conn.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', (f'json_imported_{name}', f'{db.now_utc()} · {text}'))


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8')), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def import_profile(path: Path, db_path, backup: _Backup) -> str:
    from coach.app.rider_profile import ProfileStore
    if not path.is_file():
        return 'no profile.json'
    data, error = _read(path)
    try:
        if error:
            raise ValueError(error)
        ProfileStore(db_path).import_saved(data.get('profile', {}), data.get('updatedAtUtc'))
        result = 'imported'
    except (ValueError, AttributeError) as exc:
        result = f'not valid, not imported ({exc})'
        print(f'WARNING: profile.json {result}', flush=True)
    return f'{result}; original in {backup.move(path)}'


def import_settings(path: Path, db_path, backup: _Backup) -> str:
    from coach.app.settings import SettingsStore
    if not path.is_file():
        return 'no settings.json'
    data, error = _read(path)
    if error or not isinstance((data or {}).get('settings'), dict):
        result = f'not valid, not imported ({error or "no settings"})'
        print(f'WARNING: settings.json {result}', flush=True)
    else:
        SettingsStore(db_path).save_raw(data['settings'])      # validated when loaded, like before
        result = 'imported'
    return f'{result}; original in {backup.move(path)}'


def import_route_names(path: Path, db_path, backup: _Backup) -> str:
    """routes/names.json ({gpx file: name}): each name goes to the catalogue row of its GPX."""
    from coach.app.routes_store import rename
    from coach.session.route import RouteError
    if not path.is_file():
        return 'no names.json'
    data, error = _read(path)
    if error or not isinstance(data, dict):
        result = f'not valid, not imported ({error or "not an object"})'
    else:
        named, missing = 0, []
        for file, name in data.items():
            try:
                rename(path.parent, file, name, db_path)
                named += 1
            except (FileNotFoundError, RouteError, ValueError):
                missing.append(file)                   # the GPX is gone: nothing to name
        result = f'imported {named} names' + (f', {len(missing)} without their GPX' if missing else '')
    return f'{result}; original in {backup.move(path)}'


def import_all(home: Path, db_path) -> dict:
    """Import what has not been imported yet. Returns {name: what happened} for the files handled now."""
    from coach.app.paths import data_file, routes_dir
    home = Path(home)
    backup = _Backup(home)
    done = {}
    for name, path, step in (
            ('profile', data_file('profile.json', 'PROFILE_FILE'), import_profile),
            ('settings', data_file('settings.json', 'SETTINGS_FILE'), import_settings),
            ('route_names', routes_dir() / 'names.json', import_route_names)):
        if _done(db_path, name):
            continue
        done[name] = step(Path(path), db_path, backup)
        _note(db_path, name, done[name])
    if any('imported' in text for text in done.values()):
        print(f'Imported into {db_path}: ' + '; '.join(f'{k} {v}' for k, v in done.items()), flush=True)
    return done
