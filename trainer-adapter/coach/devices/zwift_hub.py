"""Zwift protocol spoken by the trainer itself (KICKR CORE 2 with Zwift Cog: service 0xFC82).

Message layout, scaling and handshake ported from Serpentine (MIT, github.com/chrisperkles/serpentine,
src/devices/zwift.ts @e4f2126), cross-checked with Incyclist (MIT). Every message is
``[type byte][protobuf]`` written WITHOUT response to SyncRx (…0003); the trainer answers on Async
(…0002) and SyncTx (…0004).

- Handshake: ``RideOn 02 01`` then ``41 08 05``; the trainer then sends RidingData (type 0x03).
- HubCommand (type 0x04): field 3 power target (W); field 4 Simulation {1 wind m/s×100 (sint),
  2 incline %×100 (sint), 3 CWa×10000, 4 Crr×100000}; field 5 Physical {2 gear ratio×10000,
  4 bike kg×100, 5 rider kg×100}. A gear is sent as a RATIO, not an index.
- HubRequest (type 0x00): field 1 data id; 520 asks for the gear ratio. Incyclist also asks 512 (meaning not
  documented): the grade test (tools/zwift_grade_test.py) records what our trainer answers.
- RidingData (type 0x03), 1 Hz: 1 power W, 2 cadence rpm, 3 speed in m/s×100 (cm/s), 4 heart rate,
  plus 5 and 6 whose meaning is not documented (kept raw as unknown5/unknown6).

Measured on our KICKR CORE 2, firmware 3.5.11 (diagnostics/zwift_hub_probe_20261112_154311.json):
- RideOn 02 01 is answered on SyncTx with "RideOn 02 03"; RidingData starts ~1 s later.
- "41 08 05" is NOT supported: the trainer logs "ZP: No handler for opcode 65" and answers 0x3E {1: 65, 2: 1}.
- Field 3 is m/s×100: 471 = 4.71 m/s = 16.96 km/h, matching FTMS (16.97 km/h). Power and cadence match FTMS.
- Field 6 stayed 23003 for the whole minute (no gear sent yet); field 5 follows the speed (about 29 × field 3).
- Type 0x2A on Async is a text log from the trainer: {1: level, 2: {4: text}}.

Measured in the gear test (diagnostics/zwift_gear_test_20261112_155523.json):
- HubRequest 520 is answered on SyncTx with type 0x3C {1: 520, 2: {1: {8: gear ratio×10000}}}: the ratio the
  trainer actually APPLIED (24000 for gear 12, 26099 for 13, 22200 for 11). This is the confirmation to use.
- Field 6 of RidingData stayed 23003 whatever the gear: it is not the gear.
- In Zwift mode the FTMS speed is the virtual speed: cadence × ratio × ~2.1 m (60 rpm × 2.40 ≈ 18.2 km/h).
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

SERVICE_FC82 = '0000fc82-0000-1000-8000-00805f9b34fb'
SERVICE_19CA = '00000001-19ca-4651-86e5-fa29dcdd09d1'
ASYNC = '00000002-19ca-4651-86e5-fa29dcdd09d1'
SYNC_RX = '00000003-19ca-4651-86e5-fa29dcdd09d1'
SYNC_TX = '00000004-19ca-4651-86e5-fa29dcdd09d1'
# Never written by this application: Nordic DFU (firmware update) lives here on the KICKR.
FORBIDDEN_SERVICES = ('0000fe59-0000-1000-8000-00805f9b34fb',)

OP_HUB_REQUEST = 0x00
OP_RIDING_DATA = 0x03
OP_HUB_COMMAND = 0x04

RIDE_ON = b'RideOn'
RIDE_ON_TRAINER = RIDE_ON + bytes([0x02, 0x01])
TRAINER_HANDSHAKE_2 = bytes([0x41, 0x08, 0x05])
DATA_ID_GEAR_RATIO = 520

# Zwift's 24 virtual gears (same table in Serpentine, Incyclist and SHIFTR). Gear 12 = 2.40 is neutral.
GEAR_RATIOS = (0.75, 0.87, 0.99, 1.11, 1.23, 1.38, 1.53, 1.68, 1.86, 2.04, 2.22, 2.40,
               2.61, 2.82, 3.03, 3.24, 3.49, 3.74, 3.99, 4.24, 4.54, 4.84, 5.14, 5.49)
NEUTRAL_GEAR = 12


def gear_ratio(gear: int) -> float:
    if not 1 <= gear <= len(GEAR_RATIOS):
        raise ValueError(f'gear must be 1..{len(GEAR_RATIOS)}')
    return GEAR_RATIOS[gear - 1]


# ---- protobuf (only what this protocol uses: varints and nested messages) ----------------------

def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError('varint must be non-negative')
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def zigzag(value: int) -> int:
    return value * 2 if value >= 0 else -value * 2 - 1


def unzigzag(value: int) -> int:
    return value // 2 if value % 2 == 0 else -(value + 1) // 2


def _uint_field(number: int, value: Optional[int]) -> bytes:
    return b'' if value is None else encode_varint(number << 3) + encode_varint(value)


def _sint_field(number: int, value: Optional[int]) -> bytes:
    return b'' if value is None else encode_varint(number << 3) + encode_varint(zigzag(value))


def _message_field(number: int, body: bytes) -> bytes:
    return encode_varint((number << 3) | 2) + encode_varint(len(body)) + body if body else b''


def decode_fields(buf: bytes) -> List[Tuple[int, int, object]]:
    """[(field number, wire type, value)] — varints as int, length-delimited as bytes. Stops at garbage."""
    fields = []
    i = 0

    def varint():
        nonlocal i
        value = shift = 0
        while i < len(buf) and shift < 70:
            byte = buf[i]
            i += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
        return None

    while i < len(buf):
        tag = varint()
        if tag is None:
            break
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value = varint()
            if value is None:
                break
            fields.append((number, 0, value))
        elif wire == 2:
            length = varint()
            if length is None or i + length > len(buf):
                break
            fields.append((number, 2, bytes(buf[i:i + length])))
            i += length
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            break
    return fields


# ---- messages to the trainer -------------------------------------------------------------------

@dataclass(frozen=True)
class Simulation:
    incline_x100: int = 0
    wind_x100: int = 0
    cwa_x10000: int = 5100     # 0.51, Zwift's default (Serpentine, Incyclist)
    crr_x100000: int = 400     # 0.004


@dataclass(frozen=True)
class Physical:
    gear_ratio_x10000: int
    bike_weight_x100: int
    rider_weight_x100: int

    @classmethod
    def of(cls, ratio: float, bike_kg: float, rider_kg: float):
        return cls(round(ratio * 10000), round(bike_kg * 100), round(rider_kg * 100))


def encode_hub_command(power_target: Optional[int] = None, simulation: Optional[Simulation] = None,
                       physical: Optional[Physical] = None) -> bytes:
    out = bytes([OP_HUB_COMMAND]) + _uint_field(3, power_target)
    if simulation is not None:
        out += _message_field(4, _sint_field(1, simulation.wind_x100) + _sint_field(2, simulation.incline_x100)
                              + _uint_field(3, simulation.cwa_x10000) + _uint_field(4, simulation.crr_x100000))
    if physical is not None:
        out += _message_field(5, _uint_field(2, physical.gear_ratio_x10000) + _uint_field(4, physical.bike_weight_x100)
                              + _uint_field(5, physical.rider_weight_x100))
    return out


def encode_hub_request(data_id: int) -> bytes:
    return bytes([OP_HUB_REQUEST]) + _uint_field(1, data_id)


def decode_hub_command(msg: bytes) -> Optional[dict]:
    if not msg or msg[0] != OP_HUB_COMMAND:
        return None
    out = {}
    for number, wire, value in decode_fields(msg[1:]):
        if number == 3 and wire == 0:
            out['powerTarget'] = value
        elif number == 4 and wire == 2:
            names = {1: 'windX100', 2: 'inclineX100', 3: 'cwaX10000', 4: 'crrX100000'}
            out['simulation'] = {names[n]: (unzigzag(v) if n in (1, 2) else v)
                                 for n, w, v in decode_fields(value) if w == 0 and n in names}
        elif number == 5 and wire == 2:
            names = {2: 'gearRatioX10000', 4: 'bikeWeightX100', 5: 'riderWeightX100'}
            out['physical'] = {names[n]: v for n, w, v in decode_fields(value) if w == 0 and n in names}
    return out


# ---- messages from the trainer -----------------------------------------------------------------

def decode_riding_data(msg: bytes) -> Optional[Dict[str, float]]:
    if not msg or msg[0] != OP_RIDING_DATA:
        return None
    names = {1: 'powerWatts', 2: 'cadenceRpm', 3: 'speedCmPerS', 4: 'heartRateBpm', 5: 'unknown5', 6: 'unknown6'}
    out = {names[n]: v for n, w, v in decode_fields(msg[1:]) if w == 0 and n in names}
    if 'speedCmPerS' in out:
        out['speedKph'] = round(out.pop('speedCmPerS') / 100 * 3.6, 2)
    return out


def decode_log(msg: bytes) -> Optional[dict]:
    """Type 0x2A: the trainer's own text log, e.g. 'ZP: No handler for opcode 65'."""
    if not msg or msg[0] != 0x2A:
        return None
    level, text = None, None
    for number, wire, value in decode_fields(msg[1:]):
        if number == 1 and wire == 0:
            level = value
        elif number == 2 and wire == 2:
            for n, w, v in decode_fields(value):
                if n == 4 and w == 2:
                    text = v.decode('utf-8', 'replace').rstrip('\x00')
    return {'level': level, 'text': text}


OP_HUB_RESPONSE = 0x3C


def decode_hub_response(msg: bytes) -> Optional[dict]:
    """Type 0x3C, the answer to a HubRequest. For data id 520 it carries the applied gear ratio."""
    if not msg or msg[0] != OP_HUB_RESPONSE:
        return None
    out = {}
    for number, wire, value in decode_fields(msg[1:]):
        if number == 1 and wire == 0:
            out['dataId'] = value
        elif number == 2 and wire == 2:
            for n, w, v in decode_fields(value):
                if n == 1 and w == 2:
                    for n2, w2, v2 in decode_fields(v):
                        if n2 == 8 and w2 == 0:
                            out['gearRatioX10000'] = v2
    return out


def describe(msg: bytes) -> dict:
    """Best-effort decoding of any notification, for diagnostics."""
    if not msg:
        return {'type': None}
    if msg.startswith(RIDE_ON):
        return {'type': 'RideOn', 'tail': msg[len(RIDE_ON):].hex()}
    riding = decode_riding_data(msg)
    if riding is not None:
        return {'type': 'RidingData', **riding}
    log = decode_log(msg)
    if log is not None:
        return {'type': 'TrainerLog', **log}
    response = decode_hub_response(msg)
    if response is not None:
        # raw fields too: answers to other data ids (e.g. 512, asked in the grade test) are not decoded yet
        return {'type': 'HubResponse', **response, 'fields': _raw_fields(msg[1:])}
    return {'type': f'0x{msg[0]:02X}', 'fields': _raw_fields(msg[1:])}


def _raw_fields(buf: bytes) -> list:
    return [[n, w, v.hex() if isinstance(v, bytes) else v] for n, w, v in decode_fields(buf)]
