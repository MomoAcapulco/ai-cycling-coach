"""Training load (power, heart rate, estimate), duplicates, fitness / fatigue / form."""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from coach.history.load import (CTL_DAYS, ENRICH_VERSION, Params, _per_second, activity_load, daily_series,
                                derive_params, duplicates, enrich_missing, load_report, robust_max)
from coach.history.store import HistoryStore, import_app_sessions
from tests.test_fit_export import row as csv_row, write_session

P = Params(ftp=200, ftp_source='profile', hr_rest=60, hr_rest_source='profile', hr_max=180, hr_max_source='profile',
           lthr=160, lthr_source='profile')
T0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def activity(id_, kind='virtual_ride', start=T0, seconds=3600, **extra):
    return {'id': id_, 'type': kind, 'start_utc': start.isoformat(), 'elapsed_s': seconds, 'moving_s': seconds,
            'has_power': 0, 'has_hr': 0, 'np': None, 'avg_hr': None, 'hr_hist': None, 'best20_w': None,
            'max_hr': None, **extra}


class LoadTests(unittest.TestCase):
    def test_one_hour_at_ftp_or_at_threshold_heart_rate_is_100(self):
        self.assertEqual(activity_load(activity('a', has_power=1, np=200), P), (100.0, 'power'))
        hist = json.dumps({'160': 3600})
        self.assertEqual(activity_load(activity('b', kind='ride', hr_hist=hist), P), (100.0, 'hr'))
        self.assertEqual(activity_load(activity('c', kind='run', avg_hr=160), P), (100.0, 'hr_avg'))

    def test_harder_counts_more_and_easy_counts_little(self):
        easy = activity_load(activity('a', kind='ride', hr_hist=json.dumps({'110': 3600})), P)[0]
        hard = activity_load(activity('b', kind='ride', hr_hist=json.dumps({'172': 3600})), P)[0]
        self.assertLess(easy, 40)
        self.assertGreater(hard, 120)
        self.assertEqual(activity_load(activity('c', has_power=1, np=150), P)[0], round(0.75 ** 2 * 100, 1))

    def test_power_needs_an_ftp_and_running_power_is_not_used(self):
        no_ftp = Params(**{**P.__dict__, 'ftp': None, 'ftp_source': None})
        self.assertEqual(activity_load(activity('a', has_power=1, np=200, avg_hr=160), no_ftp)[1], 'hr_avg')
        self.assertEqual(activity_load(activity('b', kind='run', has_power=1, np=300, avg_hr=160), P)[1], 'hr_avg')

    def test_estimate_without_power_or_heart_rate(self):
        self.assertEqual(activity_load(activity('a', kind='ride', seconds=7200), P), (100.0, 'estimate'))
        self.assertEqual(activity_load(activity('b', kind='strength', seconds=3600), P), (35.0, 'estimate'))

    def test_heart_rate_recorded_far_beyond_the_activity_is_cut(self):
        hist = json.dumps({'160': 36000})                         # 10 h of heart rate on a 1 h activity
        self.assertEqual(activity_load(activity('a', kind='workout', hr_hist=hist), P)[0], 100.0)


class ThresholdTests(unittest.TestCase):
    def test_robust_max_ignores_a_lone_spike(self):
        self.assertEqual(robust_max([195, 181, 180, 170]), 181)
        self.assertEqual(robust_max([183, 181, 180]), 183)
        self.assertIsNone(robust_max([None, 0]))

    def test_profile_wins_else_history_else_defaults(self):
        rows = [activity('a', best20_w=200, max_hr=181, start=datetime.now(timezone.utc) - timedelta(days=10)),
                activity('b', best20_w=260, start=datetime.now(timezone.utc) - timedelta(days=500)),   # too old
                activity('c', kind='run', best20_w=300, max_hr=195)]                                   # not a ride
        empty = SimpleNamespace(ftp_watts=None, max_heart_rate=None, resting_heart_rate=None, threshold_heart_rate=None)
        p = derive_params(empty, rows)
        self.assertEqual((p.ftp, p.ftp_source, p.hr_max, p.hr_rest, p.lthr, p.lthr_source),
                         (190, 'history', 181, 60, 163, 'estimate'))
        mine = SimpleNamespace(ftp_watts=230, max_heart_rate=185, resting_heart_rate=52, threshold_heart_rate=168)
        p = derive_params(mine, rows)
        self.assertEqual((p.ftp, p.ftp_source, p.hr_max, p.hr_rest, p.lthr), (230, 'profile', 185, 52, 168))


class StreamTests(unittest.TestCase):
    def test_heart_rate_is_carried_30_s_power_only_3_s(self):
        samples = [(T0 + timedelta(seconds=s), 150, 200) for s in (0, 5, 10)] + [(T0 + timedelta(seconds=60), 150, 200)]
        grid = _per_second(samples)
        self.assertEqual(len(grid), 61)
        self.assertEqual(grid[4], (150, None))                    # 4 s after a sample: hr yes, power no
        self.assertEqual(grid[2], (150, 200))
        self.assertEqual(grid[45], (None, None))                  # 35 s without samples: both gaps


class DuplicateTests(unittest.TestCase):
    def test_the_same_ride_recorded_twice_counts_once(self):
        zwift = activity('zwift', has_power=1, has_hr=1, np=180)
        watch = activity('watch', kind='ride', start=T0 + timedelta(minutes=2), seconds=3500, has_hr=1)
        run = activity('run', kind='run', start=T0 + timedelta(minutes=5))      # another family: kept
        later = activity('later', start=T0 + timedelta(hours=3))
        self.assertEqual(duplicates([zwift, watch, run, later]), {'watch': 'zwift'})


class SeriesTests(unittest.TestCase):
    def test_fitness_fatigue_form(self):
        start = date(2026, 1, 1)
        series = daily_series({start + timedelta(days=d): 100.0 for d in range(84)}, start + timedelta(days=90))
        self.assertEqual(len(series), 91)
        day = series[83]
        self.assertAlmostEqual(day['ctl'], 100 * (1 - (1 - 1 / CTL_DAYS) ** 84), delta=0.1)
        self.assertAlmostEqual(day['atl'], 100.0, delta=0.5)
        self.assertLess(day['tsb'], 0)                            # training every day: tired
        self.assertGreater(series[-1]['tsb'], 15)                 # a week of rest: fresh
        self.assertEqual(series[0]['tsb'], 0.0)                   # form of a day = yesterday's CTL − ATL


class EnrichAndReportTests(unittest.TestCase):
    def test_enrich_app_sessions_and_report(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write_session(folder, [csv_row(t) for t in range(1300)], elapsedSeconds=1300.0)
            store = HistoryStore(folder / 'history.db')
            import_app_sessions(store, folder)
            self.assertEqual(enrich_missing(store, folder, folder), 1)
            self.assertEqual(enrich_missing(store, folder, folder), 0)            # read once
            [row] = store.list()
            self.assertEqual(row['enriched'], ENRICH_VERSION)
            self.assertEqual(json.loads(row['hr_hist']), {'140': 1300})
            self.assertEqual(row['best20_w'], 200.0)
            profile = SimpleNamespace(ftp_watts=None, max_heart_rate=None, resting_heart_rate=None, threshold_heart_rate=None)
            report = load_report(store.list(), profile, today=date(2026, 11, 15))
            self.assertEqual(report['params']['ftp'], 190)                       # 95 % of the best 20 min
            self.assertEqual(report['methods'], {'power': 1})
            self.assertEqual(report['days'][0]['date'], '2026-11-13')
            self.assertGreater(report['today']['ctl'], 0)


class ApiTests(unittest.TestCase):
    def test_load_endpoint(self):
        from threading import Thread
        from urllib.request import urlopen
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write_session(folder, [csv_row(t) for t in range(120)])
            runtime = AdapterRuntime(EnvConfig(record_dir=folder, routes_dir=folder / 'r', history_db=folder / 'h.db'),
                                     Settings(), start_workers=False).start()
            httpd = make_server('127.0.0.1', 0, runtime)
            Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                report = json.loads(urlopen(f'http://127.0.0.1:{httpd.server_address[1]}/history/load?days=30',
                                            timeout=5).read())
                self.assertLessEqual(len(report['days']), 30)                   # from the first activity, at most 30
                self.assertEqual(report['days'][-1]['date'], datetime.now().astimezone().date().isoformat())
                self.assertIn('ctl', report['today'])
                self.assertEqual(report['activities'][0]['id'], 'app:session_20261113_130000')
            finally:
                runtime.shutdown()
                httpd.shutdown()
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
