"""Step 3 of trainer control: a few native virtual gears around neutral, supervised.

Plan (about 100 s), every write checked by GuardedWriter against this exact plan:
  0-10 s   baseline: NO writes, free mode (measures the jump the rider felt when the Zwift mode starts)
  10 s     "RideOn 02 01"
  +0.5 s   Simulation 0.4 % (three projects: the trainer ignores gears until a non-zero incline is sent)
           Physical: gear 12 (2.40) + rider/bike weight, then HubRequest 520 (ask the applied gear)
  +20 s    gear 13 (2.61)   — skipped if cadence < 40 rpm (never harder while not pedalling)
  +15 s    gear 12
  +15 s    gear 11 (2.22)
  +15 s    gear 12, then 15 s more and stop
On Ctrl+C, stale telemetry (> 3 s) or any error: gear 12 + 0.4 % are sent (if connected) and the data saved.
"41 08 05" is NOT sent: our KICKR firmware 3.5.11 answers "No handler for opcode 65".

Requires --confirm. Weights: --rider-kg/--bike-kg, else the saved rider profile.
"""
import argparse
import asyncio
import json
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script from anywhere

from coach.devices.zwift_hub import (ASYNC, DATA_ID_GEAR_RATIO, NEUTRAL_GEAR, RIDE_ON_TRAINER, SYNC_RX,  # noqa: E402
                                     SYNC_TX, Physical, Simulation, decode_riding_data, describe,
                                     encode_hub_command, encode_hub_request, gear_ratio)

BASELINE_SECONDS = 10
NEUTRAL_HOLD_SECONDS = 20
STEP_SECONDS = 15
START_INCLINE_X100 = 40        # 0.4 %
MIN_CADENCE_TO_GO_HARDER = 40  # rpm
STALE_SECONDS = 3.0
GEAR_SEQUENCE = (13, 12, 11, 12)
ALLOWED_GEARS = (11, 12, 13)


def gear_message(gear, rider_kg, bike_kg):
    if gear not in ALLOWED_GEARS:
        raise ValueError(f'gear {gear} is outside this test ({ALLOWED_GEARS})')
    return encode_hub_command(physical=Physical.of(gear_ratio(gear), bike_kg=bike_kg, rider_kg=rider_kg))


def build_plan(rider_kg, bike_kg):
    """[(seconds after start, label, [messages to SyncRx])]."""
    start = BASELINE_SECONDS
    plan = [(start, 'ride_on', [RIDE_ON_TRAINER]),
            (start + 0.5, 'gear_12', [encode_hub_command(simulation=Simulation(incline_x100=START_INCLINE_X100)),
                                      gear_message(NEUTRAL_GEAR, rider_kg, bike_kg),
                                      encode_hub_request(DATA_ID_GEAR_RATIO)])]
    t = start + 0.5 + NEUTRAL_HOLD_SECONDS
    for gear in GEAR_SEQUENCE:
        plan.append((t, f'gear_{gear}', [gear_message(gear, rider_kg, bike_kg), encode_hub_request(DATA_ID_GEAR_RATIO)]))
        t += STEP_SECONDS
    plan.append((t, 'end', []))
    return plan


def allowed_messages(rider_kg, bike_kg):
    messages = {msg for _t, _label, msgs in build_plan(rider_kg, bike_kg) for msg in msgs}
    messages.add(encode_hub_command(simulation=Simulation(incline_x100=START_INCLINE_X100)))
    return {(SYNC_RX, msg) for msg in messages}


class GuardedWriter:
    """Only the messages of this plan, only to SyncRx, write without response."""
    def __init__(self, client, allowed):
        self.client = client
        self.allowed = set(allowed)
        self.sent = []

    async def write(self, uuid, data: bytes, at=None):
        if (uuid.lower(), bytes(data)) not in self.allowed:
            raise PermissionError(f'write refused by the gear test: {uuid} {bytes(data).hex()}')
        await self.client.write_gatt_char(uuid, data, response=False)
        self.sent.append({'t': at, 'hex': bytes(data).hex()})


def summarise(segments, riding, ftms, events=()):
    """Per segment: mean FTMS power/cadence/speed, Zwift unknown6 values seen, and when unknown6 first
    equalled the ratio we sent (the candidate confirmation that the trainer applied the gear)."""
    from coach.devices.zwift_hub import decode_hub_response
    confirmations = []
    for e in events:
        response = decode_hub_response(bytes.fromhex(e['hex']))
        if response and response.get('dataId') == DATA_ID_GEAR_RATIO and 'gearRatioX10000' in response:
            confirmations.append({'t': e['t'], 'ratio': response['gearRatioX10000']})
    out = []
    for i, seg in enumerate(segments):
        end = segments[i + 1]['t'] if i + 1 < len(segments) else float('inf')
        f = [x for x in ftms if seg['t'] <= x['t'] < end]
        r = [x for x in riding if seg['t'] <= x['t'] < end]

        def mean(rows, key):
            values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
            return round(sum(values) / len(values), 1) if values else None
        expected = seg.get('ratioX10000')
        match = next((x['t'] - seg['t'] for x in r if expected is not None and x.get('unknown6') == expected), None)
        confirmed = [x for x in confirmations if seg['t'] <= x['t'] < end]
        out.append({'label': seg['label'], 'startSeconds': round(seg['t'], 1), 'sentRatioX10000': expected,
                    'skipped': seg.get('skipped'),
                    'ftmsPowerW': mean(f, 'powerWatts'), 'ftmsCadenceRpm': mean(f, 'cadenceRpm'),
                    'ftmsSpeedKph': mean(f, 'speedKph'),
                    'unknown6Seen': sorted({x['unknown6'] for x in r if 'unknown6' in x}),
                    'unknown6MatchedAfterSeconds': round(match, 2) if match is not None else None,
                    # The trainer's own answer to HubRequest 520: the ratio it applied (±1 of rounding).
                    'confirmedRatioX10000': confirmed[0]['ratio'] if confirmed else None,
                    'confirmedAfterSeconds': round(confirmed[0]['t'] - seg['t'], 2) if confirmed else None,
                    'confirmedMatchesSent': (abs(confirmed[0]['ratio'] - expected) <= 1) if confirmed and expected else None})
    return out


async def run(rider_kg, bike_kg):
    from bleak import BleakClient
    from coach.bluetooth.discovery import TRAINER, classify, scan
    from coach.devices.wahoo import INDOOR_BIKE_DATA, parse_indoor_bike_data

    adverts = await scan(12)
    trainers = [(classify(a), a) for a in adverts.values() if classify(a).kind == TRAINER]
    if not trainers:
        return {'error': 'No trainer found (pedal a little to wake it; close Zwift/Wahoo apps).'}
    item, _ = max(trainers, key=lambda pair: pair[1].rssi or -999)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
    except (NotImplementedError, RuntimeError):
        pass
    events, ftms, riding, segments, notes = [], [], [], [], []
    started = monotonic()

    def at():
        return round(monotonic() - started, 3)

    def on_zwift(channel):
        def callback(_s, data):
            raw = bytes(data)
            decoded = describe(raw)
            events.append({'t': at(), 'channel': channel, 'hex': raw.hex(), 'decoded': decoded})
            rd = decode_riding_data(raw)
            if rd is not None:
                riding.append({'t': at(), **rd})
        return callback

    def on_ftms(_s, data):
        try:
            ftms.append({'t': at(), **parse_indoor_bike_data(bytes(data))})
        except ValueError:
            pass

    def ensure_live():
        """Never write without live data: called while waiting AND right before every write."""
        if not ftms:
            if at() > 2 * STALE_SECONDS:
                raise RuntimeError('no FTMS telemetry at all: stopping')
            return False
        if at() - ftms[-1]['t'] > STALE_SECONDS:
            raise RuntimeError('FTMS telemetry stale: stopping')
        return True

    plan = build_plan(rider_kg, bike_kg)
    print(f'Connecting to {item.name} {item.address} ...', flush=True)
    async with BleakClient(item.address, timeout=20) as client:
        available = {c.uuid.lower() for s in client.services for c in s.characteristics}
        if SYNC_RX not in available or ASYNC not in available or INDOOR_BIKE_DATA not in available:
            return {'error': 'Trainer lacks the Zwift channel or FTMS data', 'trainer': item.to_json()}
        writer = GuardedWriter(client, allowed_messages(rider_kg, bike_kg))
        await client.start_notify(INDOOR_BIKE_DATA, on_ftms)
        await client.start_notify(ASYNC, on_zwift('async'))
        if SYNC_TX in available:
            await client.start_notify(SYNC_TX, on_zwift('syncTx'))
        started = monotonic()
        segments.append({'t': 0.0, 'label': 'baseline_free_mode'})
        print(f'Baseline {BASELINE_SECONDS} s in free mode: pedal gently and steadily.', flush=True)
        session_open = False
        try:
            for when, label, messages in plan:
                while (at() < when or not ftms) and not stop.is_set():
                    await asyncio.sleep(0.1)
                    ensure_live()
                if stop.is_set():
                    notes.append('stopped by the rider (Ctrl+C)')
                    break
                if label == 'end':
                    break
                cadence = ftms[-1].get('cadenceRpm', 0) if ftms else 0
                if label == 'gear_13' and cadence < MIN_CADENCE_TO_GO_HARDER:
                    segments.append({'t': at(), 'label': label, 'skipped': f'cadence {cadence} rpm'})
                    print(f'  t={at():5.1f}s  {label} SKIPPED (cadence {cadence} rpm)', flush=True)
                    continue
                step_started = at()  # the segment starts when we SEND: confirmations arrive within ~0.1 s
                for msg in messages:
                    if not ensure_live():
                        raise RuntimeError('no FTMS telemetry yet: stopping')
                    await writer.write(SYNC_RX, msg, at())
                    await asyncio.sleep(0.15)
                session_open = True
                gear = int(label.split('_')[1]) if label.startswith('gear_') else None
                segments.append({'t': step_started, 'label': label,
                                 'ratioX10000': round(gear_ratio(gear) * 10000) if gear else None})
                last = ftms[-1] if ftms else {}
                print(f'  t={at():5.1f}s  {label:8}  now {last.get("powerWatts", "—")} W '
                      f'{last.get("cadenceRpm", "—")} rpm', flush=True)
        except Exception as exc:
            notes.append(f'aborted: {type(exc).__name__}: {exc}')
            print('ABORT:', exc, flush=True)
        finally:
            if session_open and client.is_connected:
                try:  # leave the trainer in the known neutral state
                    await writer.write(SYNC_RX, encode_hub_command(simulation=Simulation(incline_x100=START_INCLINE_X100)), at())
                    await writer.write(SYNC_RX, gear_message(NEUTRAL_GEAR, rider_kg, bike_kg), at())
                    notes.append('left in gear 12 at 0.4 %')
                except Exception as exc:
                    notes.append(f'could not restore neutral: {exc}')
            for uuid in (INDOOR_BIKE_DATA, ASYNC, SYNC_TX):
                if uuid in available and client.is_connected:
                    try:
                        await client.stop_notify(uuid)
                    except Exception:
                        pass
    return {'trainer': item.to_json(), 'riderKg': rider_kg, 'bikeKg': bike_kg, 'notes': notes,
            'sent': writer.sent, 'segments': summarise(segments, riding, ftms, events),
            'zwiftEvents': events, 'ftms': ftms}


def weights(args):
    if args.rider_kg is not None and args.bike_kg is not None:
        return args.rider_kg, args.bike_kg
    from coach.app.rider_profile import ProfileStore
    profile, saved = ProfileStore.default().load()
    if not saved:
        raise SystemExit('No saved rider profile: pass --rider-kg and --bike-kg (e.g. --rider-kg 80 --bike-kg 9)')
    return profile.rider_weight_kg, profile.bike_weight_kg


def main():
    parser = argparse.ArgumentParser(description='Step 3: a few native virtual gears around neutral (supervised).')
    parser.add_argument('--confirm', action='store_true', help='required: you are on the bike, pedalling gently')
    parser.add_argument('--rider-kg', type=float)
    parser.add_argument('--bike-kg', type=float)
    parser.add_argument('--out')
    args = parser.parse_args()
    if not args.confirm:
        print('This test CHANGES the trainer resistance (gears 11-13 around neutral). Read the guide first;')
        print('run again with --confirm when you are on the bike.')
        return 2
    rider_kg, bike_kg = weights(args)
    if not (30 <= rider_kg <= 250 and 3 <= bike_kg <= 40):
        raise SystemExit('weights out of range')
    print(f'Weights: rider {rider_kg:g} kg, bike {bike_kg:g} kg. Ctrl+C stops safely (back to gear 12).', flush=True)
    result = asyncio.run(run(rider_kg, bike_kg))
    result['testedAtUtc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    from coach.app.paths import diagnostics_dir
    folder = Path(args.out) if args.out else diagnostics_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('zwift_gear_test_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '.json')
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    if 'error' in result:
        print('ERROR:', result['error'])
    else:
        print(f'{"segment":20} {"W":>6} {"rpm":>6} {"km/h":>6}  unknown6 seen / matched')
        for s in result['segments']:
            print(f'{s["label"]:20} {s["ftmsPowerW"] or "—":>6} {s["ftmsCadenceRpm"] or "—":>6} {s["ftmsSpeedKph"] or "—":>6}  '
                  f'{s["unknown6Seen"]} / {s["unknown6MatchedAfterSeconds"]}{"  SKIPPED " + s["skipped"] if s.get("skipped") else ""}')
        for note in result['notes']:
            print('note:', note)
    print(f'Saved: {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
