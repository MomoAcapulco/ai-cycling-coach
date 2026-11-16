"""FTP notice: best powers, critical power fit, indoor / outdoor estimates and the advice (never lowering it)."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from coach.history.ftp_model import best_averages, estimate, fit_cp, ftp_advice, one_hour

TODAY = date(2026, 11, 16)


def curve(cp, w_prime, durations=(60, 180, 240, 300, 420, 600, 720, 900, 1200, 1800)):
    """Best powers of a rider who follows the model exactly."""
    return {t: round(cp + w_prime / t, 1) for t in durations}


def ride(id_, days_ago, mmp, kind='virtual_ride', name='Zwift'):
    return {'id': id_, 'type': kind, 'name': name, 'start_utc': f'{TODAY - timedelta(days=days_ago)}T09:00:00+00:00',
            'mmp': json.dumps(mmp)}


profile = lambda ftp: SimpleNamespace(ftp_watts=ftp)   # noqa: E731


class BestTests(unittest.TestCase):
    def test_best_average_per_duration_and_gaps_break_windows(self):
        powers = [100.0] * 300 + [None] + [200.0] * 200 + [150.0] * 100
        best = best_averages(powers, (60, 180, 300))
        self.assertEqual(best[60], 200.0)
        self.assertEqual(best[180], 200.0)
        self.assertEqual(best[300], round((200 * 200 + 150 * 100) / 300, 1))   # not across the gap
        self.assertEqual(best_averages([None, 100.0], (60,)), {})


class ModelTests(unittest.TestCase):
    def test_fit_recovers_cp_and_w_prime(self):
        model = fit_cp(curve(250, 20000))
        self.assertEqual(model['cp'], 250)
        self.assertAlmostEqual(model['wPrime'], 20000, delta=50)        # the curve is rounded to 0.1 W

    def test_needs_short_and_long_efforts_and_a_real_w_prime(self):
        self.assertIsNone(fit_cp({180: 300, 240: 290, 300: 280}))                 # nothing of 12–20 min
        self.assertIsNone(fit_cp({600: 260, 900: 255, 1200: 250}))                # nothing of 3–5 min
        self.assertIsNone(fit_cp(curve(250, 500)))                                # W′ of 0.5 kJ: not maximal

    def test_estimate_uses_the_best_of_each_duration_in_the_window(self):
        short = {t: w for t, w in curve(250, 20000).items() if t <= 300}
        long = {t: w for t, w in curve(250, 20000).items() if t > 300}
        old = curve(300, 20000)
        rows = [ride('a', 3, short), ride('b', 10, long), ride('old', 80, old)]   # 80 days: outside
        e = estimate(rows, ('virtual_ride',), TODAY)
        self.assertEqual((e['method'], e['cp'], e['ftp']), ('cp', 250, round(250 + 20000 / 3600)))
        self.assertEqual({x['id'] for x in e['efforts']}, {'a', 'b'})

    def test_a_sub_maximal_long_best_does_not_pull_it_down(self):
        efforts = {**curve(250, 20000), 1800: 200.0}                         # an easy 30 min, not all-out
        e = estimate([ride('a', 3, efforts)], ('virtual_ride',), TODAY)
        self.assertEqual(e['method'], 'single')                             # the 20 min one says more
        self.assertLess(e['modelFtp'], e['singleFtp'])
        self.assertEqual(e['ftp'], round(one_hour(250 + 20000 / 1200, 1200)))

    def test_without_the_model_one_long_effort_is_enough(self):
        self.assertAlmostEqual(one_hour(200, 1200), 190, delta=0.2)                # the classic 95 % of 20 min
        self.assertAlmostEqual(one_hour(200, 3600), 200)
        self.assertAlmostEqual(one_hour(200, 480) / 200, 0.91, delta=0.005)
        e = estimate([ride('a', 3, {1200: 200})], ('virtual_ride',), TODAY)
        self.assertEqual((e['method'], e['seconds'], e['ftp']), ('single', 1200, 190))
        e = estimate([ride('a', 3, {1200: 200, 2400: 196})], ('virtual_ride',), TODAY)   # the 40 min one says more
        self.assertEqual((e['seconds'], e['ftp']), (2400, round(one_hour(196, 2400))))
        self.assertIsNone(estimate([ride('a', 3, {60: 400, 300: 300})], ('virtual_ride',), TODAY))


class AdviceTests(unittest.TestCase):
    def test_raise_when_clearly_above(self):
        rows = [ride('a', 5, curve(250, 20000))]                                  # estimate 256
        a = ftp_advice(profile(240), rows, TODAY)
        self.assertEqual((a['kind'], a['suggestedFtp'], a['estimateFrom']), ('raise', 256, 'indoor'))
        self.assertEqual(ftp_advice(profile(250), rows, TODAY)['kind'], 'ok')    # under 3 % more: no notice

    def test_no_ftp_set_or_test(self):
        self.assertEqual(ftp_advice(profile(None), [ride('a', 5, curve(250, 20000))], TODAY)['kind'], 'set')
        self.assertEqual(ftp_advice(profile(None), [], TODAY)['kind'], 'test')

    def test_never_lowered_a_test_is_proposed(self):
        easy = {t: 180.0 for t in (180, 300, 600, 1200)}                          # sweet spot rides only
        a = ftp_advice(profile(250), [ride('a', 5, easy)], TODAY)
        self.assertEqual((a['kind'], a['reason'], a['suggestedFtp']), ('test', 'no_max_effort', None))
        hard_then_easy = [ride('max', 30, {300: 290}), ride('a', 5, easy)]       # a max 5 min a month ago, now falling
        self.assertTrue(ftp_advice(profile(250), [ride('long', 5, {3600: 240})], TODAY)['kind'] == 'ok')  # 1 h at 96 %
        a = ftp_advice(profile(250), hard_then_easy, TODAY)
        self.assertEqual((a['kind'], a['reason'], a['lastMaxEffort']['daysAgo']), ('test', 'falling', 30))

    def test_a_ramp_test_counts_as_a_max_effort(self):
        rows = [ride('t', 20, {60: 300}, name='Test de FTP (rampa)'), ride('a', 5, curve(240, 15000))]
        a = ftp_advice(profile(242), rows, TODAY)
        self.assertEqual((a['kind'], a['lastTest']['date']), ('ok', str(TODAY - timedelta(days=20))))
        self.assertEqual(ftp_advice(profile(242), [ride('t', 70, {}, name='Test de FTP (rampa)')], TODAY)['kind'], 'test')

    def test_outdoor_apart_and_cautious(self):
        rows = [ride('out', 5, curve(270, 20000), kind='ride')]                  # outdoor 276
        a = ftp_advice(profile(240), rows, TODAY)
        self.assertIsNone(a['indoor'])
        self.assertEqual((a['outdoor']['ftp'], a['estimateFrom'], a['suggestedFtp']), (276, 'outdoor', 262))


class EnrichTests(unittest.TestCase):
    def test_app_sessions_get_their_best_powers(self):
        from coach.history.load import enrich_missing
        from coach.history.store import HistoryStore, import_app_sessions
        from tests.test_fit_export import row as csv_row, write_session
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write_session(folder, [csv_row(t) for t in range(1300)], elapsedSeconds=1300.0)
            store = HistoryStore(folder / 'history.db')
            import_app_sessions(store, folder)
            enrich_missing(store, folder, folder)
            [row] = store.list()
            mmp = json.loads(row['mmp'])
            self.assertEqual((mmp['60'], mmp['1200'], row['best20_w']), (200.0, 200.0, 200.0))


if __name__ == '__main__':
    unittest.main()
