"""Step 2 of trainer control: start the trainer's native Zwift channel WITHOUT changing gears or grade.

What it sends (and nothing else, enforced by GuardedWriter):
  1. "RideOn 02 01" to the Zwift SyncRx characteristic (…0003)
  2. "41 08 05"     to the same characteristic
These open the session the trainer uses for native virtual shifting (Serpentine, Incyclist). No gear,
no grade, no power target, no FTMS control request is sent.

What it records for --seconds (default 60) into diagnostics/zwift_hub_probe_*.json:
  - every notification of the Zwift channel (Async …0002, SyncTx …0004), decoded where possible,
  - FTMS Indoor Bike Data at the same time (read-only), to compare power/cadence with the Zwift RidingData.

Pedal gently during the test. Requires --confirm.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script from anywhere

from coach.bluetooth.discovery import TRAINER, classify, scan  # noqa: E402
from coach.devices.wahoo import INDOOR_BIKE_DATA, parse_indoor_bike_data  # noqa: E402
from coach.devices.zwift_hub import (ASYNC, RIDE_ON_TRAINER, SYNC_RX, SYNC_TX, TRAINER_HANDSHAKE_2,  # noqa: E402
                                     decode_riding_data, describe)

ALLOWED_WRITES = {(SYNC_RX, RIDE_ON_TRAINER), (SYNC_RX, TRAINER_HANDSHAKE_2)}


class GuardedWriter:
    """The only way this tool writes: exactly the two handshake messages, to SyncRx, nothing else."""
    def __init__(self, client, allowed=ALLOWED_WRITES):
        self.client = client
        self.allowed = set(allowed)
        self.sent = []

    async def write(self, uuid, data: bytes):
        if (uuid.lower(), bytes(data)) not in self.allowed:
            raise PermissionError(f'write refused by the probe: {uuid} {bytes(data).hex()}')
        await self.client.write_gatt_char(uuid, data, response=False)
        self.sent.append((uuid, bytes(data).hex()))


def summarise(events, ftms):
    riding = [e for e in events if e['decoded'].get('type') == 'RidingData']
    first = riding[0]['t'] if riding else None

    def mean(rows, key):
        values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(sum(values) / len(values), 1) if values else None
    types = {}
    for e in events:
        types[e['decoded'].get('type')] = types.get(e['decoded'].get('type'), 0) + 1
    return {
        'zwiftMessagesByType': types,
        'ridingDataCount': len(riding),
        'firstRidingDataAfterSeconds': first,
        'zwiftMean': {k: mean([r['decoded'] for r in riding], k) for k in ('powerWatts', 'cadenceRpm', 'speedKph')},
        'ftmsCount': len(ftms),
        'ftmsMean': {k: mean([f['parsed'] for f in ftms], k) for k in ('powerWatts', 'cadenceRpm', 'speedKph')},
    }


async def probe(seconds: float):
    from bleak import BleakClient
    adverts = await scan(12)
    trainers = [(classify(a), a) for a in adverts.values() if classify(a).kind == TRAINER]
    if not trainers:
        return {'error': 'No trainer found (pedal a little to wake it; close Zwift/Wahoo apps).'}
    item, _adv = max(trainers, key=lambda pair: pair[1].rssi or -999)
    events, ftms = [], []
    started = monotonic()

    def at():
        return round(monotonic() - started, 3)

    def on_zwift(channel):
        def callback(_sender, data):
            raw = bytes(data)
            events.append({'t': at(), 'channel': channel, 'hex': raw.hex(), 'decoded': describe(raw)})
        return callback

    def on_ftms(_sender, data):
        raw = bytes(data)
        try:
            ftms.append({'t': at(), 'parsed': parse_indoor_bike_data(raw)})
        except ValueError as exc:
            ftms.append({'t': at(), 'error': str(exc), 'hex': raw.hex()})

    print(f'Connecting to {item.name} {item.address} ...', flush=True)
    async with BleakClient(item.address, timeout=20) as client:
        available = {c.uuid.lower() for s in client.services for c in s.characteristics}
        missing = [u for u in (ASYNC, SYNC_RX) if u not in available]
        if missing:
            return {'error': f'Zwift channel not available: missing {missing}', 'trainer': item.to_json()}
        writer = GuardedWriter(client)
        if INDOOR_BIKE_DATA in available:
            await client.start_notify(INDOOR_BIKE_DATA, on_ftms)
        await client.start_notify(ASYNC, on_zwift('async'))
        if SYNC_TX in available:
            await client.start_notify(SYNC_TX, on_zwift('syncTx'))
        started = monotonic()
        print('Sending RideOn 02 01 ...', flush=True)
        await writer.write(SYNC_RX, RIDE_ON_TRAINER)
        await asyncio.sleep(0.3)
        print('Sending 41 08 05 ...', flush=True)
        await writer.write(SYNC_RX, TRAINER_HANDSHAKE_2)
        print(f'Listening {seconds:g} s. Pedal gently. Ctrl+C stops early.', flush=True)
        last_print = 0.0
        try:
            while at() < seconds:
                await asyncio.sleep(0.25)
                if at() - last_print >= 5:
                    last_print = at()
                    riding = [e for e in events if e['decoded'].get('type') == 'RidingData']
                    latest = riding[-1]['decoded'] if riding else {}
                    print(f'  t={at():5.1f}s  zwift messages={len(events)}  riding data={len(riding)}  '
                          f'last: {latest.get("powerWatts", "—")} W {latest.get("cadenceRpm", "—")} rpm', flush=True)
        except asyncio.CancelledError:
            pass
        for uuid in (INDOOR_BIKE_DATA, ASYNC, SYNC_TX):
            if uuid in available and client.is_connected:
                try:
                    await client.stop_notify(uuid)
                except Exception:
                    pass
        return {'trainer': item.to_json(), 'sent': writer.sent, 'seconds': seconds,
                'summary': summarise(events, ftms), 'zwiftEvents': events, 'ftms': ftms}


def main():
    parser = argparse.ArgumentParser(description='Step 2: open the trainer Zwift channel (no gears, no grade).')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--confirm', action='store_true', help='required: you are on the bike or next to it')
    parser.add_argument('--out', default=None)
    args = parser.parse_args()
    if not args.confirm:
        print('This test writes the Zwift handshake to the trainer (no gears, no grade).')
        print('Run it again with --confirm when you are ready, pedalling gently.')
        return 2
    from coach.app.paths import diagnostics_dir
    try:
        result = asyncio.run(probe(args.seconds))
    except KeyboardInterrupt:
        result = {'error': 'interrupted'}
    result['probedAtUtc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    folder = Path(args.out) if args.out else diagnostics_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('zwift_hub_probe_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '.json')
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    if 'error' in result:
        print('ERROR:', result['error'])
    else:
        s = result['summary']
        print('RidingData messages:', s['ridingDataCount'], ' first after', s['firstRidingDataAfterSeconds'], 's')
        print('Zwift mean :', s['zwiftMean'])
        print('FTMS  mean :', s['ftmsMean'])
        print('Message types:', s['zwiftMessagesByType'])
    print(f'Saved: {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
