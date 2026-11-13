"""The virtual road (coach/session/virtual_ride.py) and the session metrics built on it."""
import math
import time
import unittest
from threading import Event
from types import SimpleNamespace

from coach.session.metrics import SessionMetrics
from coach.session.virtual_ride import VirtualRide

MASS = 80 + 9.5


def ride_for(ride, seconds, power, step=0.25):
    for _ in range(round(seconds / step)):
        ride.step(step, power)


class PhysicsTests(unittest.TestCase):
    def test_steady_speeds_are_realistic(self):
        kph = lambda w, g: VirtualRide.steady_speed_ms(w, g, MASS) * 3.6  # noqa: E731
        self.assertAlmostEqual(kph(200, 0), 31.8, delta=1.5)
        self.assertAlmostEqual(kph(200, 5), 14.1, delta=0.8)
        self.assertAlmostEqual(kph(200, 8), 9.6, delta=0.6)
        self.assertGreater(kph(200, -5), 50)          # ~53 km/h: a lighter rider descends slower
        self.assertLess(kph(300, 8), kph(300, 5))

    def test_speed_drops_on_a_climb_unlike_the_trainer_speed(self):
        ride = VirtualRide(80, 9.5)
        ride_for(ride, 120, 200)
        flat = ride.speed_ms * 3.6
        ride.request(8)
        ride_for(ride, 600, 200)
        self.assertAlmostEqual(flat, 31.8, delta=1.5)
        self.assertAlmostEqual(ride.speed_ms * 3.6, 9.6, delta=0.6)

    def test_coasting_never_rolls_back(self):
        ride = VirtualRide(80, 9.5)
        ride.request(8)
        ride.road_grade = 8
        ride_for(ride, 60, 0)
        self.assertEqual(ride.speed_ms, 0.0)
        self.assertEqual(ride.distance_m, 0.0)

    def test_downhill_coasting_speeds_up(self):
        ride = VirtualRide(80, 9.5)
        ride.request(-5)
        ride.road_grade = -5
        ride_for(ride, 30, 0)
        self.assertGreater(ride.speed_ms * 3.6, 30)

    def test_a_stalled_caller_does_not_teleport(self):
        ride = VirtualRide(80, 9.5)
        ride_for(ride, 120, 200)
        before = ride.distance_m
        ride.step(3600, 200)                          # one hour without steps: counted as 2 s at most
        self.assertLess(ride.distance_m - before, 2 * 10)


class RoadGradeTransitionTests(unittest.TestCase):
    def test_grade_changes_by_distance_never_as_a_wall(self):
        ride = VirtualRide(80, 9.5, meters_per_percent=20)
        ride_for(ride, 60, 200)
        ride.request(5)
        start_m, last_grade, last_m = ride.distance_m, ride.road_grade, ride.distance_m
        while ride.road_grade < 5:
            ride.step(0.25, 200)
            moved = ride.distance_m - last_m
            self.assertLessEqual(ride.road_grade - last_grade, moved / 20 + 1e-6)  # ≤ 1 % per 20 m
            last_grade, last_m = ride.road_grade, ride.distance_m
        self.assertAlmostEqual(ride.distance_m - start_m, 100, delta=8)            # 0 → 5 % in ~100 m

    def test_stopped_the_grade_does_not_change(self):
        ride = VirtualRide(80, 9.5)
        ride.request(6)
        ride_for(ride, 30, 0)                         # not pedalling, standing still
        self.assertEqual(ride.road_grade, 0.0)
        ride_for(ride, 60, 250)
        self.assertGreater(ride.road_grade, 0.0)

    def test_going_down_is_gradual_too(self):
        ride = VirtualRide(80, 9.5, meters_per_percent=10)
        ride.request(4)
        ride.road_grade = 4
        ride_for(ride, 120, 250)
        ride.request(-4)
        ride_for(ride, 1, 250)
        self.assertGreater(ride.road_grade, 0)        # 8 % of change needs 80 m: not done in 1 s

    def test_profile_change(self):
        ride = VirtualRide(80, 9.5)
        ride.set_profile(80, 8, 40)
        self.assertEqual((ride.mass_kg, ride.meters_per_percent), (88, 40))


class ElevationTests(unittest.TestCase):
    def test_climbing_a_kilometre_at_5_percent(self):
        ride = VirtualRide(80, 9.5)
        ride.request(5)
        ride.road_grade = 5
        while ride.distance_m < 1000:
            ride.step(0.25, 250)
        expected = ride.distance_m * math.sin(math.atan(0.05))
        self.assertAlmostEqual(ride.gain_m, expected, delta=0.5)
        self.assertAlmostEqual(ride.gain_m, 50, delta=2)
        snap = ride.snapshot(250)
        self.assertGreater(snap['vamMh'], 400)       # ~12 km/h at 5 %: ~600 m/h
        self.assertAlmostEqual(snap['wattsPerKg'], 250 / 80, places=2)

    def test_descending_does_not_add_gain_but_lowers_altitude(self):
        ride = VirtualRide(80, 9.5)
        ride.request(-4)
        ride.road_grade = -4
        ride_for(ride, 60, 100)
        self.assertEqual(ride.gain_m, 0.0)
        self.assertLess(ride.altitude_m, -10)
        self.assertEqual(ride.snapshot(100)['vamMh'], 0)

    def test_gain_uses_the_road_grade_not_the_difficulty(self):
        ride = VirtualRide(80, 9.5)                  # the ride knows nothing of difficulty: by design
        self.assertNotIn('difficulty', ride.snapshot())


class TickerTests(unittest.TestCase):
    def test_the_ticker_moves_the_rider_with_live_power_only(self):
        from coach.app.runtime import ride_ticker
        from coach.app.server import AdapterState
        state = AdapterState(mode='SIMULATOR', ride=VirtualRide(80, 9.5))
        stop = Event()
        from threading import Thread
        thread = Thread(target=ride_ticker, args=(state, stop, 0.02), daemon=True)
        thread.start()
        time.sleep(0.5)
        stop.set()
        thread.join(2)
        self.assertGreater(state.ride.distance_m, 0)  # the simulator streams ~165 W

    def test_no_live_data_means_no_power(self):
        from coach.app.server import live_power
        self.assertEqual(live_power({'connected': False, 'powerWatts': 300}), 0.0)
        self.assertEqual(live_power({'connected': True, 'powerWatts': 300}), 300.0)


def sample(power=200, distance=None, gain=None, connected=True):
    return {'connected': connected, 'powerWatts': power, 'cadenceRpm': 80, 'speedKph': 30,
            'rideDistanceKm': distance, 'elevationGainM': gain}


class SessionClimbMetricsTests(unittest.TestCase):
    def test_distance_and_gain_come_from_the_virtual_road(self):
        m = SessionMetrics()
        for i in range(121):                          # 2 min, 10 m/s on the road, 0.5 m up per second
            m.add(sample(distance=5 + i * 0.01, gain=100 + i * 0.5), 1)
        s = m.summary(ftp=None, rider_kg=80)
        self.assertAlmostEqual(s['distanceKm'], 1.2, places=3)  # not 30 km/h of trainer speed
        self.assertAlmostEqual(s['elevationGainM'], 60.0)
        self.assertEqual(s['vamMh'], 1800)
        self.assertAlmostEqual(s['avgWattsPerKg'], 2.5, places=2)

    def test_pause_and_dropouts_add_no_distance(self):
        m = SessionMetrics()
        m.add(sample(distance=1.0, gain=0), 1)
        m.add(sample(distance=1.01, gain=0), 1)
        m.restart_counters()                          # paused: the rider rode 2 km meanwhile
        m.add(sample(distance=3.01, gain=0), 1)
        m.add(sample(distance=3.02, gain=0), 1)
        m.add(sample(distance=3.5, gain=0, connected=False), 1)  # dropout
        m.add(sample(distance=3.51, gain=0), 1)
        self.assertAlmostEqual(m.distance_km, 0.03, places=6)

    def test_old_readings_still_use_the_trainer_speed(self):
        m = SessionMetrics()
        m.add(sample(), 3600)
        self.assertAlmostEqual(m.distance_km, 30)

    def test_vam_needs_a_minute_of_climbing(self):
        m = SessionMetrics()
        for i in range(30):
            m.add(sample(distance=i * 0.01, gain=i * 0.5), 1)
        self.assertIsNone(m.summary()['vamMh'])


class BestEffortTests(unittest.TestCase):
    def test_best_efforts_and_estimated_ftp(self):
        m = SessionMetrics()
        for _ in range(600):
            m.add(sample(power=150), 1)
        for _ in range(1200):
            m.add(sample(power=250), 1)
        for _ in range(5):
            m.add(sample(power=600), 1)
        s = m.summary(rider_kg=80)
        self.assertEqual(s['bestEffortsW']['5'], 600)
        self.assertEqual(s['bestEffortsW']['60'], round((55 * 250 + 5 * 600) / 60, 1))
        self.assertAlmostEqual(s['bestEffortsW']['1200'], (1195 * 250 + 5 * 600) / 1200, places=1)
        self.assertEqual(s['estimatedFtpW'], round(s['bestEffortsW']['1200'] * 0.95))
        self.assertAlmostEqual(s['best20MinWattsPerKg'], s['bestEffortsW']['1200'] / 80, places=2)

    def test_a_dropout_breaks_the_window(self):
        m = SessionMetrics()
        for _ in range(3):
            m.add(sample(power=500), 1)
        m.add(sample(connected=False), 1)
        for _ in range(3):
            m.add(sample(power=500), 1)
        self.assertIsNone(m.best_efforts()['5'])      # never 5 consecutive live seconds
        self.assertIsNone(m.summary()['estimatedFtpW'])



class ReplayOfRideSessionsTests(unittest.TestCase):
    def test_session_with_the_virtual_road_replays_with_distance_and_altitude(self):
        import tempfile
        from pathlib import Path
        from coach.session.recording import CsvReplay
        from coach.session.session import SessionManager
        ride = VirtualRide(80, 9.5)
        ride.request(5)

        def reading():
            ride.step(1, 250)
            return {'source': 'WAHOO', 'connected': True, 'status': 'STREAMING', 'powerWatts': 250,
                    'cadenceRpm': 80, 'speedKph': 21, 'heartRateBpm': None, 'heartRateConnected': False,
                    **ride.snapshot(250)}
        clock = SimpleNamespace(t=0.0)
        with tempfile.TemporaryDirectory() as folder:
            session = SessionManager(reading, Path(folder), clock=lambda: clock.t, sample_seconds=3600,
                                     rider_kg=lambda: 80)
            session.start()
            for _ in range(240):
                clock.t += 1
                session._sample_unlocked()
            summary = session.finish()
            self.assertGreater(summary['elevationGainM'], 10)
            self.assertEqual(summary['riderWeightKg'], 80)
            series = CsvReplay(Path(folder) / summary['csv']).series()
        self.assertEqual(series['gradeKind'], 'ROAD')
        first, last = series['samples'][0], series['samples'][-1]
        self.assertEqual(first['altitude'], 0.0)                 # relative to the start of the session
        self.assertAlmostEqual(last['altitude'], summary['elevationGainM'] - first['altitude'], delta=3)
        self.assertAlmostEqual(last['distance'], summary['distanceKm'], places=2)
        self.assertLess(last['speed'], 19)                       # the physics speed (~17 at 5 %), not the trainer's 21


if __name__ == '__main__':
    unittest.main()
