"""GPX routes: list them, accept uploads, load one to ride (coach/session/route.py).

Stored in ``routes`` in the data home (coach/app/paths.routes_dir), outside the repository: a GPX may be one of
the rider's own rides, with the places they go. Same rules as the replay recordings: a safe file name, the file is
parsed BEFORE it is stored, nothing is ever overwritten (a name already taken gets _1, _2…).
"""
import re
from pathlib import Path
from threading import Lock

from coach.session.route import Route, RouteError, parse_gpx

MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # recordings of a 24 h ride with heart rate, cadence… reach tens of MB
SAFE_NAME = re.compile(r'[^A-Za-z0-9._-]+')
_cache = {}          # (path, mtime, size) -> Route: parsing a big GPX on every listing would be slow
_cache_lock = Lock()


def safe_filename(name: str) -> str:
    base = SAFE_NAME.sub('_', Path(name or '').name).strip('._')
    if not base:
        raise ValueError('Invalid file name')
    if not base.lower().endswith('.gpx'):
        raise ValueError('Only .gpx routes are accepted')
    return base


def load_route(folder: Path, file: str) -> Route:
    """The route ``file`` of ``folder`` (a bare file name; anything else is refused)."""
    if not file or Path(file).name != file or not file.lower().endswith('.gpx'):
        raise FileNotFoundError(file)
    path = Path(folder) / file
    if not path.is_file():
        raise FileNotFoundError(file)
    stat = path.stat()
    key = (str(path), stat.st_mtime, stat.st_size)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    route = parse_gpx(path.read_bytes(), file)
    with _cache_lock:
        _cache[key] = route
    return route


def list_routes(folder: Path):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob('*.gpx'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            out.append({**load_route(folder, path.name).summary(), 'valid': True, 'error': None})
        except (RouteError, OSError) as exc:
            out.append({'file': path.name, 'name': path.stem, 'valid': False, 'error': str(exc)[:200]})
    return out


def save_upload(folder: Path, name: str, data: bytes) -> dict:
    """Validate an uploaded GPX as a ridable route and store it without overwriting anything."""
    if not data:
        raise ValueError('Empty file')
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f'File larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB')
    filename = safe_filename(name)
    try:
        route = parse_gpx(data, filename)
    except RouteError as exc:
        raise ValueError(f'Not a usable GPX route: {exc}')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    stem, counter = target.stem, 1
    while target.exists():
        target = folder / f'{stem}_{counter}.gpx'
        counter += 1
    tmp = folder / (target.name + '.uploading')
    tmp.write_bytes(data)
    tmp.rename(target)
    route.file = target.name
    return {**route.summary(), 'valid': True, 'error': None}
