"""Zwift Play/Click button adapter: read buttons; NEVER commands the trainer.

Controllers are optional and may run in REPLAY mode. BLE 'RideOn' is sent
only to the controller's proprietary handshake characteristic.
"""
import asyncio
from threading import Lock
from time import monotonic
from virtual_gears import relative_ratio, shift

NOTIFY = '00000002-19ca-4651-86e5-fa29dcdd09d1'
WRITE = '00000003-19ca-4651-86e5-fa29dcdd09d1'
BUTTON_MASKS = {
    'left': {'MINUS': 1 << 9, 'UP': 1 << 1, 'DOWN': 1 << 3,
             'LEFT': 1 << 0, 'RIGHT': 1 << 2},
    'right': {'PLUS': 1 << 13, 'Z': 1 << 8, 'B': 1 << 5,
              'A': 1 << 4, 'Y': 1 << 6},
}
ALL_RELEASED = int.from_bytes(bytes.fromhex('ffffffffff'), 'little')


def decode_packet(raw, side):
    if len(raw) != 7 or raw[:2] != b'\x23\x08':
        return None
    raw_bits = int.from_bytes(raw[2:], 'little')
    pressed_bits = ALL_RELEASED & ~raw_bits
    mapping = BUTTON_MASKS[side]
    return {button for button, mask in mapping.items() if pressed_bits & mask}


class ControllerState:
    def __init__(self, initial_gear=12, total_gears=24):
        self.lock = Lock()
        self.gear = initial_gear
        self.total_gears = total_gears
        self.connected = {'left': False, 'right': False}
        self.status = {'left': 'DISABLED', 'right': 'DISABLED'}
        self.last_button = None
        self.last_side = None
        self.last_event_at = None
        self.last_packet_at = None
        self.press_count = 0
        self.held = {'left': set(), 'right': set()}

    def set_status(self, side, connected, status):
        with self.lock:
            self.connected[side] = connected
            self.status[side] = status
            if not connected:
                self.held[side] = set()

    def on_packet(self, side, raw):
        buttons = decode_packet(raw, side)
        if buttons is None:
            return []
        events = []
        with self.lock:
            down = sorted(buttons - self.held[side])
            up = sorted(self.held[side] - buttons)
            self.held[side] = buttons
            self.last_packet_at = monotonic()
            for button in down:
                if button == 'PLUS':
                    self.gear = shift(self.gear, 1)
                elif button == 'MINUS':
                    self.gear = shift(self.gear, -1)
                self.last_button = button
                self.last_side = side
                self.last_event_at = monotonic()
                self.press_count += 1
                events.append({'event': 'BUTTON_DOWN', 'side': side, 'button': button, 'gear': self.gear})
            for button in up:
                events.append({'event': 'BUTTON_UP', 'side': side, 'button': button, 'gear': self.gear})
        return events

    def simulate_shift(self, delta):
        """For REPLAY UI only; caller must enforce REPLAY mode."""
        with self.lock:
            self.gear = shift(self.gear, delta)
            self.last_button = "PLUS" if delta == 1 else "MINUS"
            self.last_side = "ui"
            self.press_count += 1
            return self.gear

    def snapshot(self):
        with self.lock:
            return {
                'zwiftLeftConnected': self.connected['left'],
                'zwiftRightConnected': self.connected['right'],
                'zwiftLeftStatus': self.status['left'],
                'zwiftRightStatus': self.status['right'],
                'virtualGear': self.gear,
                'virtualGearCount': self.total_gears,
                'lastButton': self.last_button,
                'lastButtonSide': self.last_side,
                'buttonPressCount': self.press_count,
                'gearControlMode': 'DISPLAY_ONLY',
                'virtualGearRelativeRatio': relative_ratio(self.gear),
            }


async def controller_worker(state, side, device_id, stop):
    """Continuously retry one configured controller; no Wahoo BLE involved."""
    from bleak import BleakScanner, BleakClient
    while not stop.is_set():
        try:
            state.set_status(side, False, 'SEARCHING')
            devices = await BleakScanner.discover(timeout=8)
            device = next((d for d in devices if d.address.upper() == device_id.upper()), None)
            if device is None:
                state.set_status(side, False, 'NOT_FOUND')
            else:
                async with BleakClient(device, timeout=20) as client:
                    def on_notification(_, data):
                        for event in state.on_packet(side, bytes(data)):
                            print(f'ZWIFT {side}: {event}', flush=True)
                    await client.start_notify(NOTIFY, on_notification)
                    await client.write_gatt_char(WRITE, b'RideOn', response=False)
                    state.set_status(side, True, 'CONNECTED')
                    try:
                        while client.is_connected and not stop.is_set():
                            await asyncio.sleep(0.5)
                    finally:
                        state.set_status(side, False, 'DISCONNECTED')
                        if client.is_connected:
                            await client.stop_notify(NOTIFY)
        except Exception as exc:
            state.set_status(side, False, f'ERROR: {str(exc)[:80]}')
            print(f'ZWIFT {side}: {exc}', flush=True)
        for _ in range(10):
            if stop.is_set():
                return
            await asyncio.sleep(0.5)
