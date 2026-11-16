"""Generated routes: a GPX made from what you ask for, ridden like any other route (coach/session/route.py).

Two ways:
- **custom** (``generate_custom``): distance, elevation gain, number of climbs, their average and maximum grade, short
  kicks («repechos») and the descent grade. Each climb is a run of ~300 m pieces whose grade wanders around the
  average (a random walk, so it changes gradually like a real road) with one piece at the maximum grade (the hard
  ramp), never in the first piece. After each climb comes its descent; between features, rolling flats (±0.8 %, about 2–3 m per km).
  The total gain is matched to what you asked for AS THE ROUTE PAGE MEASURES IT (the same 50 m smoothing): the
  climbs are rescaled until the parsed route says the right number (a few passes, within ~1 %).
- **like a race** (``generate_like``): from one of your GPX, a shorter route with the same character: its REAL climbs
  (their own grade, 5 m by 5 m) in race order, each with the descent that followed it, chosen so that the gain per km
  stays as in the race (the hardest climb always goes in), with rolling flats to fill the distance.

Same ``seed``, same route: the page previews with a seed and saves with that seed. The track is a synthetic line
(a smooth random walk around 0° N 0° E, far from any real road) every 10 m: only distance and elevation matter on
the trainer. Nothing here talks to the trainer.
"""
import math
import random
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

from coach.session.route import EARTH_RADIUS_M, STEP_M, Route, parse_gpx

Segment = Tuple[float, float]          # (length m, grade %)
POINT_M = 10.0
PIECE_M = 300.0
FLAT_PIECE_M = 400.0
FLAT_AMPLITUDE = 0.8                   # % — a «flat» of 60 km with ±1.5 % climbed 280 m: too much
START_ELEVATION_M = 300.0
LIMITS = {'distanceKm': (5, 200), 'gainM': (0, 5000), 'climbs': (0, 20), 'avgGrade': (2, 15), 'maxGrade': (2, 25),
          'kicks': (0, 30), 'descentGrade': (2, 15)}
MIN_CLIMB_GAIN_M = 30.0                # a race climb: at least 30 m up …
CLIMB_DIP_M = 15.0                     # … and it ends when the road drops more than this from its top


class GenerationError(ValueError):
    """What was asked cannot be built (message for the rider)."""


# ---- custom ------------------------------------------------------------------------------------------------------
def check(params: dict) -> dict:
    out = {}
    for key, (low, high) in LIMITS.items():
        value = params.get(key)
        if value is None and key in ('kicks', 'descentGrade'):
            value = 0 if key == 'kicks' else 6
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(f'{key} must be a number between {low} and {high}')
        out[key] = float(value)
    if out['maxGrade'] < out['avgGrade']:
        raise ValueError('maxGrade must be at least avgGrade')
    for key in ('climbs', 'kicks'):
        if out[key] != int(out[key]):
            raise ValueError(f'{key} must be a whole number')
    if out['gainM'] > 0 and out['climbs'] == 0 and out['kicks'] == 0:
        raise GenerationError('Para tener desnivel hace falta al menos una subida o un repecho.')
    return out


def _walk(rng: random.Random, n: int, spread: float) -> List[float]:
    """n values around 0 that change gradually (a smoothed random walk), within about ±spread."""
    value, out = rng.uniform(-spread, spread) / 2, []
    for _ in range(n):
        value = max(-spread, min(spread, value + rng.gauss(0, spread / 2.5)))
        out.append(value)
    return out


def _climb(rng: random.Random, gain: float, avg: float, top: float) -> List[Segment]:
    length = gain / (avg / 100)
    n = max(2, round(length / PIECE_M))
    grades = [min(top, max(1.5, avg * (1 + w))) for w in _walk(rng, n, 0.35)]
    if n >= 3 and top > avg:
        grades[rng.randrange(1, n)] = top                       # the hard ramp, never at the very start
    piece = gain * 100 / sum(grades)                            # equal pieces that climb exactly ``gain``
    return [(piece, g) for g in grades]


def _descent(rng: random.Random, drop: float, grade: float) -> List[Segment]:
    if drop <= 0:
        return []
    length = drop / (grade / 100)
    n = max(1, round(length / PIECE_M))
    grades = [-min(2.2 * grade, max(1.0, grade * (1 + w))) for w in _walk(rng, n, 0.3)]
    piece = drop * 100 / -sum(grades)
    return [(piece, g) for g in grades]


def _flat(rng: random.Random, length: float) -> List[Segment]:
    """Rolling flat with no net climb: small ups and downs that cancel out."""
    if length <= 0:
        return []
    n = max(1, round(length / FLAT_PIECE_M))
    grades = _walk(rng, n, FLAT_AMPLITUDE)
    mean = sum(grades) / n
    return [(length / n, g - mean) for g in grades]


def _length(segments: List[Segment]) -> float:
    return sum(length for length, _ in segments)


def _custom_segments(p: dict, seed: int, climb_scale: float) -> List[Segment]:
    rng = random.Random(seed)
    distance, gain = p['distanceKm'] * 1000, p['gainM'] * climb_scale
    kicks = []
    for _ in range(int(p['kicks'])):
        length = rng.uniform(150, 400)
        grade = min(p['maxGrade'], rng.uniform(max(6.0, p['avgGrade']), max(6.0, p['avgGrade']) + 6))
        kicks.append((length, grade))
    kick_gain = sum(length * g / 100 for length, g in kicks)
    if p['climbs'] == 0 and kicks:
        kicks = [(length * gain / kick_gain, g) for length, g in kicks]       # only kicks: they make all the gain
        kick_gain = gain
    elif kick_gain > 0.35 * gain:                                           # kicks are spice, not the climbs
        kicks = [(length * 0.35 * gain / kick_gain, g) for length, g in kicks]
        kick_gain = 0.35 * gain
    climbs_gain = max(0.0, gain - kick_gain)
    weights = [rng.uniform(0.5, 1.5) for _ in range(int(p['climbs']))]
    features: List[List[Segment]] = []
    for w in weights:
        g = climbs_gain * w / sum(weights)
        features.append(_climb(rng, g, p['avgGrade'], p['maxGrade']) + _descent(rng, g, p['descentGrade']))
    kick_features = [[(length, g)] + _descent(rng, length * g / 100, rng.uniform(3, 6)) for length, g in kicks]
    for kick in kick_features:                                               # kicks anywhere between the climbs
        features.insert(rng.randrange(len(features) + 1), kick)
    used = sum(_length(f) for f in features)
    rest = distance - used
    if rest < 0.05 * distance:
        raise GenerationError(
            f'No cabe: {p["gainM"]:.0f} m de desnivel al {p["avgGrade"]:.0f} % de media, con sus bajadas al '
            f'{p["descentGrade"]:.0f} %, necesitan unos {used / 1000 * 1.05:.0f} km. Sube la distancia o las pendientes.')
    gaps = [rng.uniform(0.5, 1.5) for _ in range(len(features) + 1)]
    segments: List[Segment] = []
    for i, gap in enumerate(gaps):
        segments += _flat(rng, rest * gap / sum(gaps))
        if i < len(features):
            segments += features[i]
    return segments


def generate_custom(params: dict, seed: Optional[int] = None, name: Optional[str] = None) -> Tuple[Route, bytes, int]:
    """(parsed route, GPX bytes, seed) for the custom parameters. ``name``: the rider's, else one is proposed."""
    p = check(params)
    seed = _seed(seed)
    name = route_name(name) or f'{p["distanceKm"]:.0f} km · {p["gainM"]:.0f} m+ · {int(p["climbs"])} subidas'
    scale, route, data = 1.0, None, b''
    for _ in range(4):                       # match the gain as the route page measures it (50 m smoothing)
        segments = _custom_segments(p, seed, scale)
        data = to_gpx(segments, name, seed)
        route = parse_gpx(data, 'generated.gpx')
        if p['gainM'] == 0 or route.gain_m == 0 or abs(route.gain_m - p['gainM']) <= 0.01 * p['gainM']:
            break
        scale *= p['gainM'] / route.gain_m
    return route, data, seed


# ---- like a race -------------------------------------------------------------------------------------------------
def find_climbs(route: Route) -> List[Tuple[int, int]]:
    """(start, top) indexes of the route profile (STEP_M apart) for every climb of at least MIN_CLIMB_GAIN_M."""
    e = route.elevations
    climbs, low_i, high_i = [], 0, None
    for i in range(1, len(e)):
        if high_i is None:
            if e[i] < e[low_i]:
                low_i = i
            elif e[i] - e[low_i] >= MIN_CLIMB_GAIN_M:
                high_i = i
        elif e[i] > e[high_i]:
            high_i = i
        elif e[high_i] - e[i] > CLIMB_DIP_M:
            climbs.append((low_i, high_i))
            low_i, high_i = i, None
    if high_i is not None:
        climbs.append((low_i, high_i))
    return climbs


def generate_like(race: Route, distance_km: float, seed: Optional[int] = None,
                  name: Optional[str] = None) -> Tuple[Route, bytes, int]:
    if not isinstance(distance_km, (int, float)) or isinstance(distance_km, bool) or not 5 <= distance_km <= 200:
        raise ValueError('distanceKm must be a number between 5 and 200')
    seed = _seed(seed)
    rng = random.Random(seed)
    distance = distance_km * 1000
    if distance >= race.distance_m:
        raise GenerationError(f'La carrera mide {race.distance_m / 1000:.0f} km: pide una distancia menor (para '
                              'rodarla entera, usa la ruta tal cual).')
    climbs = find_climbs(race)
    if not climbs:
        raise GenerationError('La carrera no tiene subidas de más de 30 m: no hay carácter que imitar.')
    e, grades = race.elevations, race.grades

    def piece(start: int, end: int) -> List[Segment]:
        return [(STEP_M, g) for g in grades[start:end]]

    features = []                                              # (order, gain, climb + its descent)
    for k, (start, top) in enumerate(climbs):
        end = climbs[k + 1][0] if k + 1 < len(climbs) else len(e) - 1
        bottom = min(range(top, end + 1), key=lambda i: e[i])  # the descent that followed: down to the lowest point
        features.append((k, e[top] - e[start], piece(start, top) + piece(top, bottom)))
    target_gain = race.gain_m * distance / race.distance_m
    hardest = max(features, key=lambda f: f[1])
    if _length(hardest[2]) > 0.95 * distance:
        raise GenerationError(f'La subida más dura de la carrera, con su bajada, mide {_length(hardest[2]) / 1000:.1f} km: '
                              f'pide al menos {_length(hardest[2]) / 1000 / 0.9:.0f} km.')
    chosen, gain, used = [hardest], hardest[1], _length(hardest[2])
    for f in sorted((f for f in features if f is not hardest), key=lambda f: -f[1]):
        if gain + f[1] <= target_gain * 1.05 and used + _length(f[2]) <= 0.9 * distance:
            chosen.append(f)
            gain += f[1]
            used += _length(f[2])
    chosen.sort(key=lambda f: f[0])                            # in race order
    gaps = [rng.uniform(0.5, 1.5) for _ in range(len(chosen) + 1)]
    rest = distance - used
    segments: List[Segment] = []
    for i, gap in enumerate(gaps):
        segments += _flat(rng, rest * gap / sum(gaps))
        if i < len(chosen):
            segments += chosen[i][2]
    name = route_name(name) or f'{race.name} · versión de {distance_km:.0f} km'
    data = to_gpx(segments, name, seed)
    return parse_gpx(data, 'generated.gpx'), data, seed


# ---- GPX ---------------------------------------------------------------------------------------------------------
MAX_NAME = 80


def route_name(name) -> Optional[str]:
    """A rider's route name, trimmed; None for none (then one is proposed)."""
    if name is None:
        return None
    if not isinstance(name, str) or len(name.strip()) > MAX_NAME:
        raise ValueError(f'name must be a text of at most {MAX_NAME} characters')
    return ' '.join(name.split()) or None


def _seed(seed: Optional[int]) -> int:
    if seed is None:
        return random.randrange(1, 100000)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 10 ** 9:
        raise ValueError('seed must be a whole number from 0')
    return seed


def to_gpx(segments: List[Segment], name: str, seed: Optional[int] = None) -> bytes:
    """A GPX track with a point every POINT_M along a smooth synthetic line, with the elevation of ``segments``."""
    total = _length(segments)
    rng = random.Random(len(segments))
    marks, d, elevation, low = [(0.0, START_ELEVATION_M)], 0.0, START_ELEVATION_M, START_ELEVATION_M
    for length, grade in segments:
        d += length
        elevation += length * grade / 100
        marks.append((d, elevation))
        low = min(low, elevation)
    lift = max(0.0, 50 - low)                                  # never below sea level (+50 m)
    points, j, lat, lon, heading, at = [], 0, 0.0, 0.0, rng.uniform(0, 2 * math.pi), 0.0
    n = int(math.ceil(total / POINT_M))
    for i in range(n + 1):
        target = min(i * POINT_M, total)
        while j + 1 < len(marks) - 1 and marks[j + 1][0] < target:
            j += 1
        (d0, e0), (d1, e1) = marks[j], marks[min(j + 1, len(marks) - 1)]
        ele = e0 + (e1 - e0) * ((target - d0) / (d1 - d0) if d1 > d0 else 0)
        if i:
            step = target - at
            heading += rng.gauss(0, 0.05)                      # a gently winding road
            lat += math.degrees(step * math.cos(heading) / EARTH_RADIUS_M)
            lon += math.degrees(step * math.sin(heading) / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
        at = target
        points.append(f'<trkpt lat="{lat:.7f}" lon="{lon:.7f}"><ele>{ele + lift:.1f}</ele></trkpt>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="AI Cycling Coach (generated route)" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<metadata><name>{escape(name)}</name><desc>Ruta generada{f" (variante {seed})" if seed is not None else ""}: '
            f'recorrido sintético (solo cuentan la distancia y el desnivel)</desc></metadata><trk><name>{escape(name)}</name><trkseg>'
            + ''.join(points) + '</trkseg></trk></gpx>').encode('utf-8')
