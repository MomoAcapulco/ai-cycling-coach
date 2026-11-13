"""Wahoo KICKR BLE reader. Optional explicitly armed, capped FTMS grade test."""
import asyncio
import struct
from coach.bluetooth.ble_runtime import sleep_unless_stopped
from coach.bluetooth.device_finder import Ambiguous, find_for_role
from coach.devices.gear_shifter import SafeZwiftWriter
from coach.devices.zwift_hub import ASYNC as ZWIFT_ASYNC, SYNC_RX as ZWIFT_SYNC_RX, SYNC_TX as ZWIFT_SYNC_TX
from coach.session.diagnostics import save_capabilities
from coach.devices.control import CONTROL_POINT, FEATURE, FtmsController, ControlEventLog, simulation_supported, run_experiment_tick

INDOOR_BIKE_DATA = '00002ad2-0000-1000-8000-00805f9b34fb'
CYCLING_POWER_MEASUREMENT = '00002a63-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_FEATURE = '00002acc-0000-1000-8000-00805f9b34fb'
CYCLING_POWER_FEATURE = '00002a65-0000-1000-8000-00805f9b34fb'
SUPPORTED_POWER_RANGE = '00002ad8-0000-1000-8000-00805f9b34fb'
SUPPORTED_INCLINATION_RANGE = '00002ad5-0000-1000-8000-00805f9b34fb'
SUPPORTED_RESISTANCE_RANGE = '00002ad6-0000-1000-8000-00805f9b34fb'
TRAINING_STATUS = '00002ad3-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_STATUS = '00002ada-0000-1000-8000-00805f9b34fb'


def parse_indoor_bike_data(data: bytes) -> dict:
    """Parse all standard Indoor Bike Data optional fields with flag-aware offsets."""
    if len(data) < 2:
        raise ValueError('FTMS packet lacks flags')
    flags = int.from_bytes(data[:2], 'little')
    pos = 2
    result = {'ftmsFlags': flags}

    def read(fmt):
        nonlocal pos
        size = struct.calcsize(fmt)
        if pos + size > len(data):
            raise ValueError(f'Truncated FTMS packet at byte {pos}')
        value = struct.unpack_from(fmt, data, pos)[0]
        pos += size
        return value

    if not flags & 1:
        result['speedKph'] = read('<H') / 100
    if flags & (1 << 1):
        result['averageSpeedKph'] = read('<H') / 100
    if flags & (1 << 2):
        result['cadenceRpm'] = read('<H') / 2
    if flags & (1 << 3):
        result['averageCadenceRpm'] = read('<H') / 2
    if flags & (1 << 4):
        if pos + 3 > len(data):
            raise ValueError('Truncated total distance')
        result['totalDistanceMeters'] = int.from_bytes(data[pos:pos + 3], 'little')
        pos += 3
    if flags & (1 << 5):
        result['resistanceLevel'] = read('<h')
    if flags & (1 << 6):
        result['powerWatts'] = read('<h')
    if flags & (1 << 7):
        result['averagePowerWatts'] = read('<h')
    if flags & (1 << 8):
        result['totalEnergyKcal'] = read('<H')
        result['energyPerHourKcal'] = read('<H')
        result['energyPerMinuteKcal'] = read('<B')
    if flags & (1 << 9):
        result['ftmsHeartRateBpm'] = read('<B')
    if flags & (1 << 10):
        result['metabolicEquivalent'] = read('<B') / 10
    if flags & (1 << 11):
        result['machineElapsedSeconds'] = read('<H')
    if flags & (1 << 12):
        result['remainingSeconds'] = read('<H')
    if pos < len(data):
        result['trailingBytesHex'] = data[pos:].hex()
    return result


def parse_cycling_power_measurement(data: bytes) -> dict:
    """Safely read fixed CPS measurement fields; retain full packet in raw log."""
    if len(data) < 4:
        raise ValueError('Cycling Power packet too short')
    return {'cyclingPowerFlags': int.from_bytes(data[:2], 'little'),
            'cyclingPowerWatts': int.from_bytes(data[2:4], 'little', signed=True)}


async def _capture_capabilities(client, folder):
    reads = {
        'fitnessMachineFeature': FITNESS_MACHINE_FEATURE,
        'cyclingPowerFeature': CYCLING_POWER_FEATURE,
        'supportedPowerRange': SUPPORTED_POWER_RANGE,
        'supportedInclinationRange': SUPPORTED_INCLINATION_RANGE,
        'supportedResistanceRange': SUPPORTED_RESISTANCE_RANGE,
    }
    available = {c.uuid.lower() for s in client.services for c in s.characteristics}
    output = {}
    for label, uuid in reads.items():
        if uuid not in available:
            output[label] = {'supported': False}
            continue
        try:
            raw = bytes(await client.read_gatt_char(uuid))
            entry = {'supported': True, 'hex': raw.hex()}
            if label == 'fitnessMachineFeature' and len(raw) >= 8:
                entry['fitnessMachineFlags'] = int.from_bytes(raw[:4], 'little')
                entry['targetSettingFlags'] = int.from_bytes(raw[4:8], 'little')
            elif label == 'cyclingPowerFeature' and len(raw) >= 4:
                entry['flags'] = int.from_bytes(raw[:4], 'little')
            elif label == 'supportedPowerRange' and len(raw) >= 6:
                entry.update(zip(('minWatts', 'maxWatts', 'stepWatts'), struct.unpack('<hhH', raw[:6])))
            elif label == 'supportedInclinationRange' and len(raw) >= 6:
                a, b, c = struct.unpack('<hhH', raw[:6])
                entry.update({'minPercent': a / 10, 'maxPercent': b / 10, 'stepPercent': c / 10})
            elif label == 'supportedResistanceRange' and len(raw) >= 6:
                a, b, c = struct.unpack('<hhH', raw[:6])
                entry.update({'minRaw': a, 'maxRaw': b, 'stepRaw': c})
            output[label] = entry
        except Exception as exc:
            output[label] = {'supported': True, 'readError': type(exc).__name__ + ': ' + str(exc)}
    save_capabilities(folder, output)


async def bluetooth_worker(store, stop_event, device_id=None,
                           capture=None, capture_dir=None, control_test=False, scan_lock=None,
                           registry=None, shifter=None, grade=None):
    """Reads the trainer; with ``shifter`` (coach.devices.gear_shifter.GearShifter) it also drives the
    trainer's native virtual gears over the Zwift channel of the same connection, and with ``grade``
    (coach.devices.grade_controller.GradeController) the grade the rider chooses, on that same channel."""
    if control_test and shifter is not None:
        raise ValueError('the FTMS grade test and native shifting cannot run together')
    if grade is not None and shifter is None:
        raise ValueError('grade control needs the native shifting channel (shifter)')
    from bleak import BleakClient
    backoff = 2
    while not stop_event.is_set():
        try:
            store.waiting('Buscando rodillo por Bluetooth...')
            found = await find_for_role('trainer', registry=registry, explicit_id=device_id, scan_lock=scan_lock)
            if found is None:
                raise RuntimeError('No se encuentra el rodillo; cierra Zwift/Wahoo')
            if isinstance(found, Ambiguous):
                # Never pick one of several unknown trainers: the rider chooses in Ajustes. The choice applies
                # at the next connection (no switching trainers in the middle of a ride).
                raise RuntimeError(found.message())
            device = found.device
            async with BleakClient(device, timeout=20) as client:
                available = {c.uuid.lower() for s in client.services for c in s.characteristics}
                if INDOOR_BIKE_DATA not in available:
                    raise RuntimeError('El rodillo no anuncia Indoor Bike Data')
                if capture_dir is not None:
                    await _capture_capabilities(client, capture_dir)
                store.waiting(f'Conectado a {device.name}; esperando telemetría...')
                controller = None
                event_log = None
                experiment_state = {}
                if control_test:
                    if capture is None or CONTROL_POINT not in available:
                        raise RuntimeError('Control test requires capture and FTMS Control Point')
                    feature = bytes(await client.read_gatt_char(FEATURE))
                    if not simulation_supported(feature):
                        raise RuntimeError('KICKR does not advertise FTMS indoor bike simulation control')
                    controller = FtmsController(client)
                    event_log = ControlEventLog(capture_dir)
                    await controller.begin()
                    store.set_control('ARMED_BASELINE', None)
                    event_log.add('ARMED', detail='First 300 seconds: no control commands')


                def on_ftms(_sender, data):
                    raw = bytes(data)
                    try:
                        values = parse_indoor_bike_data(raw)
                        store.update(values)
                        if capture:
                            capture.event('ftms', raw, values)
                    except ValueError as exc:
                        store.note_error(f'FTMS inválido: {exc}')
                        if capture:
                            capture.event('ftms_invalid', raw, {'error': str(exc)})

                def on_power(_sender, data):
                    raw = bytes(data)
                    try:
                        values = parse_cycling_power_measurement(raw)
                        store.update_aux(values)
                        if capture:
                            capture.event('cycling_power', raw, values)
                    except ValueError as exc:
                        if capture:
                            capture.event('cycling_power_invalid', raw, {'error': str(exc)})

                def raw_callback(channel):
                    return lambda _sender, data: capture.event(channel, bytes(data)) if capture else None

                subscribed = []
                zwift_writer = None
                try:
                    for uuid, callback in (
                        (INDOOR_BIKE_DATA, on_ftms),
                        (CYCLING_POWER_MEASUREMENT, on_power),
                        (TRAINING_STATUS, raw_callback('training_status')),
                        (FITNESS_MACHINE_STATUS, raw_callback('machine_status')),
                    ):
                        if uuid in available:
                            await client.start_notify(uuid, callback)
                            subscribed.append(uuid)
                    if shifter is not None:
                        if ZWIFT_SYNC_RX in available and ZWIFT_ASYNC in available:
                            def on_zwift(_sender, data):
                                raw = bytes(data)
                                shifter.on_message(raw)
                                if grade is not None:
                                    grade.on_message(raw)   # answers to HubRequest 512: the applied grade
                                if capture:
                                    capture.event('zwift', raw)
                            for uuid in (ZWIFT_ASYNC, ZWIFT_SYNC_TX):
                                if uuid in available:
                                    await client.start_notify(uuid, on_zwift)
                                    subscribed.append(uuid)
                            zwift_writer = SafeZwiftWriter(
                                client, incline_limits=grade.limits_x100 if grade is not None else None)
                            await shifter.start(zwift_writer)  # also after every reconnect: restores the gear
                            if grade is not None:
                                grade.start()  # trainer now at 0.4 %: the rider's grade ramps up again from there
                        else:
                            shifter.status = 'NO_ZWIFT_CHANNEL'
                            if grade is not None:
                                grade.status = 'NO_ZWIFT_CHANNEL'
                    backoff = 2
                    while client.is_connected and not stop_event.is_set():
                        if zwift_writer is not None:
                            trainer = store.snapshot()
                            await shifter.tick(zwift_writer, trainer)
                            if grade is not None:
                                await grade.tick(zwift_writer, trainer)
                        if control_test:
                            try:
                                await run_experiment_tick(client, controller, capture, store, event_log, experiment_state)
                            except Exception as exc:
                                event_log.add('ABORT', detail=str(exc))
                                store.set_control('ABORTED', None)
                                raise
                        await asyncio.sleep(0.25)
                finally:
                    if zwift_writer is not None:
                        if client.is_connected and stop_event.is_set():
                            try:  # leaving the app: back to the neutral gear
                                await shifter.finish(zwift_writer)  # 0.4 % and gear 12: also ends the grade
                                if grade is not None:
                                    grade.stopped()
                            except Exception as exc:
                                print(f'WARNING: could not restore gear 12: {exc}', flush=True)
                        else:
                            shifter.disconnected()
                            if grade is not None:
                                grade.disconnected()
                    if controller is not None:
                        # On shutdown or failure, best-effort restore to 0%.
                        # An unresponsive or disconnected device cannot be guaranteed reset.
                        if experiment_state.get('control_acquired') and client.is_connected:
                            try:
                                await controller.grade(0.0)
                                store.set_control('RESET_ZERO', 0.0)
                                event_log.add('RESET_ZERO_ACK')
                            except Exception as exc:
                                print(f'WARNING: could not reset grade: {exc}', flush=True)
                                event_log.add('RESET_FAILED', detail=str(exc))
                        await controller.finish()
                    if client.is_connected:
                        for uuid in subscribed:
                            try:
                                await client.stop_notify(uuid)
                            except Exception:
                                pass
                store.waiting('Bluetooth desconectado; reconectando...')
        except Exception as exc:
            store.waiting(f'BLE: {type(exc).__name__}: {exc}')
            if control_test:
                print('CONTROL TEST ABORTED; stop pedaling, verify trainer resistance manually.', flush=True)
                break
        if not stop_event.is_set():
            await sleep_unless_stopped(stop_event, backoff)
            backoff = min(backoff * 2, 15)
