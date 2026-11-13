"""Step 1 of trainer control: READ-ONLY inventory of the trainer.

Finds the trainer (scan), connects, and saves trainer_probe_*.json in the project's diagnostics/
folder (so it can be shared):
- its advertisement (name, services, manufacturer data),
- every GATT service and characteristic with its properties,
- the value of every READABLE characteristic.

It sends nothing to the trainer: no writes, no subscriptions, no control requests. Reading a
characteristic does not change resistance. The answer we need: does the trainer expose the Zwift
service (0xFC82 or 00000001-19ca-...) that the native virtual-shifting protocol uses?

Usage:  python tools/trainer_probe.py [--seconds 15]
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script from anywhere

from coach.bluetooth.discovery import (FTMS, TRAINER, ZWIFT_RIDE_SERVICE, ZWIFT_SERVICE, Advert, classify, scan)

KNOWN = {
    FTMS: 'Fitness Machine (FTMS)',
    '00001818-0000-1000-8000-00805f9b34fb': 'Cycling Power',
    '0000180d-0000-1000-8000-00805f9b34fb': 'Heart Rate',
    '0000180a-0000-1000-8000-00805f9b34fb': 'Device Information',
    '0000180f-0000-1000-8000-00805f9b34fb': 'Battery',
    'a026ee0b-0a7d-4ab3-97fa-f1500f9feb8b': 'Wahoo trainer (proprietary)',
    ZWIFT_SERVICE: 'Zwift (19ca)',
    ZWIFT_RIDE_SERVICE: 'Zwift (FC82)',
}
DEVICE_INFO_TEXT = {
    '00002a29-0000-1000-8000-00805f9b34fb': 'manufacturer',
    '00002a24-0000-1000-8000-00805f9b34fb': 'model',
    '00002a26-0000-1000-8000-00805f9b34fb': 'firmware',
    '00002a27-0000-1000-8000-00805f9b34fb': 'hardware',
    '00002a28-0000-1000-8000-00805f9b34fb': 'software',
}


def as_text(raw: bytes):
    try:
        text = raw.decode('utf-8').strip('\x00').strip()
        return text if text and text.isprintable() else None
    except UnicodeDecodeError:
        return None


async def inventory(client) -> dict:
    """Services, characteristics and readable values of a connected client. Reads only."""
    services = []
    zwift = False
    for service in client.services:
        uuid = service.uuid.lower()
        zwift = zwift or uuid in (ZWIFT_SERVICE, ZWIFT_RIDE_SERVICE)
        entry = {'uuid': uuid, 'name': KNOWN.get(uuid), 'characteristics': []}
        for char in service.characteristics:
            item = {'uuid': char.uuid.lower(), 'properties': sorted(char.properties)}
            if 'read' in char.properties:
                try:
                    raw = bytes(await client.read_gatt_char(char.uuid))
                    item['hex'] = raw.hex()
                    text = as_text(raw)
                    if text:
                        item['text'] = text
                except Exception as exc:  # some characteristics refuse reads; record why
                    item['readError'] = f'{type(exc).__name__}: {exc}'[:160]
            entry['characteristics'].append(item)
        services.append(entry)
    info = {label: c.get('text') for s in services for c in s['characteristics']
            for uuid, label in DEVICE_INFO_TEXT.items() if c['uuid'] == uuid and c.get('text')}
    return {'deviceInformation': info, 'hasZwiftService': zwift, 'services': services}


async def probe(seconds: float):
    from bleak import BleakClient
    adverts = await scan(seconds)
    trainers = [(classify(a), a) for a in adverts.values() if classify(a).kind == TRAINER]
    if not trainers:
        return {'error': 'No trainer found: is it powered and awake (pedal a little), and Zwift/Wahoo apps closed?',
                'seen': len(adverts)}
    if len(trainers) > 1:
        print('Several trainers found; using the strongest signal:', [t.name for t, _ in trainers], flush=True)
    item, advert = max(trainers, key=lambda pair: pair[1].rssi or -999)
    print(f'Connecting (read-only) to {item.name} {item.address} ...', flush=True)
    async with BleakClient(item.address, timeout=20) as client:
        details = await inventory(client)
    advertised_zwift = any(u in (ZWIFT_SERVICE, ZWIFT_RIDE_SERVICE) for u in advert.service_uuids)
    return {'trainer': item.to_json(), 'advert': advert.to_json(),
            'advertisesZwiftService': advertised_zwift, **details}


def main():
    parser = argparse.ArgumentParser(description='Read-only inventory of the trainer (step 1 of trainer control).')
    parser.add_argument('--seconds', type=float, default=15)
    from coach.app.paths import diagnostics_dir
    parser.add_argument('--out', default=str(diagnostics_dir()))
    args = parser.parse_args()
    print(f'Scanning {args.seconds:g} s for the trainer... (pedal a little so it wakes up)', flush=True)
    result = asyncio.run(probe(args.seconds))
    result['probedAtUtc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    folder = Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('trainer_probe_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '.json')
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    if 'error' in result:
        print('ERROR:', result['error'])
    else:
        info = result['deviceInformation']
        print(f"Trainer: {result['trainer']['name']}  model={info.get('model')}  firmware={info.get('firmware')}")
        for service in result['services']:
            print(f"  service {service['uuid']}  {service['name'] or ''}  ({len(service['characteristics'])} characteristics)")
        print('Zwift service exposed:', 'YES' if result['hasZwiftService'] else 'NO',
              '(advertised)' if result['advertisesZwiftService'] else '')
    print(f'Saved: {path}')


if __name__ == '__main__':
    main()
