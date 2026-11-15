"""Import a Strava account export (the ZIP from Strava → Settings → My Account → Download your data).

Read straight from the ZIP (nothing is unpacked into the project): ``activities.csv`` gives the id, name, type,
date and Strava's own figures; the activity file (``activities/*.fit.gz``, ``.fit``, ``.gpx``, ``.tcx.gz``…) gives
the records, summarised with coach/history/store.summarize_records. Activities without a readable file keep
Strava's figures. The originals are copied to the data home (``history/files``) and the ZIP can then be deleted.

``activities.csv`` has columns with the same name twice (two "Distancia": km with a decimal comma, then metres),
so columns are read by position, located by name on the first occurrence and checked.
"""
import csv
import gzip
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from coach.history.fit_reader import FitError, MANUFACTURERS, read_fit
from coach.history.store import HistoryStore, summarize_records

TYPE_MAP = {'Bicicleta virtual': 'virtual_ride', 'Bicicleta': 'ride', 'Bicicleta de montaña': 'ride',
            'Bicicleta eléctrica': 'ride', 'Bicicleta de gravel': 'ride', 'Carrera': 'run', 'Carrera virtual': 'run',
            'Entrenamiento con pesas': 'strength', 'Entrenamiento': 'workout',
            'Virtual Ride': 'virtual_ride', 'Ride': 'ride', 'Mountain Bike Ride': 'ride', 'Gravel Ride': 'ride',
            'E-Bike Ride': 'ride', 'Run': 'run', 'Virtual Run': 'run', 'Weight Training': 'strength',
            'Workout': 'workout'}
MONTHS = {'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'ago': 8, 'sept': 9, 'sep': 9,
          'oct': 10, 'nov': 11, 'dic': 12, 'jan': 1, 'apr': 4, 'aug': 8, 'dec': 12}


def _number(text):
    try:
        return float(str(text).replace(',', '.')) if str(text).strip() != '' else None
    except ValueError:
        return None


def parse_date(text: str):
    """'12 sept 2026, 8:05:52' (Spanish export) or 'Sep 12, 2026, 8:05:52 AM' (English), as UTC."""
    text = text.strip()
    m = re.match(r'(\d{1,2}) (\w+)\.? (\d{4}),? (\d{1,2}):(\d{2}):(\d{2})', text)
    if m and m.group(2).lower() in MONTHS:
        day, month, year = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
        return datetime(year, month, day, int(m.group(4)), int(m.group(5)), int(m.group(6)), tzinfo=timezone.utc)
    for fmt in ('%b %d, %Y, %I:%M:%S %p', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class Columns:
    """Positions of the columns used (first occurrence of each name; the second "Distancia" is metres)."""
    def __init__(self, header):
        def first(*names):
            return next((header.index(n) for n in names if n in header), None)
        self.id = first('ID de actividad', 'Activity ID')
        self.date = first('Fecha de la actividad', 'Activity Date')
        self.name = first('Nombre de la actividad', 'Activity Name')
        self.type = first('Tipo de actividad', 'Activity Type')
        self.file = first('Nombre del archivo', 'Filename')
        distances = [i for i, h in enumerate(header) if h in ('Distancia', 'Distance')]
        self.distance_m = distances[1] if len(distances) > 1 else None
        elapsed = [i for i, h in enumerate(header) if h in ('Tiempo transcurrido', 'Elapsed Time')]
        self.elapsed = elapsed[-1] if elapsed else None
        self.moving = first('Tiempo en movimiento', 'Moving Time')
        self.ascent = first('Desnivel positivo', 'Elevation Gain')
        self.avg_hr = first('Frecuencia cardiaca promedio', 'Average Heart Rate')
        self.avg_power = first('Vatios promedio', 'Average Watts')
        self.relative_effort = first('Esfuerzo Relativo', 'Relative Effort')
        if None in (self.id, self.date, self.type):
            raise ValueError('activities.csv lacks the id, date or type column: not a Strava export?')


def import_strava_zip(zip_path: Path, store: HistoryStore) -> dict:
    """Import every activity of the export not already in ``store``. Returns counts and problems."""
    report = {'added': 0, 'already': 0, 'from_file': 0, 'csv_only': 0, 'problems': []}
    with zipfile.ZipFile(zip_path) as archive:
        if 'activities.csv' not in archive.namelist():
            raise ValueError('No activities.csv in the ZIP: not a Strava account export')
        reader = csv.reader(io.TextIOWrapper(archive.open('activities.csv'), encoding='utf-8'))
        cols = Columns(next(reader))
        for row in reader:
            if not row or len(row) <= cols.type:
                continue
            activity_id = f'strava:{row[cols.id]}'
            if store.has(activity_id):
                report['already'] += 1
                continue
            start = parse_date(row[cols.date])
            base = {'id': activity_id, 'source': 'strava', 'type': TYPE_MAP.get(row[cols.type], 'other'),
                    'name': row[cols.name] if cols.name is not None else None,
                    'start_utc': start.isoformat() if start else None,
                    'elapsed_s': _number(row[cols.elapsed]) if cols.elapsed is not None else None,
                    'moving_s': _number(row[cols.moving]) if cols.moving is not None else None,
                    'distance_m': _number(row[cols.distance_m]) if cols.distance_m is not None else None,
                    'ascent_m': _number(row[cols.ascent]) if cols.ascent is not None else None,
                    'avg_hr': _number(row[cols.avg_hr]) if cols.avg_hr is not None else None,
                    'avg_power': _number(row[cols.avg_power]) if cols.avg_power is not None else None,
                    'strava_relative_effort': _number(row[cols.relative_effort]) if cols.relative_effort is not None else None,
                    'has_power': int((_number(row[cols.avg_power]) or 0) > 0) if cols.avg_power is not None else 0,
                    'has_hr': int((_number(row[cols.avg_hr]) or 0) > 0) if cols.avg_hr is not None else 0}
            name = row[cols.file] if cols.file is not None else ''
            if name and name in archive.namelist():
                raw = archive.read(name)
                base['file'] = store.copy_file(f"strava_{row[cols.id]}_{Path(name).name}", raw)
                if '.fit' in name:
                    try:
                        fit = read_fit(gzip.decompress(raw) if name.endswith('.gz') else raw)
                        summary = summarize_records(fit.records, fit.sessions)
                        # Strava's elevation gain is what the rider sees and compares with: keep it when present
                        strava_ascent = base['ascent_m']
                        base.update({k: v for k, v in summary.items() if v is not None})
                        if strava_ascent is not None:
                            base['ascent_m'] = strava_ascent
                        maker = fit.file_id.get('manufacturer')
                        base['device'] = MANUFACTURERS.get(maker, str(maker) if maker is not None else None)
                        if fit.start is not None:
                            base['start_utc'] = fit.start.isoformat()
                        report['from_file'] += 1
                    except (FitError, OSError, EOFError, ValueError) as exc:
                        report['problems'].append(f'{name}: {exc}')
                        report['csv_only'] += 1
                else:
                    report['csv_only'] += 1   # GPX/TCX: Strava's figures are enough for the history
            else:
                report['csv_only'] += 1
            report['added'] += store.add(base)
    return report
