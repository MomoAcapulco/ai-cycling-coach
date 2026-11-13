"""Zwift Play/Click button adapter: read buttons; NEVER commands the trainer.

Controllers are optional and may run in REPLAY mode. BLE 'RideOn' is sent
only to the controller's proprietary handshake characteristic.
"""
import asyncio
from dataclasses import replace
from threading import Lock
from time import monotonic
from coach.bluetooth.ble_runtime import sleep_unless_stopped
from coach.bluetooth.device_finder import Ambiguous, Claims, find_for_role, still_preferred
from coach.session.virtual_gears import relative_ratio, shift

NOTIFY = '00000002-19ca-4651-86e5-fa29dcdd09d1'
WRITE = '00000003-19ca-4651-86e5-fa29dcdd09d1'
BUTTON_MASKS = {
    'left': {'MINUS': 1 << 9, 'UP': 1 << 1, 'DOWN': 1 << 3,
             'LEFT': 1 << 0, 'RIGHT': 1 << 2},
    'right': {'PLUS': 1 << 13, 'Z': 1 << 8, 'B': 1 << 5,
              'A': 1 << 4, 'Y': 1 << 6},
}
ALL_RELEASED = int.from_bytes(bytes.fromhex('ffffffffff'), 'little')


SIDE_BITS = {side: sum(masks.values()) for side, masks in BUTTON_MASKS.items()}
assert not SIDE_BITS['left'] & SIDE_BITS['right'], 'left and right button bits must not overlap'
BATTERY_MESSAGE = 0x19


def _pressed_bits(raw):
    if len(raw) != 7 or raw[:2] != b'\x23\x08':
        return None
    return ALL_RELEASED & ~int.from_bytes(raw[2:], 'little')


def decode_packet(raw, side):
    pressed_bits = _pressed_bits(raw)
    if pressed_bits is None:
        return None
    mapping = BUTTON_MASKS[side]
    return {button for button, mask in mapping.items() if pressed_bits & mask}


def decode_any(raw):
    """Buttons pressed on either controller. The bit sets of the two sides do not overlap, so a packet
    is decoded correctly even before we know which physical controller sent it."""
    pressed_bits = _pressed_bits(raw)
    if pressed_bits is None:
        return None
    return {button for masks in BUTTON_MASKS.values() for button, mask in masks.items() if pressed_bits & mask}


def side_from_packet(raw):
    """'left' or 'right' if the packet has a known button pressed, else None."""
    pressed_bits = _pressed_bits(raw)
    if not pressed_bits:
        return None
    sides = [side for side, bits in SIDE_BITS.items() if pressed_bits & bits]
    return sides[0] if len(sides) == 1 else None


def battery_from_packet(raw):
    """Battery % from a 0x19 message: protobuf field 2 (tag 0x10), as in zwiftplay and BikeControl.
    Confirmed on these controllers: 19 10 50 -> 80 %, equal to the standard Battery Level 0x50."""
    if len(raw) >= 3 and raw[0] == BATTERY_MESSAGE and raw[1] == 0x10 and raw[2] < 0x80 and raw[2] <= 100:
        return raw[2]
    return None


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
        self.shifter = None
        self.last_request = 0.0
        self.battery = {'left': None, 'right': None}
        self.detected_side = {'left': None, 'right': None}

    def set_status(self, side, connected, status):
        with self.lock:
            self.connected[side] = connected
            self.status[side] = status
            if not connected:
                self.held[side] = set()

    def on_packet(self, side, raw):
        """``side`` is the worker slot that received the packet; buttons are decoded for both sides."""
        level = battery_from_packet(raw)
        if level is not None:
            with self.lock:
                self.battery[side] = level
            return []
        buttons = decode_any(raw)
        if buttons is None:
            return []
        detected = side_from_packet(raw)
        events = []
        with self.lock:
            down = sorted(buttons - self.held[side])
            up = sorted(self.held[side] - buttons)
            self.held[side] = buttons
            self.last_packet_at = monotonic()
            if detected:
                self.detected_side[side] = detected
            for button in down:
                if button == 'PLUS':
                    self.gear = shift(self.gear, 1)
                    self.last_request = monotonic()
                elif button == 'MINUS':
                    self.gear = shift(self.gear, -1)
                    self.last_request = monotonic()
                self.last_button = button
                self.last_side = side
                self.last_event_at = monotonic()
                self.press_count += 1
                events.append({'event': 'BUTTON_DOWN', 'side': side, 'button': button, 'gear': self.gear})
            for button in up:
                events.append({'event': 'BUTTON_UP', 'side': side, 'button': button, 'gear': self.gear})
        return events

    def simulate_shift(self, delta):
        """A shift from the UI buttons: display only in REPLAY, a real request when a shifter is attached."""
        with self.lock:
            self.gear = shift(self.gear, delta)
            self.last_button = "PLUS" if delta == 1 else "MINUS"
            self.last_side = "ui"
            self.press_count += 1
            self.last_request = monotonic()
            return self.gear

    # ---- used by coach.devices.gear_shifter.GearShifter ----
    def attach_shifter(self, shifter):
        with self.lock:
            self.shifter = shifter

    def detach_shifter(self):
        with self.lock:
            self.shifter = None

    def requested_gear(self):
        with self.lock:
            return self.gear

    def last_request_at(self):
        with self.lock:
            return self.last_request

    def force_gear(self, gear):
        """The shifter's correction: refused or unconfirmed requests snap back to the gear really in use."""
        with self.lock:
            self.gear = max(1, min(self.total_gears, gear))

    def snapshot(self):
        with self.lock:
            shifter = self.shifter
            data = {
                'zwiftLeftConnected': self.connected['left'],
                'zwiftRightConnected': self.connected['right'],
                'zwiftLeftStatus': self.status['left'],
                'zwiftRightStatus': self.status['right'],
                'zwiftLeftBatteryPercent': self.battery['left'],
                'zwiftRightBatteryPercent': self.battery['right'],
                'virtualGear': self.gear,
                'virtualGearCount': self.total_gears,
                'lastButton': self.last_button,
                'lastButtonSide': self.last_side,
                'buttonPressCount': self.press_count,
                'gearControlMode': 'DISPLAY_ONLY',
                'virtualGearRelativeRatio': relative_ratio(self.gear),
            }
        if shifter is not None:
            data.update(shifter.snapshot())  # gearControlMode TRAINER, trainerGear (confirmed), gearStatus…
        return data


async def controller_worker(state, side, device_id, stop, scan_lock=None, registry=None, claims=None):
    """Keep one controller slot connected; no Wahoo BLE involved.

    The device comes from ``device_id`` (.env), else the remembered one, else a scan (see device_finder).
    A controller whose advertisement gives no side is accepted by either slot; its first button press
    tells the real side, which is then remembered for the next start.
    """
    from bleak import BleakClient
    claims = claims if claims is not None else Claims()
    while not stop.is_set():
        found = None
        try:
            state.set_status(side, False, 'SEARCHING')
            found = await find_for_role(f'zwift_{side}', registry=registry, explicit_id=device_id,
                                        scan_lock=scan_lock, claims=claims, scan_timeout=8)
            if found is None:
                state.set_status(side, False, 'NOT_FOUND')
            elif isinstance(found, Ambiguous):
                state.set_status(side, False, 'CHOOSE_IN_SETTINGS')
                print(f'ZWIFT {side}: {found.message()}', flush=True)
                found = None
            else:
                claims.take(found.device.address)
                confirmed = {'done': found.source != 'scan' or found.item.side is not None}
                async with BleakClient(found.device, timeout=20) as client:
                    def on_notification(_, data, found=found, confirmed=confirmed):
                        raw = bytes(data)
                        for event in state.on_packet(side, raw):
                            print(f'ZWIFT {side}: {event}', flush=True)
                        detected = side_from_packet(raw)
                        if detected and registry is not None and not confirmed['done']:
                            registry.remember(f'zwift_{detected}', replace(found.item, side=detected),
                                              confirmed_side=True)
                            confirmed['done'] = True
                            print(f'ZWIFT {side}: {found.device.address} is the {detected} controller (remembered)',
                                  flush=True)
                    await client.start_notify(NOTIFY, on_notification)
                    await client.write_gatt_char(WRITE, b'RideOn', response=False)
                    state.set_status(side, True, 'CONNECTED')
                    try:
                        while client.is_connected and not stop.is_set():
                            if not still_preferred(registry, f'zwift_{side}', found.device.address):
                                break  # the rider chose another controller in Ajustes: switch now
                            await asyncio.sleep(0.5)
                    finally:
                        state.set_status(side, False, 'DISCONNECTED')
                        if client.is_connected:
                            await client.stop_notify(NOTIFY)
        except Exception as exc:
            state.set_status(side, False, f'ERROR: {str(exc)[:80]}')
            print(f'ZWIFT {side}: {exc}', flush=True)
        finally:
            if found is not None:
                claims.release(found.device.address)
        await sleep_unless_stopped(stop, 5)
