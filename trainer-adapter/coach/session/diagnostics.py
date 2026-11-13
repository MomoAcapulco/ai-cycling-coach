"""Capture all observed BLE notifications in a 10-minute local raw JSONL log.

No device IDs are saved. Never sends GATT writes or exposes raw capture over HTTP.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import monotonic


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class RawCapture:
    def __init__(self, directory, seconds=600, clock=monotonic, manual=False):
        """``manual``: the capture runs between begin() and end() (a training session); otherwise it
        starts at the first moving FTMS packet and lasts ``seconds`` (the supervised control test)."""
        self.directory = Path(directory)
        self.seconds = seconds
        self.manual = manual
        self.clock = clock
        self.lock = Lock()
        self.started = None
        self.path = None
        self.file = None

    def begin(self, stem: str):
        """Manual mode: open ``<stem>.jsonl`` and record every channel until end()."""
        with self.lock:
            self._close()
            self.directory.mkdir(parents=True, exist_ok=True)
            self.path = self.directory / f'{stem}.jsonl'
            self.file = self.path.open('w', encoding='utf-8')
            self.started = self.clock()
            return self.path

    def end(self):
        with self.lock:
            self._close()
            self.started = None

    def event(self, channel, raw, decoded=None):
        """Start at first moving FTMS packet; record other channels while active."""
        with self.lock:
            if self.manual:
                if self.file is not None:
                    self._write(channel, raw, decoded, self.clock() - self.started)
                return
            if self.started is None:
                if channel != 'ftms' or not decoded or not any(
                    (decoded.get(k) or 0) > 0 for k in ('speedKph', 'powerWatts', 'cadenceRpm')
                ):
                    return
                self.directory.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
                self.path = self.directory / f'ble_raw_{stamp}.jsonl'
                self.file = self.path.open('w', encoding='utf-8')
                self.started = self.clock()
                print(f'Captura BLE cruda durante {self.seconds}s: {self.path}', flush=True)
            elapsed = self.clock() - self.started
            if elapsed >= self.seconds:
                self._close()
                return
            if self.file is None:
                return
            self._write(channel, raw, decoded, elapsed)

    def _write(self, channel, raw, decoded, elapsed):
        event = {'timestampUtc': utc_now(), 'elapsedSeconds': round(elapsed, 3),
                 'channel': channel, 'hex': bytes(raw).hex(), 'parsed': decoded or {}}
        self.file.write(json.dumps(event, ensure_ascii=False) + '\n')
        self.file.flush()

    def _close(self):
        if self.file:
            self.file.close()
            self.file = None

    def close(self):
        with self.lock:
            self._close()


def save_capabilities(directory, characteristics):
    """Read-only GATT capability values, no addresses or serial numbers."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'wahoo_capabilities.json'
    document = {'collectedAtUtc': utc_now(), 'readOnly': True,
                'characteristics': characteristics}
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Capacidades BLE: {path}', flush=True)
    return path
