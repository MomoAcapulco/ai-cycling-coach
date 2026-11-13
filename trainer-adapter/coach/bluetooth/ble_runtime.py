"""One asyncio event loop, in one thread, for every Bluetooth worker.

Until v4.2.2 the trainer, the heart-rate strap and each Zwift controller ran in
their own thread with their own ``asyncio.run``. Bleak (CoreBluetooth on macOS)
is designed around a single event loop, and parallel scans from several loops
compete for the same radio. Here every worker is a task of the same loop and
scans are serialised through a shared lock, so only one discovery runs at once.
"""
import asyncio
import contextlib
from threading import Event, Thread


async def sleep_unless_stopped(stop: Event, seconds: float, step: float = 0.25):
    """Sleep up to ``seconds`` but return as soon as ``stop`` is set."""
    remaining = seconds
    while remaining > 0 and not stop.is_set():
        await asyncio.sleep(min(step, remaining))
        remaining -= step


def scanning(scan_lock):
    """Context manager for a BLE scan: the shared lock, or nothing when absent (tests, tools)."""
    return scan_lock if scan_lock is not None else contextlib.nullcontext()


class BleRuntime:
    """Runs the registered worker coroutines as tasks of a single event loop.

    A worker is registered as ``factory(scan_lock) -> coroutine``. One worker
    failing does not cancel the others; its exception is reported and kept in
    ``errors``. The thread is not a daemon: on shutdown the trainer worker must
    be able to restore 0 % before the process exits.
    """

    def __init__(self, stop: Event, name: str = 'ble-runtime'):
        self.stop = stop
        self.name = name
        self.factories = []
        self.errors = {}
        self.thread = None

    def add(self, name, factory):
        if self.thread is not None:
            raise RuntimeError('Workers must be added before start()')
        self.factories.append((name, factory))

    def start(self):
        if not self.factories:
            return None
        self.thread = Thread(target=lambda: asyncio.run(self._main()), daemon=False, name=self.name)
        self.thread.start()
        return self.thread

    def join(self, timeout=None):
        if self.thread is not None:
            self.thread.join(timeout)

    async def _main(self):
        scan_lock = asyncio.Lock()
        tasks = [asyncio.create_task(factory(scan_lock), name=name) for name, factory in self.factories]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for (name, _factory), result in zip(self.factories, results):
            if isinstance(result, BaseException):
                self.errors[name] = result
                print(f'BLE worker {name} stopped with error: {type(result).__name__}: {result}', flush=True)
