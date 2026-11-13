"""A GPX route as a road profile: distance, elevation and grade every 5 m, to ride on the virtual road.

Reading (standard library only):
- GPX 1.0 or 1.1, track points (``trk/trkseg/trkpt``) or, if there are none, route points (``rte/rtept``);
  every point needs ``lat``, ``lon`` and ``ele``. Distance between points: haversine on a 6 371 km sphere.
- Files with a DOCTYPE or ENTITY declaration are refused (no XML entity tricks), and the size is capped by the
  store (coach/app/routes_store.py).

Profile:
- Resampled every ``STEP_M`` (5 m) by linear interpolation along the distance. Measured: 10 m blurred a real
  1→5 % ramp over 80 m, 5 m keeps it within 70 m and a short roller felt as 1.4 % instead of 1.3 %; a 100 km
  route still takes ~0.02 s.
- GPX elevation is noisy (GPS, or a DEM sampled point by point), so it is smoothed before use. Two profiles:
  * GRADE (what the rider feels), method of Serpentine (MIT, chrisperkles/serpentine src/geo/route.ts @e4f2126):
    a ±30 m moving average applied 3 times (the window shrinks symmetrically at the ends, which keeps a constant
    slope), then the grade at each point is the central difference over ±20 m (40 m). Compared with our first
    method (one 100 m average, grade per 10 m step) on synthetic routes: false spikes on a noisy flat road
    1.3 % instead of 2.1 %, a real 1→5 % ramp kept within 70 m instead of 80 m, same mean on a 6 % climb; a
    short 100 m roller of 2 % is felt as 1.4 % instead of 1.6 % (the price of less noise).
  * ELEVATION and GAIN (the chart and the summary): one centred ``SMOOTH_M`` (100 m) average, reflected at the
    ends; gain = sum of its rises. Unchanged on purpose: no method measured (ours, Serpentine's 1 m threshold,
    GoldenCheetah's 3 m threshold, gpxpy's light smoothing) was best both with GPS noise and with small real
    rollers; to be decided with real race GPX files against their official gain.
- Grades are clipped to what the rider may ask (grade_controller.TARGET_RANGE, -15 … +20 %); how many 5 m steps
  were clipped is reported.

On the virtual road (coach/session/virtual_ride.py) the TARGET grade is the profile's grade at the distance
ridden since the route started; the road grade still moves towards it by at most 1 % every 20 m, so even a
badly drawn GPX never makes a wall. At the end of the route the target becomes flat (0 %).
"""
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional

STEP_M = 5.0
SMOOTH_M = 100.0            # elevation and gain profile
GRADE_SMOOTH_RADIUS_M = 30.0  # grade profile (Serpentine): ±30 m average …
GRADE_SMOOTH_PASSES = 3       # … applied 3 times …
GRADE_HALF_BASE_M = 20.0      # … then central difference over ±20 m
MIN_DISTANCE_M = 200.0
MAX_POINTS = 200_000
EARTH_RADIUS_M = 6_371_000


class RouteError(ValueError):
    """Not a usable GPX route (message for the rider)."""


@dataclass
class Route:
    file: str
    name: str
    distance_m: float
    elevations: List[float] = field(repr=False)   # smoothed, one every STEP_M from 0
    grades: List[float] = field(repr=False)       # % of each STEP_M step (len = len(elevations) - 1)
    gain_m: float = 0.0
    loss_m: float = 0.0
    clipped_steps: int = 0
    source_points: int = 0

    def grade_at(self, distance_m: float) -> Optional[float]:
        """Grade at ``distance_m`` from the start; None after the end."""
        if distance_m < 0:
            distance_m = 0.0
        if distance_m >= self.distance_m:
            return None
        return self.grades[min(int(distance_m // STEP_M), len(self.grades) - 1)]

    def summary(self) -> dict:
        return {'file': self.file, 'name': self.name, 'distanceKm': round(self.distance_m / 1000, 2),
                'elevationGainM': round(self.gain_m), 'elevationLossM': round(self.loss_m),
                'maxGradePercent': round(max(self.grades), 1), 'minGradePercent': round(min(self.grades), 1),
                'clippedSteps': self.clipped_steps, 'points': self.source_points}

    def profile(self, max_points: int = 600) -> List[dict]:
        """Downsampled profile for the charts: distance (km), elevation (m), grade (%) of the following step."""
        every = max(1, math.ceil(len(self.elevations) / max_points))
        out = []
        for i in range(0, len(self.elevations), every):
            out.append({'d': round(min(i * STEP_M, self.distance_m) / 1000, 3), 'e': round(self.elevations[i], 1),
                        'g': round(self.grades[min(i, len(self.grades) - 1)], 1)})
        if out[-1]['d'] < round(self.distance_m / 1000, 3):
            out.append({'d': round(self.distance_m / 1000, 3), 'e': round(self.elevations[-1], 1),
                        'g': round(self.grades[-1], 1)})
        return out


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def parse_gpx(data: bytes, file: str = 'route.gpx') -> Route:
    from coach.devices.grade_controller import TARGET_RANGE
    if re.search(rb'<!(DOCTYPE|ENTITY)', data[:4096] + data[-4096:], re.I) or re.search(rb'<!ENTITY', data, re.I):
        raise RouteError('GPX files with DOCTYPE/ENTITY declarations are not accepted')
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RouteError(f'Not valid XML: {exc}')
    if _local(root.tag) != 'gpx':
        raise RouteError('Not a GPX file (the root element is not <gpx>)')

    name = None
    points = []
    for kind in ('trkpt', 'rtept'):
        for element in root.iter():
            tag = _local(element.tag)
            if name is None and tag == 'name' and (element.text or '').strip():
                name = element.text.strip()[:120]
            if tag != kind:
                continue
            ele = next((c.text for c in element if _local(c.tag) == 'ele'), None)
            try:
                lat, lon = float(element.get('lat')), float(element.get('lon'))
                elevation = float(ele) if ele is not None else None
            except (TypeError, ValueError):
                raise RouteError('A point has no valid lat/lon/ele')
            if elevation is None:
                raise RouteError('The route has no elevation (<ele>): export it with elevation')
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not math.isfinite(elevation):
                raise RouteError('A point has coordinates or elevation out of range')
            points.append((lat, lon, elevation))
            if len(points) > MAX_POINTS:
                raise RouteError(f'More than {MAX_POINTS} points')
        if points:
            break
    if len(points) < 2:
        raise RouteError('The GPX has fewer than 2 points with elevation')

    distances, total = [0.0], 0.0
    for (la1, lo1, _), (la2, lo2, _) in zip(points, points[1:]):
        total += haversine_m(la1, lo1, la2, lo2)
        distances.append(total)
    if total < MIN_DISTANCE_M:
        raise RouteError(f'The route is shorter than {MIN_DISTANCE_M:.0f} m')

    raw = _resample(distances, [p[2] for p in points], total)
    elevations = _smooth(raw, int(SMOOTH_M // STEP_M))
    low, high = TARGET_RANGE
    grades, clipped = [], 0
    for grade in _grades(raw, total):
        if not low <= grade <= high:
            clipped += 1
            grade = min(high, max(low, grade))
        grades.append(grade)
    rises = [b - a for a, b in zip(elevations, elevations[1:])]
    return Route(file=file, name=name or file.rsplit('.', 1)[0], distance_m=total, elevations=elevations,
                 grades=grades, gain_m=sum(r for r in rises if r > 0), loss_m=-sum(r for r in rises if r < 0),
                 clipped_steps=clipped, source_points=len(points))


def _resample(distances, elevations, total):
    out, j = [], 0
    steps = int(total // STEP_M)
    targets = [i * STEP_M for i in range(steps + 1)]
    if targets[-1] < total:
        targets.append(total)
    for d in targets:
        while j < len(distances) - 2 and distances[j + 1] < d:
            j += 1
        d0, d1 = distances[j], distances[j + 1]
        e0, e1 = elevations[j], elevations[j + 1]
        out.append(e0 if d1 == d0 else e0 + (e1 - e0) * (d - d0) / (d1 - d0))
    return out


def _smooth_shrinking(values, radius, passes):
    """Serpentine's running mean: ±``radius`` samples, ``passes`` times; at the ends the window shrinks
    symmetrically, so the end points stay put and a constant slope is kept."""
    a = list(values)
    for _ in range(passes):
        prefix = [0.0]
        for v in a:
            prefix.append(prefix[-1] + v)
        out = []
        for i in range(len(a)):
            r = min(radius, i, len(a) - 1 - i)
            out.append((prefix[i + r + 1] - prefix[i - r]) / (2 * r + 1))
        a = out
    return a


def _grades(raw, total):
    """Grade (%) of each STEP_M step: smoothed elevation, central difference over ±GRADE_HALF_BASE_M at each point
    (real distances, so a short last step is not a spike), then the mean of the step's two end points."""
    ele = _smooth_shrinking(raw, round(GRADE_SMOOTH_RADIUS_M / STEP_M), GRADE_SMOOTH_PASSES)
    n = len(ele)
    position = [min(i * STEP_M, total) for i in range(n)]
    half = max(1, round(GRADE_HALF_BASE_M / STEP_M))
    at_point = []
    for i in range(n):
        a, b = max(0, i - half), min(n - 1, i + half)
        run = position[b] - position[a]
        at_point.append((ele[b] - ele[a]) / run * 100 if run > 0 else 0.0)
    return [(at_point[i] + at_point[i + 1]) / 2 for i in range(n - 1)]


def _smooth(values, window):
    """Centred moving average. At both ends the series is extended by point reflection (2·v0 − v[k]), which keeps
    a constant slope: a plain truncated window would flatten a route that starts or ends on a climb."""
    if window < 2 or len(values) < 3:
        return list(values)
    half = min(window // 2, len(values) - 1)
    first, last = values[0], values[-1]
    padded = ([2 * first - values[k] for k in range(half, 0, -1)] + list(values)
              + [2 * last - values[-1 - k] for k in range(1, half + 1)])
    prefix = [0.0]
    for v in padded:
        prefix.append(prefix[-1] + v)
    size = 2 * half + 1
    return [(prefix[i + size] - prefix[i]) / size for i in range(len(values))]
