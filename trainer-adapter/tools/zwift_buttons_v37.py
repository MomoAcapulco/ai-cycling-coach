#!/usr/bin/env python3
"""Read-only Zwift controller button decoder: live BLE or offline JSONL replay."""
import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

NOTIFY = '00000002-19ca-4651-86e5-fa29dcdd09d1'
WRITE = '00000003-19ca-4651-86e5-fa29dcdd09d1'
HANDSHAKE = b'RideOn'
LEFT = 'FA4E0000-0000-4000-8000-C4F41263D137'
RIGHT = 'FA4E0000-0000-4000-8000-5A32B13A42DE'
# Button maps corrected using direct live testing on 2026-11-11.
# LEFT: UP/DOWN swapped from initial ordered capture.
# RIGHT: PLUS/Y/A/B remapped in v3.7.1; Z and B swapped in v3.7.2.
BUTTON_MASKS = {
    'left': {'MINUS': 1 << 9, 'UP': 1 << 1, 'DOWN': 1 << 3,
             'LEFT': 1 << 0, 'RIGHT': 1 << 2},
    'right': {'PLUS': 1 << 13, 'Z': 1 << 8, 'B': 1 << 5,
              'A': 1 << 4, 'Y': 1 << 6},
}

def decode_packet(raw: bytes, side: str):
    """Returns pressed buttons for known type-35 packets; None for others.

    Data observed: 23 08 xx xx xx xx 0f. Position 0 is base byte[2] bit 0.
    Unknown bits are reported; the decoder never invents button labels.
    """
    if len(raw) != 7 or raw[:2] != b'\x23\x08':
        return None
    data = int.from_bytes(raw[2:], 'little')
    released = int.from_bytes(b'\xff\xff\xff\xff\x0f', 'little')
    active = released & ~data
    mapping = BUTTON_MASKS[side]
    buttons = [name for name, bit in mapping.items() if active & bit]
    known_mask = 0
    for bit in mapping.values():
        known_mask |= bit
    return buttons, active & ~known_mask

class ButtonTracker:
    def __init__(self, side):
        self.side = side
        self.held = set()
        self.count = Counter()

    def feed(self, raw):
        data = decode_packet(raw, self.side)
        if data is None:
            return []
        pressed, unknown = data
        current = set(pressed)
        pressed_now = current - self.held
        released_now = self.held - current
        self.held = current
        events = ([{'event': 'BUTTON_DOWN', 'button': b} for b in sorted(pressed_now)]
                  + [{'event': 'BUTTON_UP', 'button': b} for b in sorted(released_now)])
        for event in events:
            if event['event'] == 'BUTTON_DOWN':
                self.count[event['button']] += 1
        if unknown:
            events.append({'event': 'UNKNOWN_MASK', 'mask': hex(unknown)})
        return events

def emit(events, timestamp=None):
    for event in events:
        if timestamp:
            event['timestamp'] = timestamp
        print(json.dumps(event, ensure_ascii=False), flush=True)

def offline(path, side):
    tracker = ButtonTracker(side)
    packets = 0
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        obj = json.loads(line)
        if obj.get('event') != 'BLE_NOTIFICATION' or obj.get('characteristic', '').lower() != NOTIFY:
            continue
        raw = bytes.fromhex(obj['hex'])
        if decode_packet(raw, side) is None:
            continue
        packets += 1
        emit(tracker.feed(raw), obj.get('utc'))
    print(f'Packets: {packets}; Button downs: {dict(tracker.count)}')

async def live(side, device_id, seconds):
    from bleak import BleakScanner, BleakClient
    devices = await BleakScanner.discover(timeout=15)
    device = next((d for d in devices if d.address.upper() == device_id.upper()), None)
    if device is None:
        raise RuntimeError('Mando no encontrado. Despiértalo y cierra Zwift.')
    tracker = ButtonTracker(side)
    log = Path('recordings')
    log.mkdir(exist_ok=True)
    filename = log / f'zwift_buttons_{side}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jsonl'
    with filename.open('w', encoding='utf-8') as output:
        def notification(sender, payload):
            raw = bytes(payload)
            timestamp = datetime.now(timezone.utc).isoformat()
            output.write(json.dumps({'utc': timestamp, 'hex': raw.hex(), 'side': side}) + '\n')
            output.flush()
            emit(tracker.feed(raw), timestamp)

        async with BleakClient(device) as client:
            await client.start_notify(NOTIFY, notification)
            await client.write_gatt_char(WRITE, HANDSHAKE, response=False)
            print(f'Conectado: {side}. Pulsa cada botón una vez; CTRL+C para terminar.')
            print(f'Registro: {filename}')
            try:
                await asyncio.sleep(seconds)
            finally:
                await client.stop_notify(NOTIFY)
    print('Pulsaciones identificadas:', dict(tracker.count))


def main():
    p = argparse.ArgumentParser(description='Zwift controller button decoder (read-only)')
    p.add_argument('--side', choices=['left', 'right'], required=True)
    p.add_argument('--file', help='JSONL original de la v3.6 para reproducir offline')
    p.add_argument('--seconds', type=int, default=60)
    p.add_argument('--device-id', help='UUID del mando (solo para prueba local)')
    args = p.parse_args()
    if args.file:
        offline(args.file, args.side)
    else:
        asyncio.run(live(args.side, args.device_id or (LEFT if args.side == 'left' else RIGHT), args.seconds))

if __name__ == '__main__':
    main()
