"""Devices remembered on this computer: ALL the ones used for each role, not only the last one.

Stored outside the project folder (default ``devices.json`` in the data home (coach/app/paths.py), override with
DEVICES_FILE) so every version finds the same devices. On macOS the address is the CoreBluetooth UUID, which is
stable on this Mac only; the name and Zwift type are kept too.

Per role (trainer, heart_rate, zwift_left, zwift_right) a list of devices, each with the last time it was used and
at most one ``preferred`` (chosen by the rider with "Usar este" in Ajustes). How they are used to pick a device:
coach/bluetooth/device_finder.py. A device belongs to one role only: a controller found to be the left one leaves
the right list.

File format version 2: ``{"version": 2, "devices": {role: [entry, ...]}}``. Version 1 (one entry per role, before
2026-11-13) is read and converted on the next save; nothing is lost.

Candidates waiting for the rider's choice (several unknown devices of the same kind nearby) are kept in memory
only (``pending``): they are a picture of what is around now, not something to remember.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from coach.bluetooth.discovery import ROLES


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class DeviceRegistry:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.lock = Lock()
        self.pending = {}   # role -> [{'address', 'name', 'rssi', 'item'}], waiting for the rider's choice
        self.revision = 0   # bumped on every change: workers use it to notice "Usar este"

    @classmethod
    def default(cls):
        from coach.app.paths import data_file
        return cls(data_file('devices.json', 'DEVICES_FILE'))

    # ---- reading ----
    def load(self) -> dict:
        """{role: [entries]} — most preferred first (preferred, then most recently used)."""
        with self.lock:
            return {role: self._ranked(entries) for role, entries in self._load().items()}

    def known(self, role) -> list:
        self._check(role)
        return self.load().get(role, [])

    def get(self, role):
        """The device that would be chosen first for ``role`` (or None)."""
        known = self.known(role)
        return known[0] if known else None

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            # A damaged file must not stop the app: start empty, keep the file for inspection.
            print(f'WARNING: ignoring unreadable device registry {self.path}: {exc}', flush=True)
            return {}
        devices = data.get('devices') if isinstance(data, dict) else None
        out = {}
        for role, value in (devices or {}).items():
            if role not in ROLES:
                continue
            entries = value if isinstance(value, list) else [value]   # version 1: one entry per role
            entries = [e for e in entries if isinstance(e, dict) and e.get('address')]
            for entry in entries:
                entry.setdefault('lastUsedAtUtc', entry.get('rememberedAtUtc'))
            if entries:
                out[role] = entries
        return out

    @staticmethod
    def _ranked(entries):
        # preferred first, then most recently used; on a tie the one used later (appended later) first
        order = sorted(enumerate(entries), key=lambda ie: (not ie[1].get('preferred'),
                                                           _desc(_when(ie[1].get('lastUsedAtUtc'))), -ie[0]))
        return [e for _, e in order]

    # ---- changes ----
    def remember(self, role, item, confirmed_side=False, used=True):
        """Add or update ``item`` (a discovery.Classified) in ``role``; ``used`` marks it as used now."""
        self._check(role)
        with self.lock:
            devices = self._load()
            previous = None
            for other, entries in list(devices.items()):
                for entry in list(entries):
                    if entry['address'].upper() == item.address.upper():
                        entries.remove(entry)
                        if other == role:
                            previous = entry
                if not entries:
                    del devices[other]
            entry = {'address': item.address, 'name': item.name or (previous or {}).get('name'), 'kind': item.kind,
                     'zwiftModel': item.zwift_model, 'zwiftType': item.zwift_type,
                     'sideConfirmedByButton': bool(confirmed_side or (previous or {}).get('sideConfirmedByButton')),
                     'preferred': bool((previous or {}).get('preferred')),
                     'rememberedAtUtc': (previous or {}).get('rememberedAtUtc') or _now(),
                     'lastUsedAtUtc': _now() if used else (previous or {}).get('lastUsedAtUtc')}
            devices.setdefault(role, []).append(entry)
            self._save(devices)
            self.pending.pop(role, None)
        return entry

    def prefer(self, role, address):
        """"Usar este": a known device, or one of the pending candidates (which is then remembered)."""
        self._check(role)
        candidate = next((c for c in self.pending.get(role, []) if c['address'].upper() == address.upper()), None)
        if candidate is not None:
            self.remember(role, candidate['item'], used=False)
        with self.lock:
            devices = self._load()
            entries = devices.get(role, [])
            if not any(e['address'].upper() == address.upper() for e in entries):
                raise KeyError(address)
            for entry in entries:
                entry['preferred'] = entry['address'].upper() == address.upper()
            self._save(devices)
            self.pending.pop(role, None)
        return self.known(role)

    def forget(self, role, address=None):
        """Forget one device of ``role``, or all of them."""
        self._check(role)
        with self.lock:
            devices = self._load()
            entries = devices.get(role, [])
            kept = [e for e in entries if address is not None and e['address'].upper() != address.upper()]
            if len(kept) != len(entries):
                if kept:
                    devices[role] = kept
                else:
                    devices.pop(role, None)
                self._save(devices)

    def set_pending(self, role, candidates):
        """Several unknown devices for ``role`` and no known one: the rider chooses (see device_finder)."""
        with self.lock:
            changed = [c['address'] for c in self.pending.get(role, [])] != [c['address'] for c in candidates]
            self.pending[role] = candidates
            if changed:
                self.revision += 1

    def pending_json(self):
        with self.lock:
            return {role: [{k: v for k, v in c.items() if k != 'item'} for c in cands]
                    for role, cands in self.pending.items() if cands}

    # ---- internals ----
    @staticmethod
    def _check(role):
        if role not in ROLES:
            raise ValueError(f'unknown role {role}')

    def _save(self, devices):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + '.tmp')
        tmp.write_text(json.dumps({'version': 2, 'devices': devices}, indent=2, ensure_ascii=False),
                       encoding='utf-8')
        os.replace(tmp, self.path)  # atomic: never a half-written registry
        self.revision += 1


def _when(iso):
    """ISO date as a sortable UTC timestamp (seconds or microseconds, both formats are in old files)."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


def _desc(iso):
    """Sort key for 'most recent first' with a timestamp (None last)."""
    return (0, -iso) if iso is not None else (1, 0)
