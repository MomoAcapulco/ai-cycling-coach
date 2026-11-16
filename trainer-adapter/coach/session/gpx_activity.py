"""Replay of a GPX that is a recorded ride (a point with its time, every second or so), not only a planned route.

``build_replay`` turns it into a recording the replay plays like a session: time, speed (from the positions, over
±5 s), distance along the route, the route's smoothed elevation and grade at that distance (the same numbers as the
Rutas page), and heart rate, cadence and power when the GPX has them (Garmin TrackPointExtension, or <power>). It is
written next to the sessions as ``gpx_<route>.csv`` with a ``.json`` that names the route (so the Panel draws it),
and is rebuilt only when the GPX is newer. Without times — a planned route — or with less than ``MIN_SECONDS`` of
them, there is nothing to replay: «datos insuficientes».
"""
import csv
import io
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from coach.session.route import STEP_M, Route, haversine_m
from coach.session.session import SESSION_FIELDS

MIN_SECONDS = 60
SPEED_HALF_WINDOW = 5          # points on each side for the speed
SENSORS = {'hr': 'hr', 'heartrate': 'hr', 'cad': 'cad', 'cadence': 'cad', 'power': 'power', 'watts': 'power'}


class NotEnoughData(ValueError):
    """The GPX cannot be replayed (message for the rider)."""


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1].lower()


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.strip().replace('Z', '+00:00'))


def read_points(data: bytes) -> List[dict]:
    """Track points with a time: {t, lat, lon, hr, cad, power} (sensors None when absent)."""
    points = []
    for _, element in ET.iterparse(io.BytesIO(data), events=('end',)):
        if _local(element.tag) != 'trkpt':
            continue
        point = {'hr': None, 'cad': None, 'power': None, 't': None}
        for child in element.iter():
            tag = _local(child.tag)
            if tag == 'time' and child.text:
                try:
                    point['t'] = _time(child.text)
                except ValueError:
                    pass
            elif tag in SENSORS and child.text:
                try:
                    point[SENSORS[tag]] = int(round(float(child.text)))
                except ValueError:
                    pass
        try:
            point['lat'], point['lon'] = float(element.get('lat')), float(element.get('lon'))
        except (TypeError, ValueError):
            point['t'] = None
        if point['t'] is not None:
            points.append(point)
        element.clear()
    return points


def replay_name(route_file: str) -> str:
    return f'gpx_{Path(route_file).stem}'


def build_replay(route: Route, gpx_path: Path, folder: Path) -> str:
    """Write (or reuse) the replay recording of a recorded GPX; returns the CSV name."""
    stem = replay_name(route.file)
    csv_path, json_path = Path(folder) / f'{stem}.csv', Path(folder) / f'{stem}.json'
    if csv_path.is_file() and json_path.is_file() and csv_path.stat().st_mtime >= gpx_path.stat().st_mtime:
        return csv_path.name
    points = read_points(gpx_path.read_bytes())
    points = [p for i, p in enumerate(points) if i == 0 or p['t'] > points[i - 1]['t']]   # time must go forward
    if len(points) < 2 or (points[-1]['t'] - points[0]['t']).total_seconds() < MIN_SECONDS:
        raise NotEnoughData('el GPX no tiene los tiempos de cada punto: es una ruta planificada, no una actividad '
                            'grabada' if len(points) < 2 else f'el GPX solo tiene {len(points)} puntos con tiempo')
    distances, total = [0.0], 0.0
    for a, b in zip(points, points[1:]):
        total += haversine_m(a['lat'], a['lon'], b['lat'], b['lon'])
        distances.append(total)
    scale = route.distance_m / total if total else 1.0          # the same line as the route: equal in practice
    t0 = points[0]['t']
    has = {k: any(p[k] is not None for p in points) for k in ('hr', 'cad', 'power')}
    Path(folder).mkdir(parents=True, exist_ok=True)
    tmp = csv_path.with_name(csv_path.name + '.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=SESSION_FIELDS, extrasaction='ignore')
        writer.writeheader()
        n = len(points)
        for i, p in enumerate(points):
            a, b = max(0, i - SPEED_HALF_WINDOW), min(n - 1, i + SPEED_HALF_WINDOW)
            seconds = (points[b]['t'] - points[a]['t']).total_seconds()
            speed = (distances[b] - distances[a]) / seconds * 3.6 if seconds > 0 else 0.0
            d = min(distances[i] * scale, route.distance_m)
            step = min(int(d // STEP_M), len(route.elevations) - 1)
            writer.writerow({
                'recordedAtUtc': p['t'].isoformat(), 'elapsedSeconds': round((p['t'] - t0).total_seconds(), 1),
                'source': 'GPX', 'connected': True, 'status': 'GPX',
                'powerWatts': '' if p['power'] is None else p['power'], 'cadenceRpm': '' if p['cad'] is None else p['cad'],
                'speedKph': round(speed, 2), 'rideSpeedKph': round(speed, 2),
                'heartRateBpm': '' if p['hr'] is None else p['hr'], 'heartRateConnected': p['hr'] is not None,
                'estimatedDistanceKm': round(d / 1000, 4), 'rideDistanceKm': round(d / 1000, 4),
                'altitudeM': round(route.elevations[step], 1), 'roadGradePercent': route.grade_at(min(d, route.distance_m - 0.01)),
                'routeName': route.name, 'routeProgressKm': round(d / 1000, 3),
            })
    tmp.replace(csv_path)
    json_path.write_text(json.dumps({'source': 'GPX', 'route': route.file, 'startedAtUtc': t0.isoformat(),
                                     'durationSeconds': (points[-1]['t'] - t0).total_seconds(),
                                     'sensors': [k for k, v in has.items() if v],
                                     'routes': [{'file': route.file, 'name': route.name,
                                                 'km': round(route.distance_m / 1000, 2)}]},
                                    ensure_ascii=False, indent=2), encoding='utf-8')
    return csv_path.name


def has_times(route: Optional[Route]) -> bool:
    return bool(route and route.timed_points >= 2)
