import asyncio
import threading
import time
import unittest
from threading import Event

from coach.bluetooth.ble_runtime import BleRuntime, scanning, sleep_unless_stopped


class BleRuntimeTests(unittest.TestCase):
    def test_all_workers_share_one_loop_and_one_thread(self):
        stop = Event()
        seen = {}

        def worker(name):
            async def run(scan_lock):
                seen[name] = (asyncio.get_running_loop(), threading.get_ident(), scan_lock)
                while not stop.is_set():
                    await asyncio.sleep(0.01)
            return run

        runtime = BleRuntime(stop)
        for name in ('wahoo', 'hr', 'zwift-left', 'zwift-right'):
            runtime.add(name, worker(name))
        runtime.start()
        deadline = time.monotonic() + 2
        while len(seen) < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        stop.set()
        runtime.join(timeout=2)
        self.assertFalse(runtime.thread.is_alive())
        self.assertEqual(len({id(v[0]) for v in seen.values()}), 1, 'one event loop')
        self.assertEqual(len({v[1] for v in seen.values()}), 1, 'one thread')
        self.assertEqual(len({id(v[2]) for v in seen.values()}), 1, 'one shared scan lock')
        self.assertNotEqual(next(iter(seen.values()))[1], threading.get_ident())

    def test_scans_never_overlap(self):
        stop = Event()
        active = []
        overlaps = []

        def scanner(name):
            async def run(scan_lock):
                for _ in range(3):
                    async with scanning(scan_lock):
                        active.append(name)
                        if len(active) > 1:
                            overlaps.append(tuple(active))
                        await asyncio.sleep(0.01)
                        active.remove(name)
            return run

        runtime = BleRuntime(stop)
        for name in ('a', 'b', 'c'):
            runtime.add(name, scanner(name))
        runtime.start()
        runtime.join(timeout=2)
        self.assertEqual(overlaps, [])

    def test_one_failing_worker_does_not_stop_the_others(self):
        stop = Event()
        finished = []

        async def broken(_scan_lock):
            raise RuntimeError('boom')

        async def healthy(_scan_lock):
            await asyncio.sleep(0.05)
            finished.append('healthy')

        runtime = BleRuntime(stop)
        runtime.add('broken', broken)
        runtime.add('healthy', healthy)
        runtime.start()
        runtime.join(timeout=2)
        self.assertEqual(finished, ['healthy'])
        self.assertIsInstance(runtime.errors['broken'], RuntimeError)

    def test_no_workers_no_thread(self):
        runtime = BleRuntime(Event())
        self.assertIsNone(runtime.start())
        runtime.join(timeout=0.1)

    def test_cannot_add_after_start(self):
        stop = Event()
        stop.set()

        async def quick(_scan_lock):
            return None

        runtime = BleRuntime(stop)
        runtime.add('quick', quick)
        runtime.start()
        with self.assertRaises(RuntimeError):
            runtime.add('late', quick)
        runtime.join(timeout=1)

    def test_sleep_returns_early_when_stopped(self):
        stop = Event()

        async def scenario():
            asyncio.get_running_loop().call_later(0.05, stop.set)
            started = time.monotonic()
            await sleep_unless_stopped(stop, 10)
            return time.monotonic() - started

        self.assertLess(asyncio.run(scenario()), 1)


if __name__ == '__main__':
    unittest.main()
