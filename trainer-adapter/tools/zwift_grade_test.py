"""Step 5 of trainer control: a gentle grade ramp over the native Zwift channel, supervised.

Plan (about 2.5 min, never above 1.5 %), every write checked by GuardedWriter against this exact plan:
  0-10 s     baseline: NO writes, free mode
  10 s       "RideOn 02 01"
  +0.5 s     0.4 % + gear 12 (weights), HubRequest 520 (gear) and 512 (unknown: Incyclist asks it)
  +20 s      1.0 %          — skipped if cadence < 40 rpm (never harder while not pedalling)
  +20 s      1.5 %          — idem (steps of 0.5-0.6 %: about +0.3 W per kg of rider and bike each, at 65 rpm)
  +10 s      gear 12 again, still at 1.5 %: does a gear message keep the grade? (the app sends gears alone)
  +10 s      1.0 %
  +20 s      0.4 %
  +20 s      0.0 %          — does an exact 0 switch the gears off? (Incyclist sends 0.01 % instead)
  +10 s      gear 13 at 0 % — skipped if cadence < 40; is it still confirmed (HubRequest 520)?
  +10 s      gear 12 at 0 %
  +10 s      0.4 %, then 15 s more and stop
After every grade change HubRequest 512 is sent and everything on Async/SyncTx is recorded, to find out
whether the trainer confirms a grade at all.
On Ctrl+C, stale telemetry (> 3 s) or any error: 0.4 % + gear 12 are sent (if connected) and the data saved.
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
                                     SYNC_TX, Simulation, decode_hub_response, decode_riding_data, describe,
                                     encode_hub_command, encode_hub_request, gear_ratio)
from tools.zwift_gear_test import GuardedWriter, gear_message, weights  # noqa: E402

BASELINE_SECONDS = 10
NEUTRAL_HOLD_SECONDS = 20
STEP_SECONDS = 20
SHORT_STEP_SECONDS = 10
FINAL_HOLD_SECONDS = 15
STALE_SECONDS = 3.0
MIN_CADENCE_TO_GO_HARDER = 40  # rpm
START_INCLINE_X100 = 40        # 0.4 %
DATA_ID_UNKNOWN_512 = 512
MAX_INCLINE_X100 = 150         # nothing above 1.5 % in this test

# (label, incline ×100 or None, gear or None, seconds held)
STEPS = (
    ('grade_1.0', 100, None, 'STEP'),
    ('grade_1.5', 150, None, 'SHORT'),
    ('gear_12_at_1.5', None, 12, 'SHORT'),
    ('grade_1.0_down', 100, None, 'STEP'),
    ('grade_0.4', 40, None, 'STEP'),
    ('grade_0.0', 0, None, 'SHORT'),
    ('gear_13_at_0.0', None, 13, 'SHORT'),
    ('gear_12_at_0.0', None, 12, 'SHORT'),
    ('grade_0.4_end', 40, None, 'FINAL'),
)


def grade_message(incline_x100):
    if not 0 <= incline_x100 <= MAX_INCLINE_X100:
        raise ValueError(f'grade {incline_x100 / 100:g} % is outside this test (0..1.5 %)')
    return encode_hub_command(simulation=Simulation(incline_x100=incline_x100))


def build_plan(rider_kg, bike_kg):
    """[(seconds after start, label, [messages to SyncRx], {'inclineX100': …, 'gear': …})]."""
    durations = {'STEP': STEP_SECONDS, 'SHORT': SHORT_STEP_SECONDS, 'FINAL': FINAL_HOLD_SECONDS}
    start = BASELINE_SECONDS
    plan = [(start, 'ride_on', [RIDE_ON_TRAINER], {}),
            (start + 0.5, 'start_0.4_gear_12',
             [grade_message(START_INCLINE_X100), gear_message(NEUTRAL_GEAR, rider_kg, bike_kg),
              encode_hub_request(DATA_ID_GEAR_RATIO), encode_hub_request(DATA_ID_UNKNOWN_512)],
             {'inclineX100': START_INCLINE_X100, 'gear': NEUTRAL_GEAR})]
    t = start + 0.5 + NEUTRAL_HOLD_SECONDS
    for label, incline, gear, hold in STEPS:
        if incline is not None:
            messages = [grade_message(incline), encode_hub_request(DATA_ID_UNKNOWN_512)]
        else:
            messages = [gear_message(gear, rider_kg, bike_kg), encode_hub_request(DATA_ID_GEAR_RATIO)]
        plan.append((t, label, messages, {'inclineX100': incline, 'gear': gear}))
        t += durations[hold]
    plan.append((t, 'end', [], {}))
    return plan


def restore_messages(rider_kg, bike_kg):
    return [grade_message(START_INCLINE_X100), gear_message(NEUTRAL_GEAR, rider_kg, bike_kg)]


def allowed_messages(rider_kg, bike_kg):
    messages = {msg for _t, _label, msgs, _step in build_plan(rider_kg, bike_kg) for msg in msgs}
    messages.update(restore_messages(rider_kg, bike_kg))
    return {(SYNC_RX, msg) for msg in messages}


def is_harder(step, incline_now, gear_now):
    incline, gear = step.get('inclineX100'), step.get('gear')
    return (incline is not None and incline > incline_now) or (gear is not None and gear > gear_now)


def summarise(segments, riding, ftms, events=()):
    """Per segment: FTMS and RidingData means, every message the trainer sent, gear confirmations."""
    out = []
    for i, seg in enumerate(segments):
        end = segments[i + 1]['t'] if i + 1 < len(segments) else float('inf')
        f = [x for x in ftms if seg['t'] <= x['t'] < end]
        r = [x for x in riding if seg['t'] <= x['t'] < end]
        e = [x for x in events if seg['t'] <= x['t'] < end]

        def mean(rows, key):
            values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
            return round(sum(values) / len(values), 1) if values else None
        types = {}
        for x in e:
            types[x['decoded'].get('type')] = types.get(x['decoded'].get('type'), 0) + 1
        responses = [{'t': round(x['t'] - seg['t'], 2), **x['decoded']} for x in e
                     if x['decoded'].get('type') == 'HubResponse']
        gear_answers = [x for x in responses if x.get('dataId') == DATA_ID_GEAR_RATIO and 'gearRatioX10000' in x]
        gear = seg.get('gear')
        expected = round(gear_ratio(gear) * 10000) if gear else None
        out.append({
            'label': seg['label'], 'startSeconds': round(seg['t'], 1), 'skipped': seg.get('skipped'),
            'sentInclinePercent': None if seg.get('inclineX100') is None else seg['inclineX100'] / 100,
            'sentGear': gear,
            'ftmsPowerW': mean(f, 'powerWatts'), 'ftmsCadenceRpm': mean(f, 'cadenceRpm'),
            'ftmsSpeedKph': mean(f, 'speedKph'), 'ridingDataPowerW': mean(r, 'powerWatts'),
            # power in the last 5 s of the segment: after the trainer settled
            'ftmsPowerLast5sW': mean([x for x in f if x['t'] >= (f[-1]['t'] - 5 if f else 0)], 'powerWatts'),
            'messageTypes': types,
            'hubResponses': responses,
            'trainerLogs': [x['decoded'].get('text') for x in e if x['decoded'].get('type') == 'TrainerLog'],
            'gearConfirmedRatioX10000': gear_answers[0]['gearRatioX10000'] if gear_answers else None,
            'gearConfirmedMatchesSent': (abs(gear_answers[0]['gearRatioX10000'] - expected) <= 2)
            if gear_answers and expected else None,
        })
    return out


def findings(summary):
    """The two open questions of step 5, answered from the data (None = no evidence either way)."""
    by_label = {s['label']: s for s in summary}
    at_zero = by_label.get('gear_13_at_0.0', {})
    answers_512 = [r for s in summary for r in s['hubResponses'] if r.get('dataId') == DATA_ID_UNKNOWN_512]
    other = sorted({r.get('dataId') for s in summary for r in s['hubResponses']} - {DATA_ID_GEAR_RATIO, None})
    return {
        'gearsConfirmedAtZeroGrade': at_zero.get('gearConfirmedMatchesSent') if not at_zero.get('skipped') else None,
        'answersTo512': answers_512[:5],
        'answersTo512Count': len(answers_512),
        'otherHubResponseIds': other,
        'note': 'Compare ftmsPowerLast5sW between grade segments (same cadence) to see the grade being applied; '
                'gear_12_at_1.5 vs grade_1.5 tells whether a gear message keeps the grade.',
    }


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
            events.append({'t': at(), 'channel': channel, 'hex': raw.hex(), 'decoded': describe(raw)})
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
        print(f'Baseline {BASELINE_SECONDS} s in free mode: pedal gently and steadily (70-90 rpm).', flush=True)
        session_open = False
        incline_now, gear_now = START_INCLINE_X100, NEUTRAL_GEAR
        try:
            for when, label, messages, step in plan:
                while (at() < when or not ftms) and not stop.is_set():
                    await asyncio.sleep(0.1)
                    ensure_live()
                if stop.is_set():
                    notes.append('stopped by the rider (Ctrl+C)')
                    break
                if label == 'end':
                    break
                cadence = ftms[-1].get('cadenceRpm', 0) if ftms else 0
                if session_open and is_harder(step, incline_now, gear_now) and cadence < MIN_CADENCE_TO_GO_HARDER:
                    segments.append({'t': at(), 'label': label, 'skipped': f'cadence {cadence} rpm'})
                    notes.append(f'{label} skipped: cadence {cadence} rpm')
                    print(f'  t={at():5.1f}s  {label} SKIPPED (cadence {cadence} rpm)', flush=True)
                    continue
                step_started = at()  # the segment starts when we SEND
                for msg in messages:
                    if not ensure_live():
                        raise RuntimeError('no FTMS telemetry yet: stopping')
                    await writer.write(SYNC_RX, msg, at())
                    await asyncio.sleep(0.15)
                session_open = True
                if step.get('inclineX100') is not None:
                    incline_now = step['inclineX100']
                if step.get('gear') is not None:
                    gear_now = step['gear']
                segments.append({'t': step_started, 'label': label, **step})
                last = ftms[-1] if ftms else {}
                print(f'  t={at():5.1f}s  {label:16}  now {last.get("powerWatts", "—")} W '
                      f'{last.get("cadenceRpm", "—")} rpm', flush=True)
        except Exception as exc:
            notes.append(f'aborted: {type(exc).__name__}: {exc}')
            print('ABORT:', exc, flush=True)
        finally:
            if session_open and client.is_connected:
                try:  # leave the trainer in the known neutral state
                    for msg in restore_messages(rider_kg, bike_kg):
                        await writer.write(SYNC_RX, msg, at())
                    notes.append('left in gear 12 at 0.4 %')
                except Exception as exc:
                    notes.append(f'could not restore neutral: {exc}')
            for uuid in (INDOOR_BIKE_DATA, ASYNC, SYNC_TX):
                if uuid in available and client.is_connected:
                    try:
                        await client.stop_notify(uuid)
                    except Exception:
                        pass
    summary = summarise(segments, riding, ftms, events)
    return {'trainer': item.to_json(), 'riderKg': rider_kg, 'bikeKg': bike_kg, 'notes': notes,
            'findings': findings(summary), 'sent': writer.sent, 'segments': summary,
            'zwiftEvents': events, 'ftms': ftms}


def main():
    parser = argparse.ArgumentParser(description='Step 5: a gentle grade ramp 0.4-1.5 % (supervised).')
    parser.add_argument('--confirm', action='store_true', help='required: you are on the bike, pedalling gently')
    parser.add_argument('--rider-kg', type=float)
    parser.add_argument('--bike-kg', type=float)
    parser.add_argument('--out')
    args = parser.parse_args()
    if not args.confirm:
        print('This test CHANGES the trainer resistance (grades 0-1.5 %, gears 12-13). Read the guide first;')
        print('run again with --confirm when you are on the bike.')
        return 2
    rider_kg, bike_kg = weights(args)
    if not (30 <= rider_kg <= 250 and 3 <= bike_kg <= 40):
        raise SystemExit('weights out of range')
    print(f'Weights: rider {rider_kg:g} kg, bike {bike_kg:g} kg. Ctrl+C stops safely (0.4 %, gear 12).', flush=True)
    result = asyncio.run(run(rider_kg, bike_kg))
    result['testedAtUtc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    from coach.app.paths import diagnostics_dir
    folder = Path(args.out) if args.out else diagnostics_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('zwift_grade_test_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '.json')
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    if 'error' in result:
        print('ERROR:', result['error'])
    else:
        print(f'{"segment":20} {"W":>6} {"W 5s":>6} {"rpm":>6} {"km/h":>6}  answers')
        for s in result['segments']:
            answers = ','.join(f'{r.get("dataId")}' for r in s['hubResponses']) or '—'
            print(f'{s["label"]:20} {s["ftmsPowerW"] or "—":>6} {s["ftmsPowerLast5sW"] or "—":>6} '
                  f'{s["ftmsCadenceRpm"] or "—":>6} {s["ftmsSpeedKph"] or "—":>6}  {answers}'
                  f'{"  SKIPPED " + s["skipped"] if s.get("skipped") else ""}')
        f = result['findings']
        print(f'Gear confirmed at 0 %: {f["gearsConfirmedAtZeroGrade"]} · answers to 512: {f["answersTo512Count"]}')
        for note in result['notes']:
            print('note:', note)
    print(f'Saved: {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
