import csv
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread
from time import sleep
from recording import CsvReplay, record_once


class RecordingTests(unittest.TestCase):
    def test_record_and_replay(self):
        trainer = lambda: {
            'source': 'WAHOO', 'powerWatts': 153, 'cadenceRpm': 78.0,
            'speedKph': 22.4, 'connected': True, 'status': 'STREAMING',
        }
        hr = lambda: {
            'heartRateBpm': 128, 'heartRateConnected': True,
            'heartRateStatus': 'STREAMING',
        }
        with tempfile.TemporaryDirectory() as d:
            path = record_once(trainer, hr, Event(), Path(d),
                               seconds=0.14, interval=0.04)
            self.assertTrue(path.is_file())
            with path.open() as f:
                rows = list(csv.DictReader(f))
            self.assertGreaterEqual(len(rows), 2)
            self.assertEqual(rows[0]['powerWatts'], '153')
            self.assertEqual(rows[0]['heartRateBpm'], '128')
            replay = CsvReplay(path)
            self.assertEqual(replay.snapshot()['source'], 'REPLAY')
            self.assertEqual(replay.snapshot()['powerWatts'], 153)
            self.assertEqual(replay.snapshot()['heartRateBpm'], 128)

    def test_waits_for_first_movement(self):
        stop = Event()
        with tempfile.TemporaryDirectory() as d:
            t = Thread(target=lambda: record_once(
                lambda: {'connected': True, 'powerWatts': 0,
                         'cadenceRpm': 0, 'speedKph': 0},
                lambda: {}, stop, Path(d), seconds=0.2,
                interval=0.05))
            t.start()
            sleep(0.08)
            stop.set()
            t.join(2)
            self.assertEqual(list(Path(d).glob('*.csv')), [])

    def test_missing_file_fails_cleanly(self):
        with self.assertRaises(FileNotFoundError):
            CsvReplay('/no/such/file.csv')


if __name__ == '__main__':
    unittest.main()
