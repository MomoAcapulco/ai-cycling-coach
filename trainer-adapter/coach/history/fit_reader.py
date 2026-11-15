"""Read FIT activity files (Garmin, Zwift, iGPSPORT, Wahoo, Strava's own…), standard library only.

The general FIT format is decoded: normal and compressed-timestamp record headers, little and big endian
definitions, developer fields (skipped by their size), arrays, strings, invalid values (returned as None) and
several FIT files chained in one. Only the messages and fields an activity history needs are given names and
scales (taken from the official profile, FIT SDK 21.171, like coach/session/fit_export.py); everything else is
skipped. Validated against Garmin's own Python decoder on 112 real activities (tests/test_fit_reader.py and the
import report).
"""
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
SEMICIRCLE_DEG = 180 / 2 ** 31

# base type code -> (struct format, invalid value or None for strings/bytes)
BASE_TYPES = {
    0x00: ('B', 0xFF), 0x01: ('b', 0x7F), 0x02: ('B', 0xFF), 0x83: ('h', 0x7FFF), 0x84: ('H', 0xFFFF),
    0x85: ('i', 0x7FFFFFFF), 0x86: ('I', 0xFFFFFFFF), 0x07: ('s', None), 0x88: ('f', 'nan'), 0x89: ('d', 'nan'),
    0x0A: ('B', 0x00), 0x8B: ('H', 0x0000), 0x8C: ('I', 0x00000000), 0x0D: ('B', 0xFF),
    0x8E: ('q', 0x7FFFFFFFFFFFFFFF), 0x8F: ('Q', 0xFFFFFFFFFFFFFFFF), 0x90: ('Q', 0x0000000000000000),
}

_BY_NUMBER = {code & 0x1F: code for code in BASE_TYPES}   # base type number -> full code

# The messages and fields used, from Profile.xlsx: {mesg_num: (name, {field_num: (name, scale, offset)})}
PROFILE = {
    0: ('file_id', {0: ('type', 1, 0), 1: ('manufacturer', 1, 0), 2: ('product', 1, 0), 4: ('time_created', 1, 0)}),
    18: ('session', {253: ('timestamp', 1, 0), 2: ('start_time', 1, 0), 5: ('sport', 1, 0), 6: ('sub_sport', 1, 0),
                     7: ('total_elapsed_time', 1000, 0), 8: ('total_timer_time', 1000, 0),
                     9: ('total_distance', 100, 0), 16: ('avg_heart_rate', 1, 0), 17: ('max_heart_rate', 1, 0),
                     18: ('avg_cadence', 1, 0), 20: ('avg_power', 1, 0), 21: ('max_power', 1, 0),
                     22: ('total_ascent', 1, 0), 23: ('total_descent', 1, 0), 34: ('normalized_power', 1, 0),
                     48: ('total_work', 1, 0)}),
    20: ('record', {253: ('timestamp', 1, 0), 0: ('position_lat', 1, 0), 1: ('position_long', 1, 0),
                    2: ('altitude', 5, 500), 3: ('heart_rate', 1, 0), 4: ('cadence', 1, 0), 5: ('distance', 100, 0),
                    6: ('speed', 1000, 0), 7: ('power', 1, 0), 73: ('enhanced_speed', 1000, 0),
                    78: ('enhanced_altitude', 5, 500)}),
    34: ('activity', {253: ('timestamp', 1, 0), 5: ('local_timestamp', 1, 0)}),
}
SPORTS = {0: 'generic', 1: 'running', 2: 'cycling', 4: 'fitness_equipment', 10: 'training', 11: 'walking',
          17: 'hiking'}
MANUFACTURERS = {1: 'garmin', 32: 'wahoo_fitness', 255: 'development', 260: 'zwift', 265: 'strava', 302: 'igpsport'}


class FitError(ValueError):
    """Not a readable FIT file."""


@dataclass
class FitActivity:
    file_id: dict = field(default_factory=dict)
    sessions: List[dict] = field(default_factory=list)
    records: List[dict] = field(default_factory=list)
    activity: dict = field(default_factory=dict)
    crc_ok: bool = True
    developer_fields_skipped: int = 0

    @property
    def start(self) -> Optional[datetime]:
        for candidate in ([s.get('start_time') for s in self.sessions] + [r.get('timestamp') for r in self.records[:1]]
                          + [self.file_id.get('time_created')]):
            if candidate is not None:
                return candidate
        return None


def _crc(data: bytes, crc: int = 0) -> int:
    table = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
             0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)
    for byte in data:
        tmp = table[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ table[byte & 0xF]
        tmp = table[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ table[(byte >> 4) & 0xF]
    return crc


def _value(raw: bytes, code: int, endian: str):
    fmt, invalid = BASE_TYPES.get(code) or BASE_TYPES.get(_BY_NUMBER.get(code & 0x1F), ('B', 0xFF))
    if fmt == 's':
        text = raw.split(b'\x00', 1)[0]
        return text.decode('utf-8', 'replace') or None
    size = struct.calcsize(fmt)
    if len(raw) < size:
        return None
    if len(raw) > size:                                   # an array: the first element is enough here
        raw = raw[:size]
    value = struct.unpack(endian + fmt, raw)[0]
    if invalid == 'nan':
        return None if value != value else value
    return None if value == invalid else value


def read_fit(data: bytes) -> FitActivity:
    """Decode every FIT file contained in ``data`` (FIT files may be chained) into one FitActivity."""
    out = FitActivity()
    position = 0
    while position < len(data):
        if len(data) - position < 12:
            break
        position = _read_one(data, position, out)
    if not out.file_id and not out.records:
        raise FitError('No FIT data')
    return out


def _read_one(data: bytes, start: int, out: FitActivity) -> int:
    header_size = data[start]
    if header_size not in (12, 14) or data[start + 8:start + 12] != b'.FIT':
        raise FitError('Not a FIT file (no .FIT signature)')
    data_size = struct.unpack('<I', data[start + 4:start + 8])[0]
    end = start + header_size + data_size
    if end + 2 > len(data):
        raise FitError('Truncated FIT file')
    if struct.unpack('<H', data[end:end + 2])[0] not in (0, _crc(data[start:end])):
        out.crc_ok = False
    i = start + header_size
    definitions: Dict[int, tuple] = {}
    last_timestamp = None
    while i < end:
        header = data[i]
        i += 1
        if header & 0x80:                                 # compressed timestamp header
            local = (header >> 5) & 0x03
            offset = header & 0x1F
            if last_timestamp is not None:
                timestamp = (last_timestamp & ~0x1F) + offset
                if offset < (last_timestamp & 0x1F):
                    timestamp += 0x20
                last_timestamp = timestamp
            compressed = True
        else:
            local = header & 0x0F
            compressed = False
            if header & 0x40:                             # definition message
                endian = '>' if data[i + 1] == 1 else '<'
                mesg_num = struct.unpack(endian + 'H', data[i + 2:i + 4])[0]
                count = data[i + 4]
                fields = [(data[i + 5 + 3 * k], data[i + 6 + 3 * k], data[i + 7 + 3 * k]) for k in range(count)]
                i += 5 + 3 * count
                developer_size = 0
                if header & 0x20:                         # developer data fields: skipped by size
                    dev_count = data[i]
                    developer_size = sum(data[i + 2 + 3 * k] for k in range(dev_count))
                    i += 1 + 3 * dev_count
                    out.developer_fields_skipped += dev_count
                definitions[local] = (mesg_num, endian, fields, developer_size)
                continue
        if local not in definitions:
            raise FitError('Data message without its definition')
        mesg_num, endian, fields, developer_size = definitions[local]
        known = PROFILE.get(mesg_num)
        values = {}
        for number, size, code in fields:
            raw = data[i:i + size]
            i += size
            if known and number in known[1]:
                values[number] = _value(raw, code, endian)
        i += developer_size
        if number_timestamp := values.get(253):
            last_timestamp = number_timestamp
        elif compressed and last_timestamp is not None:
            values[253] = last_timestamp
        if known:
            _store(out, known, values)
    return end + 2


def _store(out: FitActivity, known, values):
    name, spec = known
    message = {}
    for number, value in values.items():
        if value is None:
            continue
        field_name, scale, offset = spec[number]
        if field_name in ('timestamp', 'start_time', 'time_created', 'local_timestamp'):
            message[field_name] = FIT_EPOCH + timedelta(seconds=value)
        elif field_name in ('position_lat', 'position_long'):
            message[field_name] = value * SEMICIRCLE_DEG
        else:
            message[field_name] = value / scale - offset if (scale != 1 or offset) else value
    if name == 'file_id':
        out.file_id = out.file_id or message
    elif name == 'session':
        out.sessions.append(message)
    elif name == 'record':
        if 'enhanced_speed' in message:
            message['speed'] = message.pop('enhanced_speed')
        if 'enhanced_altitude' in message:
            message['altitude'] = message.pop('enhanced_altitude')
        out.records.append(message)
    elif name == 'activity':
        out.activity = message
