import tempfile
import unittest
from pathlib import Path
from recording import CsvReplay
from virtual_gears import shift, relative_ratio


class ReplayControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'data.csv'
        self.path.write_text('elapsedSeconds,source,powerWatts,cadenceRpm,speedKph,connected,status,heartRateBpm,heartRateConnected,targetGradePercent\n'
                             '0,WAHOO,100,60,15,true,STREAMING,120,true,\n'
                             '2,WAHOO,200,70,18,true,STREAMING,140,true,2\n')
        self.now = [0.0]
        self.replay = CsvReplay(self.path, clock=lambda: self.now[0])

    def tearDown(self):
        self.temp.cleanup()

    def test_seek_pause_play_speed(self):
        self.assertEqual(len(self.replay.series()['samples']), 2)
        self.replay.control('pause')
        self.now[0] += 10
        self.assertEqual(self.replay.snapshot()['elapsedSeconds'], 0)
        self.replay.control('seek', 2)
        self.assertEqual(self.replay.snapshot()['targetGradePercent'], 2)
        self.replay.control('restart')
        self.assertIsNone(self.replay.snapshot()['targetGradePercent'])
        self.replay.control('speed', 2)
        self.replay.control('play')
        self.now[0] += 1
        self.assertEqual(self.replay.snapshot()['elapsedSeconds'], 2)

    def test_limits(self):
        self.assertEqual(shift(24, 1), 24)
        self.assertEqual(shift(1, -1), 1)
        self.assertEqual(relative_ratio(12), 1.0)
        with self.assertRaises(ValueError):
            self.replay.control('speed', 30)
        with self.assertRaises(ValueError):
            shift(12, 0)


if __name__ == '__main__':
    unittest.main()
