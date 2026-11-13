import unittest

from coach.session.metrics import SessionMetrics


def live(power, cadence=80, speed=30.0, hr=None, gear=None):
    return {'connected': True, 'powerWatts': power, 'cadenceRpm': cadence, 'speedKph': speed,
            'heartRateBpm': hr, 'heartRateConnected': hr is not None, 'trainerGear': gear}


class MetricsTests(unittest.TestCase):
    def test_constant_effort(self):
        m = SessionMetrics()
        for _ in range(3600):
            m.add(live(200, speed=36.0, hr=140, gear=14), 1.0)
        s = m.summary(ftp=250)
        self.assertEqual((s['elapsedSeconds'], s['movingSeconds']), (3600.0, 3600.0))
        self.assertAlmostEqual(s['distanceKm'], 36.0, places=6)
        self.assertEqual(s['workKj'], 720.0)               # 200 W × 3600 s
        self.assertEqual((s['avgPowerW'], s['normalizedPowerW']), (200.0, 200.0))  # steady: NP = average
        self.assertEqual(s['intensityFactor'], 0.8)
        self.assertEqual(s['tss'], 64.0)                  # 1 h × 0.8² × 100
        self.assertEqual((s['avgHeartRateBpm'], s['maxHeartRateBpm']), (140.0, 140.0))
        self.assertEqual(s['gearSeconds'], {'14': 3600.0})

    def test_np_rewards_variability(self):
        m = SessionMetrics()
        for i in range(1200):  # alternating 60 s at 300 W and 60 s at 100 W: average 200 W
            m.add(live(300 if (i // 60) % 2 == 0 else 100), 1.0)
        s = m.summary()
        self.assertEqual(s['avgPowerW'], 200.0)
        self.assertGreater(s['normalizedPowerW'], 220)
        self.assertIsNone(s['intensityFactor'])           # no FTP: no IF/TSS, never invented
        self.assertIsNone(s['tss'])

    def test_no_np_below_30_samples(self):
        m = SessionMetrics()
        for _ in range(29):
            m.add(live(200), 1.0)
        self.assertIsNone(m.summary()['normalizedPowerW'])

    def test_dropouts_are_gaps_and_coasting_excluded_from_cadence(self):
        m = SessionMetrics()
        m.add(live(200, cadence=90), 1.0)
        m.add({'connected': False, 'powerWatts': 999, 'cadenceRpm': 0, 'speedKph': 50}, 1.0)  # stale reading
        m.add(live(0, cadence=0, speed=0), 1.0)                                              # stopped
        s = m.summary()
        self.assertEqual((s['elapsedSeconds'], s['movingSeconds'], s['liveSamples']), (3.0, 1.0, 2))
        self.assertEqual((s['avgPowerW'], s['avgMovingPowerW'], s['maxPowerW']), (100.0, 200.0, 200.0))
        self.assertEqual(s['avgCadenceRpm'], 90.0)
        self.assertEqual(s['workKj'], 0.2)

    def test_empty(self):
        s = SessionMetrics().summary(ftp=200)
        self.assertEqual((s['avgPowerW'], s['normalizedPowerW'], s['tss'], s['distanceKm']), (None, None, None, 0.0))


if __name__ == '__main__':
    unittest.main()
