"""GPX routes: list them, accept uploads, load one to ride (coach/session/route.py).

Stored in ``routes`` in the data home (coach/app/paths.routes_dir), outside the repository: a GPX may be one of
the rider's own rides, with the places they go. Same rules as the replay recordings: a safe file name, the file is
parsed BEFORE it is stored, nothing is ever overwritten (a name already taken gets _1, _2…).
"""
import json
import re
import unicodedata
from pathlib import Path
from threading import Lock

from coach.session.route import Route, RouteError, parse_gpx

GENERATED_PREFIX = 'gen_'      # generated routes: told apart from the uploaded ones (not offered as races)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # recordings of a 24 h ride with heart rate, cadence… reach tens of MB
SAFE_NAME = re.compile(r'[^A-Za-z0-9._-]+')
TRASH = '.papelera'           # deleted routes and sessions go here, never removed: they can be put back by hand
NAMES_FILE = 'names.json'     # {file: name} chosen by the rider; the GPX files are never rewritten for a name
_names_lock = Lock()
_cache = {}          # (path, mtime, size) -> Route: parsing a big GPX on every listing would be slow
_cache_lock = Lock()


def safe_filename(name: str) -> str:
    base = SAFE_NAME.sub('_', Path(name or '').name).strip('._')
    if not base:
        raise ValueError('Invalid file name')
    if not base.lower().endswith('.gpx'):
        raise ValueError('Only .gpx routes are accepted')
    return base


def _names(folder: Path) -> dict:
    try:
        names = json.loads((Path(folder) / NAMES_FILE).read_text(encoding='utf-8'))
        return names if isinstance(names, dict) else {}
    except (OSError, ValueError):
        return {}


def rename(folder: Path, file: str, name) -> dict:
    """Give the route ``file`` the rider's own ``name`` (empty: back to the GPX's)."""
    from coach.session.route_generator import route_name
    route = load_route(folder, file)                   # FileNotFoundError for anything that is not a route
    name = route_name(name if name is not None else '')
    with _names_lock:
        names = _names(folder)
        if name and name != route.gpx_name:
            names[file] = name
        else:
            names.pop(file, None)
        tmp = Path(folder) / (NAMES_FILE + '.tmp')
        tmp.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(Path(folder) / NAMES_FILE)
    return {**load_route(folder, file).summary(), 'valid': True, 'error': None}


def to_trash(folder: Path, names) -> list:
    """Move files of ``folder`` into its TRASH folder, renaming if one with that name is already there."""
    trash = Path(folder) / TRASH
    trash.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in names:
        source = Path(folder) / name
        if not source.is_file():
            continue
        target, counter = trash / name, 1
        while target.exists():
            target = trash / f'{source.stem}_{counter}{source.suffix}'
            counter += 1
        source.replace(target)
        moved.append(target.name)
    return moved


def delete_route(folder: Path, file: str) -> dict:
    """Move a route to the trash and forget the name the rider gave it."""
    load_route(folder, file)                             # FileNotFoundError for anything that is not a route
    moved = to_trash(folder, [file])
    with _names_lock:
        names = _names(folder)
        if names.pop(file, None) is not None:
            (Path(folder) / NAMES_FILE).write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding='utf-8')
    with _cache_lock:
        for key in [k for k in _cache if Path(k[0]).name == file and Path(k[0]).parent == Path(folder)]:
            del _cache[key]
    return {'deleted': file, 'trash': str(Path(folder) / TRASH), 'moved': moved}


def slug(name: str) -> str:
    """A file name from a route name: no accents, only safe characters («Cuna de la Legión» → Cuna_de_la_Legion)."""
    plain = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return SAFE_NAME.sub('_', plain).strip('._')[:60] or 'ruta'


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
            return _named(_cache[key], folder)
    route = parse_gpx(path.read_bytes(), file)
    with _cache_lock:
        _cache[key] = route
    return _named(route, folder)


def _named(route: Route, folder: Path) -> Route:
    route.name = _names(folder).get(route.file) or route.gpx_name
    return route


def list_routes(folder: Path):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob('*.gpx'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            route = load_route(folder, path.name)
            out.append({**route.summary(), 'valid': True, 'error': None, 'thumb': route.profile(max_points=80),
                        'recorded': route.timed_points >= 2,   # a recorded ride: its own replay
                        'generated': path.name.startswith((GENERATED_PREFIX, 'generada_', 'como_')),   # + the first ones
                        'gpxName': route.gpx_name})
        except (RouteError, OSError) as exc:
            out.append({'file': path.name, 'name': path.stem, 'valid': False, 'error': str(exc)[:200]})
    return out


def generate(folder: Path, body: dict) -> dict:
    """A generated route (coach/session/route_generator.py): previewed, or saved as a GPX with ``save``.

    ``mode`` «custom» takes distanceKm, gainM, climbs, avgGrade, maxGrade, kicks, descentGrade; «like» takes the
    ``file`` of a race and distanceKm. ``seed`` repeats a route: the preview returns it, the save sends it back.
    """
    from coach.session.route_generator import generate_custom, generate_like
    if not isinstance(body, dict):
        raise ValueError('Expected an object')
    mode, seed, name = body.get('mode'), body.get('seed'), body.get('name')
    if mode == 'custom':
        route, data, seed = generate_custom(body, seed, name)
    elif mode == 'like':
        try:
            race = load_route(folder, body.get('file'))
        except FileNotFoundError:
            raise ValueError('file must be one of your routes')
        route, data, seed = generate_like(race, body.get('distanceKm'), seed, name)
    else:
        raise ValueError('mode must be custom or like')
    filename = f'{GENERATED_PREFIX}{slug(route.name)}.gpx'     # from the name (proposed or the rider's)
    out = {**route.summary(), 'seed': seed, 'profile': route.profile(600), 'saved': False}
    if body.get('save'):
        saved = save_upload(folder, filename, data)
        out.update(file=saved['file'], saved=True)
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
