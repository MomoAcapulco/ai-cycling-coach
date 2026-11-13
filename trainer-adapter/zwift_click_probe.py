"""Read-only Zwift Click BLE probe. No writes to controller or trainer.

Collects GATT metadata and notifications with UTC timestamps for protocol analysis.
Controller protocol may require pairing/handshake; raw bytes are not assumed to
represent button presses until verified against a labeled test sequence.
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner

ZWIFT_SERVICE = '00000001-19ca-4651-86e5-fa29dcdd09d1'
BATTERY_LEVEL = '00002a19-0000-1000-8000-00805f9b34fb'


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def write_event(file, event, **fields):
    record = {'utc': stamp(), 'event': event, **fields}
    file.write(json.dumps(record, ensure_ascii=False) + '\n')
    file.flush()
    print(json.dumps(record, ensure_ascii=False), flush=True)


async def run(seconds, folder, device_id):
    folder.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = folder / f'zwift_click_raw_{name}.jsonl'
    print(f'Captura SOLO LECTURA: {out}')
    print('Cierra Zwift antes de ejecutar esta prueba.')
    print('Buscando Zwift Click durante 15 segundos...')
    devices = await BleakScanner.discover(timeout=15)
    matches = [d for d in devices if d.name and 'ZWIFT CLICK' in d.name.upper()]
    for i, d in enumerate(matches, 1):
        print(f'{i}. {d.name}: {d.address}')
    if device_id:
        matches = [d for d in devices if d.address == device_id]
    if not matches:
        print('No se ha encontrado el mando. Enciéndelo y cierra Zwift.')
        return
    if len(matches) > 1 and not device_id:
        print('Se detectaron varios mandos: indica --device-id con uno de los IDs de arriba.')
        return
    device = matches[0]
    with out.open('w', encoding='utf-8') as f:
        write_event(f, 'DEVICE_FOUND', name=device.name, deviceId=device.address)
        try:
            async with BleakClient(device, timeout=20) as client:
                write_event(f, 'CONNECTED', deviceId=device.address)
                characteristic_uuids = []
                for service in client.services:
                    write_event(f, 'SERVICE', uuid=service.uuid)
                    for ch in service.characteristics:
                        write_event(f, 'CHARACTERISTIC', service=service.uuid,
                                    uuid=ch.uuid, properties=list(ch.properties))
                        if 'notify' in ch.properties or 'indicate' in ch.properties:
                            characteristic_uuids.append(ch.uuid)
                try:
                    if BATTERY_LEVEL in [ch.uuid.lower() for srv in client.services for ch in srv.characteristics]:
                        value = await client.read_gatt_char(BATTERY_LEVEL)
                        write_event(f, 'BATTERY', percent=int(value[0]) if value else None)
                except Exception as exc:
                    write_event(f, 'BATTERY_READ_ERROR', detail=str(exc))

                registered = []
                def callback(sender, value):
                    write_event(f, 'NOTIFICATION', characteristic=str(sender.uuid),
                                rawHex=bytes(value).hex(), byteLength=len(value))
                for uuid in characteristic_uuids:
                    # Only listen on the proprietary Zwift service. Ignore unrelated
                    # notifications that could be noisy or sensitive.
                    belongs = any(s.uuid.lower() == ZWIFT_SERVICE and
                                  any(c.uuid.lower() == uuid.lower() for c in s.characteristics)
                                  for s in client.services)
                    if not belongs:
                        continue
                    try:
                        await client.start_notify(uuid, callback)
                        registered.append(uuid)
                        write_event(f, 'SUBSCRIBED', characteristic=uuid)
                    except Exception as exc:
                        write_event(f, 'SUBSCRIBE_ERROR', characteristic=uuid, detail=str(exc))
                print(f'Pulsa alternativamente (+), (-), (+), (-), luego no pulses nada. Captura: {seconds}s.')
                await asyncio.sleep(seconds)
                for uuid in registered:
                    try:
                        await client.stop_notify(uuid)
                    except Exception:
                        pass
                write_event(f, 'CAPTURE_FINISHED', durationSeconds=seconds)
        except Exception as exc:
            write_event(f, 'CONNECTION_ERROR', detail=str(exc))
    print(f'Archivo guardado: {out}')
    print('Si aparecen SERVICE pero no NOTIFICATION, puede faltar el handshake de Zwift.')


def main():
    parser = argparse.ArgumentParser(description='Inspección BLE de Zwift Click sin escribir ni cambiar resistencia')
    parser.add_argument('--seconds', type=int, default=45)
    parser.add_argument('--device-id', help='UUID exacto visto por Bleak en Mac')
    parser.add_argument('--output', default=str(Path(__file__).resolve().parent / 'recordings'))
    args = parser.parse_args()
    if not 5 <= args.seconds <= 300:
        parser.error('--seconds debe estar entre 5 y 300')
    asyncio.run(run(args.seconds, Path(args.output), args.device_id))


if __name__ == '__main__':
    main()
