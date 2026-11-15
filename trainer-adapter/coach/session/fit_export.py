"""A finished session as a FIT activity file, to upload to intervals.icu, Strava, GoldenCheetah, TrainingPeaks…

Standard library only: a small FIT encoder for exactly the messages an activity needs. Message and field
numbers, base types, scales and enum values were taken from the official profile (FIT SDK 21.171, Profile.xlsx),
not from memory; the files are checked with the SDK's own decoders (tests/test_fit_export.py, and FitCSVTool when
the SDK is available).

File layout (Garmin's "activity file" structure):
  file_id · event timer start · record ×N (1 Hz) · [event timer stop / start at each pause] · event timer stop
  · lap · session · activity
Records: timestamp, power, cadence, heart rate (only while the strap streams), speed and distance of the virtual
road (physics speed; the trainer's own speed for old sessions without it), altitude relative to the start, and the
road grade. A dropout (no live trainer data) is written with the fields marked invalid: nothing is invented.
Session and lap totals come from the session summary (coach/session/metrics.py): timer time without pauses,
distance, work, average/max power, NP, IF, TSS and the FTP used, ascent, heart rate and cadence.
Sport: cycling; sub-sport "virtual activity" when the session has the virtual road, else "indoor cycling".
"""
import csv
import json
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
PROFILE_VERSION = 21171
PROTOCOL_VERSION = 0x20

# base types: (code, struct format, invalid value)
ENUM, UINT8, SINT16, UINT16, UINT32, UINT32Z = (
    (0x00, 'B', 0xFF), (0x02, 'B', 0xFF), (0x83, 'h', 0x7FFF), (0x84, 'H', 0xFFFF),
    (0x86, 'I', 0xFFFFFFFF), (0x8C, 'I', 0x00000000))

# mesg_num
FILE_ID, SESSION, LAP, RECORD, EVENT, ACTIVITY = 0, 18, 19, 20, 21, 34
# enums
FILE_ACTIVITY, MANUFACTURER_DEVELOPMENT, SPORT_CYCLING = 4, 255, 2
SUB_SPORT_INDOOR, SUB_SPORT_VIRTUAL = 6, 58
EVENT_TIMER, EVENT_SESSION, EVENT_LAP, EVENT_ACTIVITY = 0, 8, 9, 26
EVENT_TYPE_START, EVENT_TYPE_STOP, EVENT_TYPE_STOP_ALL = 0, 1, 4
ACTIVITY_MANUAL, LAP_TRIGGER_SESSION_END, SESSION_TRIGGER_ACTIVITY_END = 0, 7, 0

PAUSE_GAP_S = 2.5   # wall-clock time growing this much more than session time between samples = a pause

_CRC_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)


def fit_crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def fit_time(moment: datetime) -> int:
    return int((moment - FIT_EPOCH).total_seconds())


class FitWriter:
    """Definition + data messages, little endian, one local message type per global message."""
    def __init__(self):
        self.body = bytearray()
        self.defs = {}

    def define(self, local: int, mesg_num: int, fields):
        """``fields``: [(field number, base type)] in the order values will be written."""
        self.body += bytes([0x40 | local, 0, 0]) + struct.pack('<HB', mesg_num, len(fields))
        for number, (code, fmt, _invalid) in fields:
            self.body += bytes([number, struct.calcsize(fmt), code])
        self.defs[local] = fields

    def write(self, local: int, values):
        """``values``: one per field; None writes the base type's invalid value."""
        fields = self.defs[local]
        if len(values) != len(fields):
            raise ValueError('one value per field')
        self.body.append(local)
        for (_number, (_code, fmt, invalid)), value in zip(fields, values):
            if value is None:
                value = invalid
            else:
                value = int(round(value))
                low, high = _range(fmt)
                if not low <= value <= high or value == invalid:
                    value = invalid          # out of range for the field: invalid, never wrapped around
            self.body += struct.pack('<' + fmt, value)

    def to_bytes(self) -> bytes:
        header = struct.pack('<BBHI4s', 14, PROTOCOL_VERSION, PROFILE_VERSION, len(self.body), b'.FIT')
        header += struct.pack('<H', fit_crc(header))
        data = header + bytes(self.body)
        return data + struct.pack('<H', fit_crc(data))


def _range(fmt):
    return {'B': (0, 0xFF), 'h': (-0x8000, 0x7FFF), 'H': (0, 0xFFFF), 'I': (0, 0xFFFFFFFF)}[fmt]


def _num(value) -> Optional[float]:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _true(value) -> bool:
    return str(value).lower() in ('true', '1', 'yes')


def _time(iso: str) -> datetime:
    moment = datetime.fromisoformat(iso)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def session_to_fit(csv_path: Path, summary: dict) -> bytes:
    """FIT activity bytes for a finished session (its 1 Hz CSV and its summary JSON)."""
    with Path(csv_path).open(newline='', encoding='utf-8') as handle:
        rows = [r for r in csv.DictReader(handle) if r.get('recordedAtUtc')]
    if not rows:
        raise ValueError('The session has no samples')
    times = [_time(r['recordedAtUtc']) for r in rows]
    start = _time(summary['startedAtUtc']) if summary.get('startedAtUtc') else times[0]
    end = max(times[-1], _time(summary['finishedAtUtc'])) if summary.get('finishedAtUtc') else times[-1]
    virtual = any(_num(r.get('rideSpeedKph')) is not None for r in rows)
    altitudes = [_num(r.get('altitudeM')) for r in rows]
    base_altitude = next((a for a in altitudes if a is not None), None)

    w = FitWriter()
    w.define(0, FILE_ID, [(0, ENUM), (1, UINT16), (2, UINT16), (3, UINT32Z), (4, UINT32)])
    serial = (zlib.crc32(str(summary.get('session', 'session')).encode()) & 0x7FFFFFFF) or 1
    w.write(0, [FILE_ACTIVITY, MANUFACTURER_DEVELOPMENT, 1, serial, fit_time(start)])

    w.define(1, EVENT, [(253, UINT32), (0, ENUM), (1, ENUM)])
    w.write(1, [fit_time(start), EVENT_TIMER, EVENT_TYPE_START])

    w.define(2, RECORD, [(253, UINT32), (7, UINT16), (4, UINT8), (3, UINT8), (6, UINT16), (5, UINT32),
                         (2, UINT16), (9, SINT16)])
    previous = None
    for row, moment in zip(rows, times):
        elapsed = _num(row.get('elapsedSeconds')) or 0.0
        if previous is not None:
            wall_gap = (moment - previous[1]).total_seconds()
            if wall_gap - (elapsed - previous[0]) > PAUSE_GAP_S:   # paused in between: timer stop / start
                w.write(1, [fit_time(previous[1]), EVENT_TIMER, EVENT_TYPE_STOP_ALL])
                w.write(1, [fit_time(moment), EVENT_TIMER, EVENT_TYPE_START])
        previous = (elapsed, moment)
        live = _true(row.get('connected'))
        speed_kph = _num(row.get('rideSpeedKph')) if virtual else _num(row.get('speedKph'))
        distance_km = _num(row.get('estimatedDistanceKm'))
        altitude = _num(row.get('altitudeM'))
        grade = _num(row.get('roadGradePercent'))
        heart = _num(row.get('heartRateBpm')) if _true(row.get('heartRateConnected')) else None
        w.write(2, [fit_time(moment),
                    _num(row.get('powerWatts')) if live else None,
                    _num(row.get('cadenceRpm')) if live else None,
                    heart,
                    speed_kph / 3.6 * 1000 if live and speed_kph is not None else None,
                    distance_km * 1000 * 100 if distance_km is not None else None,
                    (altitude - base_altitude + 500) * 5 if altitude is not None and base_altitude is not None else None,
                    grade * 100 if grade is not None else None])
    w.write(1, [fit_time(end), EVENT_TIMER, EVENT_TYPE_STOP_ALL])

    timer_s = float(summary.get('elapsedSeconds') or 0.0)
    elapsed_s = max(timer_s, (end - start).total_seconds())
    distance_m = float(summary.get('distanceKm') or 0.0) * 1000
    avg_speed = distance_m / timer_s if timer_s > 0 else None
    speeds = [(_num(r.get('rideSpeedKph')) if virtual else _num(r.get('speedKph'))) for r in rows
              if _true(r.get('connected'))]
    max_speed = max((s for s in speeds if s is not None), default=None)
    sub_sport = SUB_SPORT_VIRTUAL if virtual else SUB_SPORT_INDOOR
    work_j = float(summary.get('workKj') or 0.0) * 1000
    totals = [fit_time(start), elapsed_s * 1000, timer_s * 1000, distance_m * 100,
              avg_speed * 1000 if avg_speed is not None else None, max_speed / 3.6 * 1000 if max_speed else None,
              summary.get('avgHeartRateBpm'), summary.get('maxHeartRateBpm'), summary.get('avgCadenceRpm'),
              summary.get('avgPowerW'), summary.get('maxPowerW'), summary.get('elevationGainM'),
              summary.get('normalizedPowerW'), work_j]

    w.define(3, LAP, [(254, UINT16), (253, UINT32), (0, ENUM), (1, ENUM), (2, UINT32), (7, UINT32), (8, UINT32),
                      (9, UINT32), (13, UINT16), (14, UINT16), (15, UINT8), (16, UINT8), (17, UINT8), (19, UINT16),
                      (20, UINT16), (21, UINT16), (33, UINT16), (41, UINT32), (24, ENUM), (25, ENUM), (39, ENUM)])
    w.write(3, [0, fit_time(end), EVENT_LAP, EVENT_TYPE_STOP] + totals[:] + [LAP_TRIGGER_SESSION_END, SPORT_CYCLING,
                                                                            sub_sport])

    intensity = summary.get('intensityFactor')
    tss = summary.get('tss')
    w.define(4, SESSION, [(254, UINT16), (253, UINT32), (0, ENUM), (1, ENUM), (2, UINT32), (7, UINT32),
                          (8, UINT32), (9, UINT32), (14, UINT16), (15, UINT16), (16, UINT8), (17, UINT8), (18, UINT8),
                          (20, UINT16), (21, UINT16), (22, UINT16), (34, UINT16), (48, UINT32), (5, ENUM), (6, ENUM),
                          (25, UINT16), (26, UINT16), (28, ENUM), (35, UINT16), (36, UINT16), (45, UINT16)])
    w.write(4, [0, fit_time(end), EVENT_SESSION, EVENT_TYPE_STOP] + totals[:]
            + [SPORT_CYCLING, sub_sport, 0, 1, SESSION_TRIGGER_ACTIVITY_END,
               tss * 10 if tss is not None else None, intensity * 1000 if intensity is not None else None,
               summary.get('ftpWatts')])

    w.define(5, ACTIVITY, [(253, UINT32), (0, UINT32), (1, UINT16), (2, ENUM), (3, ENUM), (4, ENUM), (5, UINT32)])
    w.write(5, [fit_time(end), timer_s * 1000, 1, ACTIVITY_MANUAL, EVENT_ACTIVITY, EVENT_TYPE_STOP, fit_time(end)])
    return w.to_bytes()


def session_fit(folder: Path, stem: str) -> bytes:
    """The FIT of session ``stem`` (session_YYYYmmdd_HHMMSS) from its files in ``folder``."""
    folder = Path(folder)
    summary = json.loads((folder / f'{stem}.json').read_text(encoding='utf-8'))
    return session_to_fit(folder / summary.get('csv', f'{stem}.csv'), summary)
