"""GPX routes: list them, accept uploads, load one to ride (coach/session/route.py).

Stored in ``routes`` in the data home (coach/app/paths.routes_dir), outside the repository: a GPX may be one of
the rider's own rides, with the places they go. Same rules as the replay recordings: a safe file name, the file is
parsed BEFORE it is stored, nothing is ever overwritten (a name already taken gets _1, _2…).

The GPX files stay files (their geometry, openable with any program); the catalogue is the ``routes`` table of the
local database (coach/app/db.py): the name the rider gave, generated or uploaded, the generator's settings, distance
and climbing, and when a route was deleted. A row belongs to the GPX whose fingerprint (``sha256``) it has, so a new
GPX uploaded with the name of a deleted one starts clean. Until 16-11 the names were in ``routes/names.json``
(coach/app/legacy_json.py imports it once).
"""
import hashlib
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
NAMES_FILE = 'names.json'     # until 16-11: {file: name} chosen by the rider (now the routes table)
_db_lock = Lock()
_cache = {}          # (path, mtime, size) -> (Route, sha256): parsing a big GPX on every listing would be slow
_cache_lock = Lock()


def safe_filename(name: str) -> str:
    base = SAFE_NAME.sub('_', Path(name or '').name).strip('._')
    if not base:
        raise ValueError('Invalid file name')
    if not base.lower().endswith('.gpx'):
        raise ValueError('Only .gpx routes are accepted')
    return base


def _database(db_path=None):
    from coach.app import db
    return db.migrate(db_path) if db_path else db.open_default()


def _current(conn, file: str, sha: str):
    """The catalogue row of this very GPX (same file name AND same content), or None."""
    return conn.execute('SELECT id, name FROM routes WHERE file = ? AND sha256 = ? AND deleted_utc IS NULL '
                        'ORDER BY created_utc DESC LIMIT 1', (file, sha)).fetchone()


def _register(conn, route: Route, sha: str, generator: dict = None) -> str:
    """Add this GPX to the catalogue (if it is not there yet) and return its id."""
    from coach.app import db
    row = _current(conn, route.file, sha)
    if row:
        return row[0]
    route_id = db.new_id()
    conn.execute('INSERT INTO routes (id, file, sha256, gpx_name, generated, generator, recorded, distance_m, gain_m, '
                 'loss_m, created_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                 (route_id, route.file, sha, route.gpx_name, int(_is_generated(route.file)),
                  json.dumps(generator, ensure_ascii=False) if generator else None, int(route.timed_points >= 2),
                  route.distance_m, route.gain_m, route.loss_m, db.now_utc()))
    return route_id


def _is_generated(file: str) -> bool:
    return file.startswith((GENERATED_PREFIX, 'generada_', 'como_'))   # + the first generated ones


def rename(folder: Path, file: str, name, db_path=None) -> dict:
    """Give the route ``file`` the rider's own ``name`` (empty: back to the GPX's)."""
    from coach.app import db
    from coach.session.route_generator import route_name
    route, sha = _parsed(folder, file)                 # FileNotFoundError for anything that is not a route
    name = route_name(name if name is not None else '')
    with _db_lock, db.opened(_database(db_path)) as conn:
        route_id = _register(conn, route, sha)
        conn.execute('UPDATE routes SET name = ? WHERE id = ?',
                     (name if name and name != route.gpx_name else None, route_id))
    return {**load_route(folder, file, db_path).summary(), 'valid': True, 'error': None}


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


def delete_route(folder: Path, file: str, db_path=None) -> dict:
    """Move a route to the trash; its catalogue row stays, marked deleted (sessions ridden on it still name it)."""
    from coach.app import db
    route, sha = _parsed(folder, file)                 # FileNotFoundError for anything that is not a route
    with _db_lock, db.opened(_database(db_path)) as conn:
        route_id = _register(conn, route, sha)
        conn.execute('UPDATE routes SET deleted_utc = ? WHERE id = ?', (db.now_utc(), route_id))
    moved = to_trash(folder, [file])
    with _cache_lock:
        for key in [k for k in _cache if Path(k[0]).name == file and Path(k[0]).parent == Path(folder)]:
            del _cache[key]
    return {'deleted': file, 'trash': str(Path(folder) / TRASH), 'moved': moved}


def slug(name: str) -> str:
    """A file name from a route name: no accents, only safe characters («Cuna de la Legión» → Cuna_de_la_Legion)."""
    plain = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return SAFE_NAME.sub('_', plain).strip('._')[:60] or 'ruta'


def _parsed(folder: Path, file: str):
    """(route, sha256) of ``file`` in ``folder`` (a bare file name; anything else is refused), cached."""
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
    data = path.read_bytes()
    parsed = (parse_gpx(data, file), hashlib.sha256(data).hexdigest())
    with _cache_lock:
        _cache[key] = parsed
    return parsed


def load_route(folder: Path, file: str, db_path=None) -> Route:
    """The route ``file`` of ``folder``, with the name the rider gave it."""
    from coach.app import db
    route, sha = _parsed(folder, file)
    with db.opened(_database(db_path)) as conn:
        row = _current(conn, route.file, sha)
    route.name = (row[1] if row else None) or route.gpx_name
    return route


def list_routes(folder: Path, db_path=None):
    """Every GPX of ``folder``, newest first; each valid one is also put in the catalogue (once)."""
    from coach.app import db
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob('*.gpx'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            route, sha = _parsed(folder, path.name)
            with _db_lock, db.opened(_database(db_path)) as conn:
                _register(conn, route, sha)
            route = load_route(folder, path.name, db_path)
            out.append({**route.summary(), 'valid': True, 'error': None, 'thumb': route.profile(max_points=80),
                        'recorded': route.timed_points >= 2,   # a recorded ride: its own replay
                        'generated': _is_generated(path.name),
                        'gpxName': route.gpx_name})
        except (RouteError, OSError) as exc:
            out.append({'file': path.name, 'name': path.stem, 'valid': False, 'error': str(exc)[:200]})
    return out


def generate(folder: Path, body: dict, db_path=None) -> dict:
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
            race = load_route(folder, body.get('file'), db_path)
        except FileNotFoundError:
            raise ValueError('file must be one of your routes')
        route, data, seed = generate_like(race, body.get('distanceKm'), seed, name)
    else:
        raise ValueError('mode must be custom or like')
    filename = f'{GENERATED_PREFIX}{slug(route.name)}.gpx'     # from the name (proposed or the rider's)
    out = {**route.summary(), 'seed': seed, 'profile': route.profile(600), 'saved': False}
    if body.get('save'):
        generator = {k: body.get(k) for k in ('mode', 'file', 'distanceKm', 'gainM', 'climbs', 'avgGrade', 'maxGrade',
                                              'kicks', 'descentGrade') if body.get(k) is not None}
        saved = save_upload(folder, filename, data, db_path, {**generator, 'seed': seed})
        out.update(file=saved['file'], saved=True)
    return out


def save_upload(folder: Path, name: str, data: bytes, db_path=None, generator: dict = None) -> dict:
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
    from coach.app import db
    with _db_lock, db.opened(_database(db_path)) as conn:
        _register(conn, route, hashlib.sha256(data).hexdigest(), generator)
    return {**route.summary(), 'valid': True, 'error': None}
