"""Recordings available for REPLAY: list them and accept uploaded CSV files from the admin page."""
import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from coach.session.recording import CsvReplay

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SAFE_NAME = re.compile(r'[^A-Za-z0-9._-]+')


def describe(path: Path) -> dict:
    # Recordings are listed from and saved to the recordings folder: the name is enough to select one.
    info = {'name': path.name, 'path': path.name, 'sizeBytes': path.stat().st_size,
            'modifiedUtc': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec='seconds'),
            'valid': False, 'samples': None, 'durationSeconds': None, 'error': None}
    try:
        replay = CsvReplay(path)
        info.update(valid=True, samples=len(replay.rows), durationSeconds=replay.duration)
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        info['error'] = str(exc)[:200]
    return info


def list_recordings(folder: Path):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = sorted(folder.glob('*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
    return [describe(p) for p in files]


def safe_filename(name: str) -> str:
    base = SAFE_NAME.sub('_', Path(name or '').name).strip('._')
    if not base:
        raise ValueError('Invalid file name')
    if not base.lower().endswith('.csv'):
        raise ValueError('Only .csv recordings are accepted')
    return base


def save_upload(folder: Path, name: str, data: bytes) -> dict:
    """Validate an uploaded CSV as a replayable recording and store it without overwriting anything."""
    if not data:
        raise ValueError('Empty file')
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f'File larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB')
    filename = safe_filename(name)
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('The file is not UTF-8 text')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    stem, counter = target.stem, 1
    while target.exists():
        target = folder / f'{stem}_{counter}.csv'
        counter += 1
    tmp = folder / (target.name + '.uploading')
    try:
        tmp.write_text(text, encoding='utf-8', newline='')
        CsvReplay(tmp)  # raises ValueError for empty, incompatible or unordered recordings
    except (ValueError, KeyError, csv.Error) as exc:
        tmp.unlink(missing_ok=True)
        raise ValueError(f'Not a replayable recording: {exc}')
    tmp.rename(target)
    return describe(target)
