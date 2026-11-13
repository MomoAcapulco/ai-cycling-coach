"""Read-only Bluetooth Heart Rate Measurement, including RR intervals if emitted."""
import asyncio

HEART_RATE_MEASUREMENT = '00002a37-0000-1000-8000-00805f9b34fb'


def parse_heart_rate(data: bytes) -> dict:
    if len(data) < 2:
        raise ValueError('Short heart-rate notification')
    flags = data[0]
    pos = 1
    if flags & 1:
        if len(data) < 3:
            raise ValueError('Short uint16 heart-rate notification')
        bpm = int.from_bytes(data[1:3], 'little')
        pos = 3
    else:
        bpm = data[1]
        pos = 2
    result = {'heartRateBpm': bpm, 'heartRateFlags': flags}
    if flags & 8:
        if len(data) < pos + 2:
            raise ValueError('Truncated energy expended')
        result['energyExpendedKj'] = int.from_bytes(data[pos:pos + 2], 'little')
        pos += 2
    if flags & 16:
        if (len(data) - pos) % 2:
            raise ValueError('Truncated RR interval')
        result['rrIntervalsMs'] = [round(int.from_bytes(data[i:i + 2], 'little') * 1000 / 1024, 2)
                                   for i in range(pos, len(data), 2)]
    return result


async def hr_worker(store, stop_event, device_name='HR50', device_id=None, capture=None):
    from bleak import BleakClient, BleakScanner
    delay = 2
    while not stop_event.is_set():
        try:
            store.waiting('Buscando pulsómetro BLE...')
            if device_id:
                device = await BleakScanner.find_device_by_address(device_id, timeout=12)
            else:
                device = await BleakScanner.find_device_by_filter(
                    lambda d, a: bool(d.name and device_name.upper() in d.name.upper()), timeout=12)
            if device is None:
                raise RuntimeError('No se encuentra HR50; activa la banda')
            async with BleakClient(device, timeout=20) as client:
                if HEART_RATE_MEASUREMENT not in {c.uuid.lower() for s in client.services for c in s.characteristics}:
                    raise RuntimeError('Sensor no anuncia Heart Rate Measurement')
                store.waiting(f'Conectado a {device.name}; esperando pulso...')

                def on_measurement(_sender, data):
                    raw = bytes(data)
                    try:
                        decoded = parse_heart_rate(raw)
                        store.update(decoded)
                        if capture:
                            capture.event('heart_rate', raw, decoded)
                    except ValueError as exc:
                        store.note_error(f'HR inválido: {exc}')
                        if capture:
                            capture.event('heart_rate_invalid', raw, {'error': str(exc)})

                await client.start_notify(HEART_RATE_MEASUREMENT, on_measurement)
                delay = 2
                while client.is_connected and not stop_event.is_set():
                    await asyncio.sleep(.5)
                if client.is_connected:
                    await client.stop_notify(HEART_RATE_MEASUREMENT)
                store.waiting('Pulsómetro desconectado; reconectando...')
        except Exception as exc:
            store.waiting(f'HR BLE: {type(exc).__name__}: {exc}')
        if not stop_event.is_set():
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)
