#!/usr/bin/env python3
"""Zwift Click/Play diagnostic. No keyboard events, trainer commands, or network calls.

Based on protocol details documented by ajchellew/zwiftplay and
jat255/zwift_click_handling (MIT). Handshake variant may not work on Zwift Play.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ASYNC_UUID = '00000002-19ca-4651-86e5-fa29dcdd09d1'
SYNC_RX_UUID = '00000003-19ca-4651-86e5-fa29dcdd09d1'
SYNC_TX_UUID = '00000004-19ca-4651-86e5-fa29dcdd09d1'
BATTERY_UUID = '00002a19-0000-1000-8000-00805f9b34fb'
EXTRA_UUIDS = ('00000100-19ca-4651-86e5-fa29dcdd09d1',
               '00000101-19ca-4651-86e5-fa29dcdd09d1',
               '00000102-19ca-4651-86e5-fa29dcdd09d1')


def parse_varint(buf, at):
    value = 0
    shift = 0
    while at < len(buf) and shift <= 63:
        b = buf[at]
        at += 1
        value |= (b & 127) << shift
        if not b & 128:
            return value, at
        shift += 7
    raise ValueError('Varint incompleto o demasiado grande')


def protobuf_numbers(buf):
    """Only wire types 0,1,2,5. Diagnostic: does not assume field meanings."""
    fields = {}
    at = 0
    while at < len(buf):
        key, at = parse_varint(buf, at)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError('Campo protobuf 0 inválido')
        if wire == 0:
            value, at = parse_varint(buf, at)
        elif wire == 1:
            if at + 8 > len(buf): raise ValueError('fixed64 truncado')
            value = buf[at:at+8].hex(); at += 8
        elif wire == 2:
            length, at = parse_varint(buf, at)
            if at + length > len(buf): raise ValueError('bytes truncados')
            value = buf[at:at+length].hex(); at += length
        elif wire == 5:
            if at + 4 > len(buf): raise ValueError('fixed32 truncado')
            value = buf[at:at+4].hex(); at += 4
        else:
            raise ValueError(f'wire type {wire} no soportado')
        fields.setdefault(str(field), []).append(value)
    return fields


def decode_plain_notification(data):
    """Unencrypted RideOn mode: first byte type (55=Click, 7=Play candidate)."""
    if not data:
        return None
    msg_type = data[0]
    if msg_type not in (7, 21, 25, 55):
        return {'type': msg_type, 'decoded': None}
    try:
        fields = protobuf_numbers(data[1:])
        decoded = {'type': msg_type, 'fields': fields}
        # Known mapping ONLY on classic 2-button Click (type 55).
        if msg_type == 55 and '1' in fields and '2' in fields:
            p, m = fields['1'][-1], fields['2'][-1]
            if p in (0, 1) and m in (0, 1):
                decoded['classicClickState'] = {'plusPressed': p == 0,
                                                'minusPressed': m == 0}
        return decoded
    except ValueError as exc:
        return {'type': msg_type, 'error': str(exc)}


async def run(args):
    from bleak import BleakClient, BleakScanner
    print('Buscando dispositivos Zwift Click/Play...')
    discovered = await BleakScanner.discover(timeout=15)
    devices = [d for d in discovered if d.name and ('Zwift Click' in d.name or 'Zwift Play' in d.name)]
    for device in devices:
        print(' -', device.name, device.address)
    target = next((d for d in devices if d.address.lower() == (args.device_id or '').lower()), None)
    if not target and len(devices) == 1 and not args.device_id:
        target = devices[0]
    if not target:
        print('Selecciona un mando con --device-id usando uno de los identificadores anteriores.')
        return 2

    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    suffix = target.address.replace('-', '')[-8:]
    output_path = folder / f'zwift_controller_v36_{stamp}_{suffix}.jsonl'
    print('Conectando:', target.name, target.address)
    print('Registro:', output_path)

    with output_path.open('w', encoding='utf-8') as out:
        def log(event, **fields):
            row = {'utc': datetime.now(timezone.utc).isoformat(), 'event': event,
                   'deviceId': target.address, **fields}
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
            out.flush()
            if event in ('CONNECTED', 'HANDSHAKE_SENT', 'BUTTON', 'BUTTON_STATE',
                         'BLE_NOTIFICATION', 'ERROR', 'FINISHED'):
                print(event, {k:v for k,v in fields.items() if k not in ('hex',)})

        try:
            async with BleakClient(target, timeout=20) as client:
                log('CONNECTED')
                chars = {c.uuid.lower(): c for s in client.services for c in s.characteristics}
                for uuid in (ASYNC_UUID, SYNC_RX_UUID, SYNC_TX_UUID, BATTERY_UUID):
                    log('CAPABILITY', uuid=uuid, properties=chars[uuid].properties if uuid in chars else None)
                if SYNC_RX_UUID not in chars or ASYNC_UUID not in chars:
                    log('ERROR', detail='El mando no anuncia características de control esperadas')
                    return 3
                last_state = None
                seen = 0
                def notify(characteristic, payload):
                    nonlocal last_state, seen
                    seen += 1
                    data = bytes(payload)
                    uuid = characteristic.uuid.lower()
                    decoded = decode_plain_notification(data) if uuid == ASYNC_UUID else None
                    log('BLE_NOTIFICATION', characteristic=uuid, hex=data.hex(), decoded=decoded)
                    state = (decoded or {}).get('classicClickState')
                    if state is not None and state != last_state:
                        log('BUTTON_STATE', **state)
                        if last_state is not None:
                            for b in ('plusPressed', 'minusPressed'):
                                if state[b] != last_state[b]:
                                    log('BUTTON', button=b.replace('Pressed', '').upper(),
                                        action='PRESSED' if state[b] else 'RELEASED')
                        last_state = state
                subscribed = []
                for uuid in (ASYNC_UUID, SYNC_TX_UUID, BATTERY_UUID):
                    if uuid in chars and ('notify' in chars[uuid].properties or 'indicate' in chars[uuid].properties):
                        await client.start_notify(uuid, notify)
                        subscribed.append(uuid)
                        log('SUBSCRIBED', characteristic=uuid)
                if args.extra:
                    for uuid in EXTRA_UUIDS:
                        if uuid in chars and 'notify' in chars[uuid].properties:
                            await client.start_notify(uuid, notify)
                            subscribed.append(uuid)
                            log('SUBSCRIBED', characteristic=uuid)
                if not args.no_handshake:
                    # Reference project demonstrates unencrypted handshake for classic Click.
                    # Some Play firmwares might require encrypted RideOn ECDH session instead.
                    await client.write_gatt_char(SYNC_RX_UUID, b'RideOn', response=False)
                    log('HANDSHAKE_SENT', variant='RideOn-plain', commandHex=b'RideOn'.hex())
                print(f'Pulsa los botones uno a uno durante {args.seconds} segundos...')
                await asyncio.sleep(args.seconds)
                for uuid in reversed(subscribed):
                    if client.is_connected:
                        await client.stop_notify(uuid)
                log('FINISHED', notifications=seen, encryptedHandshake=False,
                    caveat='Decodificación Play no validada')
            return 0
        except Exception as exc:
            log('ERROR', detail=f'{type(exc).__name__}: {exc}')
            return 1


def main():
    parser = argparse.ArgumentParser(description='Captura BLE Zwift Click / Play, SIN controlar rodillo')
    parser.add_argument('--device-id', default=None)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--output-dir', default='recordings')
    parser.add_argument('--no-handshake', action='store_true')
    parser.add_argument('--extra', action='store_true', help='Suscribir características propietarias adicionales')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('--seconds debe estar entre 1 y 600')
    return asyncio.run(run(args))

if __name__ == '__main__':
    sys.exit(main())
