"""Bluetooth autodiscovery: classify advertisements into trainer, heart-rate strap or Zwift controller.

Rules taken from established open-source projects (see docs/adr/ADR-002-autodiscovery.md):
- Trainer: advertises FTMS (0x1826), Cycling Power (0x1818) or the Wahoo service. It is checked FIRST,
  because a trainer can also advertise Heart Rate (it relays a paired strap) and, on KICKR CORE 2
  class trainers, the Zwift service itself (BikeControl, Incyclist).
- Zwift controller: Zwift service (00000001-19ca-..., or 0xFC82) or manufacturer data of Zwift, Inc.
  (company 0x094A). The first manufacturer byte is the device type: 0x02 Play right, 0x03 Play left,
  0x07/0x08 Ride right/left, 0x09 Click, 0x0A/0x0B Click v2 right/left, 0x0E Play firmware 2 (no side).
  Same values in BikeControl, Incyclist and zwiftplay. 0x0A/0x0B, marked "unconfirmed" in BikeControl,
  are confirmed by our own scan of 2026-11-12 (ble_scan_20261112_124949.json): two "Zwift Click"
  advertising service 0xFC82 with manufacturer data 0b.. (left) and 0a.. (right).
- Heart rate: Heart Rate service (0x180D) only, checked LAST.

Run ``python tools/discovery.py --seconds 15`` to list what is around and save the raw advertisements.
Nothing here connects to or writes to any device.
"""
import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

BASE_UUID = '-0000-1000-8000-00805f9b34fb'
FTMS = '00001826' + BASE_UUID
CYCLING_POWER = '00001818' + BASE_UUID
HEART_RATE = '0000180d' + BASE_UUID
WAHOO_SERVICE = 'a026ee0b-0a7d-4ab3-97fa-f1500f9feb8b'
ZWIFT_SERVICE = '00000001-19ca-4651-86e5-fa29dcdd09d1'
ZWIFT_RIDE_SERVICE = '0000fc82' + BASE_UUID
ZWIFT_COMPANY_ID = 0x094A
TRAINER_SERVICES = (FTMS, CYCLING_POWER, WAHOO_SERVICE)
ZWIFT_SERVICES = (ZWIFT_SERVICE, ZWIFT_RIDE_SERVICE)

TRAINER, HEART_RATE_STRAP, ZWIFT_CONTROLLER, UNKNOWN = 'trainer', 'heart_rate', 'zwift', 'unknown'

# type byte -> (model, side or None)
ZWIFT_TYPES = {
    0x02: ('PLAY', 'right'),
    0x03: ('PLAY', 'left'),
    0x07: ('RIDE', 'right'),
    0x08: ('RIDE', 'left'),
    0x09: ('CLICK', None),
    0x0A: ('CLICK_V2', 'right'),  # confirmed on our controllers, 2026-11-12
    0x0B: ('CLICK_V2', 'left'),   # confirmed on our controllers, 2026-11-12
    0x0E: ('PLAY_FW2', None),
}


def normalize_uuid(uuid: str) -> str:
    """'1826', '0x1826' and the full form all become the full lower-case 128-bit UUID."""
    value = uuid.strip().lower()
    if value.startswith('0x'):
        value = value[2:]
    if len(value) == 4:
        return f'0000{value}{BASE_UUID}'
    if len(value) == 8:
        return f'{value}{BASE_UUID}'
    return value


@dataclass(frozen=True)
class Advert:
    """What a scan tells us about one device, independent of Bleak."""
    address: str
    name: Optional[str] = None
    service_uuids: Tuple[str, ...] = ()
    manufacturer_data: Dict[int, bytes] = field(default_factory=dict)
    rssi: Optional[int] = None

    @classmethod
    def from_bleak(cls, device, adv):
        return cls(address=device.address,
                   name=adv.local_name or device.name,
                   service_uuids=tuple(normalize_uuid(u) for u in (adv.service_uuids or [])),
                   manufacturer_data={int(k): bytes(v) for k, v in (adv.manufacturer_data or {}).items()},
                   rssi=adv.rssi)

    def merged(self, newer: 'Advert') -> 'Advert':
        """macOS often delivers name, services and manufacturer data in separate packets: keep everything."""
        return Advert(address=self.address,
                      name=newer.name or self.name,
                      service_uuids=tuple(dict.fromkeys(self.service_uuids + newer.service_uuids)),
                      manufacturer_data={**self.manufacturer_data, **newer.manufacturer_data},
                      rssi=newer.rssi if newer.rssi is not None else self.rssi)

    def to_json(self):
        return {'address': self.address, 'name': self.name, 'serviceUuids': list(self.service_uuids),
                'manufacturerData': {f'0x{k:04X}': v.hex() for k, v in self.manufacturer_data.items()},
                'rssi': self.rssi}


@dataclass(frozen=True)
class Classified:
    kind: str
    address: str
    name: Optional[str]
    side: Optional[str] = None
    zwift_model: Optional[str] = None
    zwift_type: Optional[int] = None
    reason: str = ''

    def to_json(self):
        return asdict(self)


def zwift_type(adv: Advert) -> Optional[int]:
    data = adv.manufacturer_data.get(ZWIFT_COMPANY_ID)
    return data[0] if data else None


def classify(adv: Advert) -> Classified:
    services = {normalize_uuid(u) for u in adv.service_uuids}
    found = [s for s in TRAINER_SERVICES if s in services]
    if found:
        return Classified(TRAINER, adv.address, adv.name, reason='service ' + found[0][:8])
    type_byte = zwift_type(adv)
    if type_byte is not None or services & set(ZWIFT_SERVICES):
        model, side = ZWIFT_TYPES.get(type_byte, ('UNKNOWN_ZWIFT', None)) if type_byte is not None else ('UNKNOWN_ZWIFT', None)
        reason = f'zwift type 0x{type_byte:02X}' if type_byte is not None else 'zwift service, no manufacturer data'
        return Classified(ZWIFT_CONTROLLER, adv.address, adv.name, side=side, zwift_model=model,
                          zwift_type=type_byte, reason=reason)
    if HEART_RATE in services:
        return Classified(HEART_RATE_STRAP, adv.address, adv.name, reason='service 180d')
    return Classified(UNKNOWN, adv.address, adv.name, reason='no known service')


ROLES = ('trainer', 'heart_rate', 'zwift_left', 'zwift_right')


def fits_role(item: Classified, role: str) -> bool:
    """Whether a classified device can take a role: by TYPE only (what it advertises), never by name, so any
    brand works. Zwift controllers without a side fit either side; the side is then confirmed by the first
    button press (see zwift_controllers.side_from_packet)."""
    if role == 'trainer':
        return item.kind == TRAINER
    if role == 'heart_rate':
        return item.kind == HEART_RATE_STRAP
    if role in ('zwift_left', 'zwift_right'):
        wanted = role.split('_', 1)[1]
        return item.kind == ZWIFT_CONTROLLER and item.side in (wanted, None)
    raise ValueError(f'unknown role {role}')


async def scan(seconds: float, scan_lock=None) -> Dict[str, Advert]:
    """One passive scan; returns the merged advertisement per address."""
    from bleak import BleakScanner
    from coach.bluetooth.ble_runtime import scanning
    seen: Dict[str, Advert] = {}

    def on_advert(device, adv):
        new = Advert.from_bleak(device, adv)
        seen[device.address] = seen[device.address].merged(new) if device.address in seen else new

    async with scanning(scan_lock):
        async with BleakScanner(detection_callback=on_advert):
            await asyncio.sleep(seconds)
    return seen


def main():
    parser = argparse.ArgumentParser(description='List nearby trainers, HR straps and Zwift controllers (read-only).')
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--all', action='store_true', help='also list unknown devices')
    from coach.app.paths import diagnostics_dir
    parser.add_argument('--out', default=str(diagnostics_dir()),
                        help='folder for the raw scan JSON')
    parser.add_argument('--remember', action='store_true',
                        help='store the unambiguous trainer / strap / controllers in the device registry')
    args = parser.parse_args()
    print(f'Scanning {args.seconds:g} s... (close Zwift/Wahoo apps; press a button on each Zwift controller)')
    adverts = asyncio.run(scan(args.seconds))
    results = [(classify(a), a) for a in adverts.values()]
    results.sort(key=lambda r: (r[0].kind == UNKNOWN, r[0].kind, r[0].name or ''))
    for item, adv in results:
        if item.kind == UNKNOWN and not args.all:
            continue
        side = f' side={item.side}' if item.kind == ZWIFT_CONTROLLER else ''
        print(f'{item.kind:10} {item.name or "?":24} {item.address}  rssi={adv.rssi}{side}  ({item.reason})')
    folder = Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('ble_scan_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '.json')
    path.write_text(json.dumps({'scannedAtUtc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                'devices': [{'classified': i.to_json(), 'advert': a.to_json()} for i, a in results]},
                               indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Raw advertisements saved: {path}')
    if args.remember:
        from coach.bluetooth.device_registry import DeviceRegistry
        registry = DeviceRegistry.default()
        for role in ROLES:
            candidates = [i for i, _ in results if fits_role(i, role)]
            if role.startswith('zwift'):
                candidates = [i for i in candidates if i.side == role.split('_', 1)[1]]
            if len(candidates) == 1:
                registry.remember(role, candidates[0])
                print(f'Remembered {role}: {candidates[0].name} {candidates[0].address}')
            elif candidates:
                print(f'Not remembered {role}: {len(candidates)} candidates, choose one in .env')
        print(f'Registry: {registry.path}')


if __name__ == '__main__':
    main()
