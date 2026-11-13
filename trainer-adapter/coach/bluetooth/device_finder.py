"""Find the device for one role: explicit ID (.env) > the rider's known devices > a single new one. Never guesses.

1. ``explicit_id`` (.env): only that device; if it is not around, nothing (never silently another one).
2. One scan that collects every device fitting the role by TYPE (``discovery.fits_role``; any brand):
   - the rider's known devices that are present win, ranked: the PREFERRED one ("Usar este" in Ajustes), then the
     most recently used. The scan stops as soon as the best-ranked known device shows up.
   - no known device present and exactly ONE new one: it is used and added to the known devices.
   - no known device present and SEVERAL new ones: no guess (a neighbour's heart-rate strap would silently record
     someone else's pulse). The candidates are published (``registry.set_pending``) for the rider to choose in
     Ajustes, and the result is ``Ambiguous``; the worker says so and looks again a bit later.
Zwift controllers whose advertisement gives no side fit either slot; they are remembered once the first button
press confirms the side (zwift_controllers.controller_worker). ``Claims`` keeps the two slots apart. For a
controller slot only several new controllers announcing THAT side are ambiguous: two without a side are almost
surely the rider's pair, and the first press puts each in its place.

The scanner is injected (default: bleak.BleakScanner) so the decision logic is tested without radio: only its
``find_device_by_address`` and ``find_device_by_filter`` class methods are used.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from coach.bluetooth.ble_runtime import scanning
from coach.bluetooth.discovery import Advert, Classified, classify, fits_role

SCAN_TIMEOUT = 6      # seconds collecting candidates when the best known device does not show up earlier
REMEMBERED_TIMEOUT = SCAN_TIMEOUT  # kept for callers of the previous version


@dataclass
class Found:
    device: object          # bleak BLEDevice
    item: Classified
    source: str             # 'env', 'registry' or 'scan'


@dataclass
class Ambiguous:
    """Several new devices fit the role and none is known: the rider has to choose one in Ajustes."""
    role: str
    candidates: List[dict] = field(default_factory=list)

    def message(self):
        names = ', '.join(c['name'] or c['address'] for c in self.candidates)
        return f'Hay {len(self.candidates)} dispositivos posibles ({names}): elige uno en Ajustes'


class Claims:
    """Addresses already taken by a worker, so the two controller workers never grab the same device."""
    def __init__(self):
        self.addresses = set()

    def taken(self, address):
        return address.upper() in self.addresses

    def take(self, address):
        self.addresses.add(address.upper())

    def release(self, address):
        self.addresses.discard(address.upper())


async def find_for_role(role, registry=None, explicit_id=None, scan_lock=None,
                        claims: Optional[Claims] = None, scanner=None, scan_timeout=SCAN_TIMEOUT,
                        remembered_timeout=None):
    """Found, Ambiguous or None (nothing fits). ``remembered_timeout`` is accepted for compatibility only."""
    if scanner is None:
        from bleak import BleakScanner
        scanner = BleakScanner
    if explicit_id:
        async with scanning(scan_lock):
            device = await scanner.find_device_by_address(explicit_id, timeout=scan_timeout)
        if device is None:
            return None  # an explicit ID is a choice: never silently replace it with another device
        return Found(device, Classified('configured', device.address, device.name, reason='.env'), 'env')

    known = [k for k in (registry.known(role) if registry is not None else [])
             if not (claims and claims.taken(k['address']))]
    rank = {k['address'].upper(): i for i, k in enumerate(known)}
    # devices the rider has in ANOTHER role (e.g. the right controller while looking for the left one) never count
    elsewhere = {e['address'].upper() for r, entries in (registry.load() if registry is not None else {}).items()
                 if r != role for e in entries}
    seen = {}  # address -> (device, Classified, rssi)

    def wanted(device, adv):
        address = device.address.upper()
        if (claims and claims.taken(address)) or address in elsewhere:
            return False
        if address in rank:
            seen[address] = (device, _known_item(known[rank[address]], device, role), getattr(adv, 'rssi', None))
            return rank[address] == 0       # the best known device: no need to look further
        item = classify(Advert.from_bleak(device, adv))
        if fits_role(item, role):
            seen[address] = (device, item, getattr(adv, 'rssi', None))
        return False

    async with scanning(scan_lock):
        await scanner.find_device_by_filter(wanted, timeout=scan_timeout)

    present_known = sorted((a for a in seen if a in rank), key=rank.get)
    if present_known:
        device, item, _ = seen[present_known[0]]
        if registry is not None:
            registry.remember(role, item, confirmed_side=bool(known[rank[present_known[0]]].get('sideConfirmedByButton')))
        return Found(device, item, 'registry')
    new = list(seen.values())
    if not new:
        return None
    if role.startswith('zwift_'):
        wanted_side = role.split('_', 1)[1]
        explicit = [n for n in new if n[1].side == wanted_side]
        new = explicit if explicit else new[:1]
    if len(new) > 1:
        candidates = [{'address': d.address, 'name': i.name, 'rssi': r, 'item': i}
                      for d, i, r in sorted(new, key=lambda x: -(x[2] if x[2] is not None else -999))]
        if registry is not None:
            registry.set_pending(role, candidates)
        return Ambiguous(role, [{k: v for k, v in c.items() if k != 'item'} for c in candidates])
    device, item, _ = new[0]
    if registry is not None:
        registry.set_pending(role, [])
        # Controllers whose advertisement gives no side are stored once the first press confirms it.
        if not (role.startswith('zwift_') and item.side is None):
            registry.remember(role, item)
    return Found(device, item, 'scan')


def _known_item(entry, device, role):
    side = role.split('_', 1)[1] if role.startswith('zwift_') else None
    return Classified(entry.get('kind') or 'remembered', device.address, device.name or entry.get('name'),
                      side=side, zwift_model=entry.get('zwiftModel'), zwift_type=entry.get('zwiftType'),
                      reason='remembered')


def still_preferred(registry, role, address) -> bool:
    """False when the rider chose ANOTHER known device with "Usar este" while this one is connected."""
    if registry is None:
        return True
    best = registry.get(role)
    return not (best and best.get('preferred') and best['address'].upper() != address.upper())

