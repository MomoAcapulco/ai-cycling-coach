"""Nothing moves until the rider asks: the simulated rider waits for «Iniciar sesión», a replay for «Reproducir»."""
import tempfile
import unittest
from pathlib import Path

from coach.app.runtime import AdapterRuntime, EnvConfig
from coach.app.server import current_reading
from coach.app.settings import Settings
from coach.session.recording import CsvReplay
from tests.test_fit_export import row as csv_row, write_session


class SimulatorTests(unittest.TestCase):
    def test_the_simulated_rider_only_pedals_in_a_running_session(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            runtime = AdapterRuntime(EnvConfig(record_dir=folder, routes_dir=folder / 'r', history_db=folder / 'h.db'),
                                     Settings(mode='SIMULATOR'), start_workers=False).start()
            try:
                idle = current_reading(runtime.state)
                self.assertEqual((idle['powerWatts'], idle['cadenceRpm'], idle['speedKph']), (0, 0, 0.0))
                self.assertTrue(idle['connected'])                       # the simulated trainer is there
                runtime.session.start()
                self.assertGreater(current_reading(runtime.state)['powerWatts'], 0)
                runtime.session.pause()
                self.assertEqual(current_reading(runtime.state)['powerWatts'], 0)
                runtime.session.resume()
                runtime.session.finish()
                self.assertEqual(current_reading(runtime.state)['powerWatts'], 0)
            finally:
                runtime.shutdown()


class ReplayTests(unittest.TestCase):
    def test_a_replay_waits_at_zero_until_play(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write_session(folder, [csv_row(t) for t in range(60)])
            clock = [100.0]
            replay = CsvReplay(folder / 'session_20261113_130000.csv', clock=lambda: clock[0])
            clock[0] += 10
            self.assertEqual((replay.state()['positionSeconds'], replay.state()['playing']), (0.0, False))
            replay.control('play')
            clock[0] += 10
            self.assertEqual(replay.state()['positionSeconds'], 10.0)


if __name__ == '__main__':
    unittest.main()
