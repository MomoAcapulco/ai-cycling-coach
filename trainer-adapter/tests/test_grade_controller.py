"""GradeController with a fake clock: every safety rule of coach/devices/grade_controller.py."""
import asyncio
import unittest

from coach.app.rider_profile import RiderProfile
from coach.devices.gear_shifter import SafeZwiftWriter, check_outgoing
from coach.devices.grade_controller import (GradeController, GradePrefs, START_INCLINE_X100, ZERO_INCLINE_X100,
                                            validate_target)
from coach.session.virtual_ride import VirtualRide
from coach.devices.zwift_hub import SYNC_RX, Simulation, decode_hub_command, encode_hub_command

LIVE = {'connected': True, 'cadenceRpm': 80}
STOPPED = {'connected': True, 'cadenceRpm': 10}
STALE = {'connected': False, 'cadenceRpm': 0}


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, uuid, data, response):
        self.writes.append(bytes(data))


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def inclines(writes):
    return [decode_hub_command(w)['simulation']['inclineX100'] for w in writes
            if 'simulation' in (decode_hub_command(w) or {})]


class GradeControllerTests(unittest.TestCase):
    """The road grade is set by hand here (its distance-based transition is tested in test_virtual_ride)."""
    def setUp(self):
        self.clock = Clock()
        self.client = FakeClient()
        self.ride = VirtualRide(80, 9.5)
        self.grade = GradeController(GradePrefs(), ride=self.ride, clock=self.clock)
        self.writer = SafeZwiftWriter(self.client, incline_limits=self.grade.limits_x100)
        self.grade.start()

    def road(self, grade, target=None):
        """The rider asked ``target`` (default: same) and the road has reached ``grade``."""
        self.ride.request(grade if target is None else target)
        self.ride.road_grade = grade

    def run_for(self, seconds, trainer=LIVE, step=0.25):
        sent_at = []
        for _ in range(round(seconds / step)):
            self.clock.now += step
            before = len(self.client.writes)
            asyncio.run(self.grade.tick(self.writer, trainer))
            if len(self.client.writes) > before:
                sent_at.append(self.clock.now)
        return sent_at

    def test_nothing_is_written_until_the_rider_chooses_a_grade(self):
        self.run_for(30)
        self.assertEqual(self.client.writes, [])
        snap = self.grade.snapshot()
        self.assertEqual((snap['gradeStatus'], snap['effectiveGradePercent']), ('FLAT_START', None))

    def test_difficulty_and_descent_factor(self):
        prefs = GradePrefs()                        # 50 % difficulty, 50 % descent factor, -5..+10
        self.assertEqual(prefs.effective(8), 4)
        self.assertEqual(prefs.effective(-4), -1)   # 4 × 0.5 × 0.5
        self.assertEqual(prefs.effective(20), 10)   # 20 × 0.5 = 10 (cap)
        self.assertEqual(GradePrefs(100, 100, 10, -5).effective(15), 10)   # capped at max
        self.assertEqual(GradePrefs(100, 100, 10, -5).effective(-12), -5)  # capped at min
        self.assertEqual(GradePrefs(0, 50, 10, -5).effective(15), 0)       # 0 %: flat whatever is asked

    def test_follows_the_road_grade_not_the_target(self):
        self.road(2, target=10)                      # the road is still climbing towards 10 %
        self.assertEqual(self.grade.effective(), 1.0)
        self.run_for(10)
        self.assertEqual(inclines(self.client.writes)[-1], 100)
        self.assertEqual(self.grade.snapshot()['gradeStatus'], 'RAMPING')

    def test_safety_net_never_more_than_1_percent_per_second_harder(self):
        self.road(20)                                # even if the road jumped (it never does): 10 % effective
        sent_at = self.run_for(30)
        sent = inclines(self.client.writes)
        self.assertEqual(sent[-1], 1000)
        values = [START_INCLINE_X100] + sent
        rises = [(b - a) / (t2 - t1) for (a, b), (t1, t2) in
                 zip(zip(values, values[1:]), zip([100.0] + sent_at, sent_at)) if b > a]
        self.assertTrue(all(r <= 100.01 for r in rises), rises)   # ≤ 1 % (100 ×0.01) per second
        self.assertTrue(all(b - a >= 1.0 for a, b in zip(sent_at, sent_at[1:])))

    def test_easier_follows_at_once(self):
        self.road(8)
        self.run_for(30)
        self.client.writes.clear()
        self.road(2)
        self.run_for(1.25)
        self.assertEqual(inclines(self.client.writes), [100])

    def test_small_changes_wait_and_settled_values_are_sent(self):
        self.road(8)
        self.run_for(30)
        self.client.writes.clear()
        self.road(8.1)                               # effective 4.05 %: below the 0.1 % step, but settled
        self.run_for(4)
        self.assertEqual(inclines(self.client.writes), [405])
        self.client.writes.clear()
        self.ride.request(12)                        # the road climbs 0.02 % per tick towards 12 %
        sent_at = []
        for _ in range(200):
            self.ride.road_grade = min(12, self.ride.road_grade + 0.02)
            sent_at += self.run_for(0.25)
        values = [405] + inclines(self.client.writes)
        self.assertTrue(all(abs(b - a) >= 10 or b == 600 for a, b in zip(values, values[1:])), values)
        self.assertTrue(all(b - a >= 1.0 for a, b in zip(sent_at, sent_at[1:])))
        self.assertEqual(values[-1], 600)

    def test_unchanged_grade_is_resent_every_10_seconds(self):
        self.road(4)
        self.run_for(30)
        self.client.writes.clear()
        sent_at = self.run_for(40)
        self.assertEqual(set(inclines(self.client.writes)), {200})
        self.assertEqual({round(b - a, 2) for a, b in zip(sent_at, sent_at[1:])}, {10.0})

    def test_never_harder_without_pedalling_or_live_data(self):
        for trainer in (STOPPED, STALE):
            with self.subTest(trainer=trainer):
                self.setUp()
                self.road(10)
                self.run_for(20, trainer)
                self.assertTrue(all(x <= START_INCLINE_X100 for x in inclines(self.client.writes)))
                self.assertEqual(self.grade.snapshot()['gradeStatus'], 'HOLD_NOT_PEDALLING')
                self.run_for(5, LIVE)                # pedalling again: it rises
                self.assertGreater(inclines(self.client.writes)[-1], START_INCLINE_X100)

    def test_easier_is_allowed_when_stopped(self):
        self.road(10)
        self.run_for(30)
        self.client.writes.clear()
        self.road(-2)
        self.run_for(10, STOPPED)
        self.assertEqual(inclines(self.client.writes)[-1], -50)     # -2 × 0.5 × 0.5

    def test_exact_zero_is_sent_as_one_hundredth(self):
        self.road(4)
        self.run_for(30)
        self.road(0)
        self.run_for(10)
        self.assertEqual(inclines(self.client.writes)[-1], ZERO_INCLINE_X100)
        self.assertEqual(self.grade.snapshot()['sentGradePercent'], 0.01)

    def test_reconnect_rises_again_from_the_start_grade(self):
        self.road(16)                                # 8 %
        self.run_for(40)
        self.grade.disconnected()
        self.assertEqual(self.grade.snapshot()['gradeStatus'], 'DISCONNECTED')
        self.client.writes.clear()
        self.grade.start()                           # GearShifter.start has just sent 0.4 %
        self.assertEqual(self.ride.target_grade, 16)  # the rider's choice is kept
        self.run_for(1.25)
        self.assertLessEqual(inclines(self.client.writes)[0], START_INCLINE_X100 + 100)  # no jump back to 8 %
        self.run_for(40)
        self.assertEqual(inclines(self.client.writes)[-1], 800)

    def test_profile_change_applies_at_once(self):
        self.road(8)
        self.run_for(30)
        self.grade.set_prefs(GradePrefs(100, 50, 10, -5))
        self.run_for(30)
        self.assertEqual(inclines(self.client.writes)[-1], 800)
        self.grade.set_prefs(GradePrefs(100, 50, 3, -5))  # lower cap: comes down to 3 %
        self.run_for(10)
        self.assertEqual(inclines(self.client.writes)[-1], 300)

    def test_stop_marks_the_neutral_grade(self):
        self.road(8)
        self.run_for(30)
        self.grade.stopped()
        snap = self.grade.snapshot()
        self.assertEqual((snap['gradeStatus'], snap['sentGradePercent']), ('STOPPED', 0.4))

    def test_target_validation(self):
        self.assertEqual(validate_target(3), 3.0)
        self.assertEqual(validate_target(-2.55), -2.5)  # rounded to 0.1 (banker's rounding of .55 is fine)
        for bad in (None, 'x', True, float('nan'), float('inf'), 21, -16):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_target(bad)


class GradeGuardTests(unittest.TestCase):
    def grade_message(self, x100, **kw):
        return encode_hub_command(simulation=Simulation(incline_x100=x100, **kw))

    def test_shifting_only_writer_still_refuses_any_grade(self):
        check_outgoing(SYNC_RX, self.grade_message(40))
        with self.assertRaises(PermissionError):
            check_outgoing(SYNC_RX, self.grade_message(200))

    def test_grades_inside_the_rider_limits_only(self):
        limits = (-500, 1000)
        for x100 in (-500, -1, 0, 1, 40, 400, 1000):
            check_outgoing(SYNC_RX, self.grade_message(x100), limits)
        for x100 in (-501, 1001, 1500):
            with self.subTest(x100=x100), self.assertRaises(PermissionError):
                check_outgoing(SYNC_RX, self.grade_message(x100), limits)

    def test_hard_limits_whatever_the_profile_says(self):
        with self.assertRaises(PermissionError):
            check_outgoing(SYNC_RX, self.grade_message(2500), (-5000, 5000))
        with self.assertRaises(PermissionError):
            check_outgoing(SYNC_RX, self.grade_message(-1500), (-5000, 5000))

    def test_wind_drag_and_rolling_resistance_are_fixed(self):
        for kw in ({'wind_x100': 500}, {'cwa_x10000': 9000}, {'crr_x100000': 900}):
            with self.subTest(kw=kw), self.assertRaises(PermissionError):
                check_outgoing(SYNC_RX, self.grade_message(200, **kw), (-500, 1000))

    def test_erg_and_other_channels_still_refused(self):
        limits = (-500, 1000)
        for uuid, data in ((SYNC_RX, encode_hub_command(power_target=200)),
                           ('00002ad9-0000-1000-8000-00805f9b34fb', self.grade_message(200)),
                           ('8ec90003-f315-4f60-9fb8-838830daea50', self.grade_message(200))):
            with self.subTest(uuid=uuid), self.assertRaises(PermissionError):
                check_outgoing(uuid, data, limits)

    def test_writer_reads_the_limits_at_every_write(self):
        prefs = {'limits': (-500, 1000)}
        client = FakeClient()
        writer = SafeZwiftWriter(client, incline_limits=lambda: prefs['limits'])
        asyncio.run(writer.write(self.grade_message(800)))
        prefs['limits'] = (-500, 300)
        with self.assertRaises(PermissionError):
            asyncio.run(writer.write(self.grade_message(800)))
        self.assertEqual(len(client.writes), 1)


class GradeProfileTests(unittest.TestCase):
    def test_defaults_and_from_profile(self):
        prefs = GradePrefs.from_profile(RiderProfile())
        self.assertEqual(prefs, GradePrefs(50, 50, 10.0, -5.0))
        self.assertEqual(RiderProfile().to_json()['gradeDifficultyPercent'], 50)
        self.assertEqual(RiderProfile().to_json()['gradeTransitionMetersPerPercent'], 20.0)

    def test_out_of_range_is_rejected_not_clamped(self):
        for change in ({'gradeDifficultyPercent': 101}, {'gradeDifficultyPercent': 50.5},
                       {'gradeDescentFactorPercent': -1}, {'maxGradePercent': 25}, {'maxGradePercent': 0},
                       {'minGradePercent': 1}, {'minGradePercent': -12}, {'minGradePercent': 'x'},
                       {'gradeTransitionMetersPerPercent': 2}, {'gradeTransitionMetersPerPercent': 500}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                RiderProfile().updated(change)

    def test_valid_change(self):
        p = RiderProfile().updated({'gradeDifficultyPercent': 75, 'maxGradePercent': 8, 'minGradePercent': -3.5})
        self.assertEqual(GradePrefs.from_profile(p), GradePrefs(75, 50, 8.0, -3.5))


if __name__ == '__main__':
    unittest.main()
