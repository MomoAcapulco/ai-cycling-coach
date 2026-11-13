"""Conservative, explicitly enabled FTMS grade experiment.

No commands are sent before minute 5. Responses MUST acknowledge success.
If control cannot be confirmed, the experiment aborts (the app cannot promise
that BLE disconnect restores the physical trainer's previous resistance).
"""
import asyncio
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

CONTROL_POINT = '00002ad9-0000-1000-8000-00805f9b34fb'
FEATURE = '00002acc-0000-1000-8000-00805f9b34fb'
# 5 minutes of baseline, 5 × 60 seconds of slopes, deliberately capped at 3%.
BASELINE_SECONDS = 300
STEPS = [(1.0, 60), (2.0, 60), (3.0, 60), (2.0, 60), (0.0, 60)]
MAX_GRADE = 3.0


def simulation_packet(grade):
    if not 0 <= grade <= MAX_GRADE:
        raise ValueError('Grade outside conservative test range (0-3%)')
    # Opcode 0x11: signed wind speed (0.001 m/s), signed grade (0.01%),
    # rolling coeff (0.0001), aerodynamic coeff (0.01 kg/m).
    return struct.pack('<BhhBB', 0x11, 0, round(grade * 100), 40, 30)


def parse_response(payload, requested_opcode):
    if len(payload) < 3 or payload[0] != 0x80 or payload[1] != requested_opcode:
        raise ValueError(f'Unexpected FTMS response: {payload.hex()}')
    if payload[2] != 0x01:
        raise RuntimeError(f'FTMS rejected opcode {requested_opcode:#x}, result={payload[2]:#x}')


def simulation_supported(raw_feature):
    return len(raw_feature) >= 8 and bool(int.from_bytes(raw_feature[4:8], 'little') & (1 << 13))


def experiment_phase(elapsed):
    if elapsed < BASELINE_SECONDS:
        return 'BASELINE', None
    at = elapsed - BASELINE_SECONDS
    for i, (grade, length) in enumerate(STEPS):
        if at < length:
            return f'SLOPE_{i + 1}', grade
        at -= length
    return 'FINISHED', None


class FtmsController:
    def __init__(self, client):
        self.client = client
        self.pending = None
        self.pending_opcode = None
        self.started = False

    def indication(self, _sender, data):
        response = bytes(data)
        if self.pending is not None and not self.pending.done():
            if len(response) >= 2 and response[:2] == bytes([0x80, self.pending_opcode]):
                self.pending.set_result(response)

    async def begin(self):
        await self.client.start_notify(CONTROL_POINT, self.indication)
        self.started = True

    async def send(self, packet):
        if not self.started:
            raise RuntimeError('Control indications not enabled')
        if self.pending is not None:
            raise RuntimeError('Concurrent FTMS control request')
        loop = asyncio.get_running_loop()
        self.pending = loop.create_future()
        self.pending_opcode = packet[0]
        try:
            await self.client.write_gatt_char(CONTROL_POINT, packet, response=True)
            reply = await asyncio.wait_for(self.pending, timeout=4)
            parse_response(reply, packet[0])
        finally:
            self.pending = None
            self.pending_opcode = None

    async def request_control(self):
        await self.send(b'\x00')

    async def grade(self, value):
        await self.send(simulation_packet(value))

    async def finish(self):
        if self.started and self.client.is_connected:
            try:
                await self.client.stop_notify(CONTROL_POINT)
            except Exception:
                pass
        self.started = False


class ControlEventLog:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = None

    def add(self, event, elapsed=None, grade=None, detail=None):
        self.folder.mkdir(parents=True, exist_ok=True)
        if self.path is None:
            self.path = self.folder / ('control_events_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.jsonl')
        record = {'utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  'event': event, 'elapsedSeconds': elapsed, 'gradePercent': grade, 'detail': detail}
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')


async def run_experiment_tick(client, controller, capture, store, events, state):
    """Called from BLE worker loop. Sends one command per planned step."""
    if capture.started is None:
        return
    elapsed = capture.clock() - capture.started
    phase, grade = experiment_phase(elapsed)
    if phase == 'BASELINE':
        return
    if state.get('complete'):
        return
    if phase == 'FINISHED':
        state['complete'] = True
        store.set_control('COMPLETED', 0.0)
        events.add('COMPLETED', elapsed, 0)
        return
    if state.get('phase') == phase:
        return
    if not store.snapshot()['connected']:
        raise RuntimeError('Telemetry stale; stopping control test')
    if not state.get('control_acquired'):
        await controller.request_control()
        state['control_acquired'] = True
        events.add('CONTROL_GRANTED', elapsed)
    await controller.grade(grade)
    state['phase'] = phase
    store.set_control(phase, grade)
    events.add('GRADE_ACK', elapsed, grade, phase)
