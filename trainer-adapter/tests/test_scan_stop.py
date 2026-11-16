"""A Bluetooth scan stops as soon as the workers are told to stop (leaving the replay must not wait for it)."""
import asyncio
import time
import unittest
from threading import Event, Timer

from coach.bluetooth.device_finder import find_for_role


class SlowScanner:
    """A scan that would take 5 s, like looking for a controller that is asleep."""
    cancelled = False

    @classmethod
    async def find_device_by_filter(cls, wanted, timeout):
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cls.cancelled = True
            raise

    @classmethod
    async def find_device_by_address(cls, address, timeout):
        await asyncio.sleep(5)


class ScanStopTests(unittest.TestCase):
    def test_a_scan_stops_at_once(self):
        stop = Event()
        Timer(0.3, stop.set).start()
        started = time.monotonic()
        found = asyncio.run(find_for_role('zwift_left', scanner=SlowScanner, scan_timeout=5, stop=stop))
        self.assertIsNone(found)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(SlowScanner.cancelled)                       # the scan itself is cancelled, not left running

    def test_an_explicit_device_too(self):
        stop = Event()
        Timer(0.3, stop.set).start()
        started = time.monotonic()
        self.assertIsNone(asyncio.run(find_for_role('trainer', explicit_id='AA', scanner=SlowScanner, stop=stop)))
        self.assertLess(time.monotonic() - started, 1.0)

    def test_already_stopped_does_not_scan(self):
        stop = Event()
        stop.set()
        started = time.monotonic()
        self.assertIsNone(asyncio.run(find_for_role('heart_rate', scanner=SlowScanner, stop=stop)))
        self.assertLess(time.monotonic() - started, 0.2)


if __name__ == '__main__':
    unittest.main()
