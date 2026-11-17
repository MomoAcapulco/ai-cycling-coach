"""The race calendar (coach/app/goals_store.py): events, results and the month view."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.app import db
from coach.app.goals_store import GoalsStore
from coach.app.routes_store import save_upload
from coach.app.runtime import AdapterRuntime, EnvConfig
from coach.app.server import make_server
from coach.app.settings import Settings
from coach.history.store import HistoryStore
from tests.test_routes import CLIMB, gpx, segments_profile

TODAY = date(2026, 11, 17)


class GoalsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.db = db.migrate(self.folder / 'coach.db')
        self.store = GoalsStore(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_an_event_with_its_route_and_the_days_left(self):
        save_upload(self.folder / 'routes', 'cuna.gpx', gpx(segments_profile(CLIMB)), self.db)
        event = self.store.create({'name': 'Cuna de la Legión', 'eventDate': '2027-03-14', 'kind': 'MTB_MARATHON',
                                   'distanceKm': 56, 'gainM': 1429, 'routeFile': 'cuna.gpx', 'priority': 'A'})
        [listed] = self.store.list(TODAY)
        self.assertEqual((listed['name'], listed['priority'], listed['routeFile'], listed['distanceKm'], listed['gainM']),
                         ('Cuna de la Legión', 'A', 'cuna.gpx', 56.0, 1429.0))
        self.assertEqual(listed['daysTo'], (date(2027, 3, 14) - TODAY).days)
        self.assertFalse(listed['needsResult'])
        self.assertEqual(self.store.update(event['id'], {'priority': 'B'})['priority'], 'B')
        self.store.delete(event['id'])
        self.assertEqual(self.store.list(TODAY), [])

    def test_bad_events_are_refused(self):
        for body in ({'eventDate': '2027-03-14'}, {'name': 'X', 'eventDate': '14/03/2027'}, {'name': 'X', 'eventDate': '2027-02-30'},
                     {'name': 'X', 'eventDate': '2027-03-14', 'kind': 'TRIATHLON'}, {'name': 'X', 'eventDate': '2027-03-14', 'priority': 'Z'},
                     {'name': 'X', 'eventDate': '2027-03-14', 'distanceKm': -5}, {'name': 'X', 'eventDate': '2027-03-14', 'routeFile': 'none.gpx'},
                     {'name': 'X', 'eventDate': '2027-03-14', 'colour': 'red'}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.store.create(body)

    def test_a_past_event_asks_how_it_went_and_keeps_the_result(self):
        HistoryStore(self.db).add({'id': 'strava:42', 'source': 'strava', 'type': 'ride', 'name': 'La Africana',
                                   'start_utc': '2026-10-19T07:30:00+00:00', 'moving_s': 17000, 'distance_m': 74200})
        event = self.store.create({'name': 'La Africana', 'eventDate': '2026-10-19', 'priority': 'B'})
        self.assertTrue(self.store.list(TODAY)[0]['needsResult'])
        self.assertEqual([a['id'] for a in self.store.activities_on('2026-10-19')], ['strava:42'])
        done = self.store.save_result(event['id'], {'finished': True, 'timeSeconds': 18120, 'rpe': 8,
                                                    'note': 'calambres al final', 'activityId': 'strava:42'})
        self.assertEqual(done['status'], 'done')
        self.assertEqual(done['result'], {'finished': True, 'timeSeconds': 18120.0, 'rpe': 8,
                                          'note': 'calambres al final', 'activityId': 'strava:42'})
        self.assertFalse(self.store.list(TODAY)[0]['needsResult'])
        self.store.save_result(event['id'], {'finished': False})                 # changed: one result, the latest
        self.assertEqual(self.store.get(event['id'])['result']['finished'], False)
        for bad in ({'finished': 'yes'}, {'finished': True, 'rpe': 11}, {'finished': True, 'activityId': 'strava:0'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.store.save_result(event['id'], bad)

    def test_the_month_shows_events_and_what_was_done(self):
        history = HistoryStore(self.db)
        history.add({'id': 'app:session_20261103_180000', 'source': 'app', 'type': 'virtual_ride', 'name': 'Rodillo',
                     'start_utc': '2026-11-03T18:00:00+00:00', 'moving_s': 3600})
        history.add({'id': 'strava:7', 'source': 'strava', 'type': 'run', 'start_utc': '2026-10-31T09:00:00+00:00'})
        self.store.create({'name': 'Prueba de noviembre', 'eventDate': '2026-11-29'})
        month = self.store.month('2026-11', TODAY)
        self.assertEqual(list(month['activities']), ['2026-11-03'])               # October is not in November
        self.assertEqual([g['name'] for g in month['goals']], ['Prueba de noviembre'])
        with self.assertRaises(ValueError):
            self.store.month('noviembre')


class StageRaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.db = db.migrate(self.folder / 'coach.db')
        self.store = GoalsStore(self.db)
        save_upload(self.folder / 'routes', 'e1.gpx', gpx(segments_profile(CLIMB), name='Etapa 1'), self.db)
        self.race = self.store.create({'name': 'Andalucía Bike Race', 'kind': 'MTB_STAGES', 'priority': 'A', 'stages': [
            {'date': '2026-11-10', 'distanceKm': 70, 'gainM': 1800, 'routeFile': 'e1.gpx', 'name': 'Jaén'},
            {'date': '2026-11-11', 'distanceKm': 65, 'gainM': 1500},
            {'date': '2026-11-20', 'distanceKm': 60, 'gainM': 1200}]})

    def tearDown(self):
        self.temp.cleanup()

    def test_a_race_in_stages_goes_from_the_first_to_the_last_adding_them_up(self):
        race = self.store.list(TODAY)[0]
        self.assertEqual((race['eventDate'], race['endDate'], race['distanceKm'], race['gainM']),
                         ('2026-11-10', '2026-11-20', 195.0, 4500.0))
        self.assertEqual([(s['stageNo'], s['name'], s['routeFile']) for s in race['stages']],
                         [(1, 'Jaén', 'e1.gpx'), (2, None, None), (3, None, None)])
        self.assertEqual(race['daysToEnd'], 3)
        self.assertTrue(race['needsResult'])                                  # stages 1 and 2 are over
        self.assertEqual([s['needsResult'] for s in race['stages']], [True, True, False])
        days = self.store.month('2026-11', TODAY)['raceDays']
        self.assertEqual([(d['date'], d['stageNo'], d['stages']) for d in days],
                         [('2026-11-10', 1, 3), ('2026-11-11', 2, 3), ('2026-11-20', 3, 3)])

    def test_each_stage_has_its_result_and_the_race_adds_them_up(self):
        rid = self.race['id']
        self.store.save_result(rid, {'stageNo': 1, 'finished': True, 'timeSeconds': 18000, 'rpe': 8})
        self.store.save_result(rid, {'stageNo': 2, 'finished': True, 'timeSeconds': 16000, 'rpe': 9})
        partial = self.store.get(rid)
        self.assertIsNone(partial['result'])                                  # stage 3 still to come
        self.assertEqual(partial['status'], 'planned')
        done = self.store.save_result(rid, {'stageNo': 3, 'finished': True, 'timeSeconds': 15000, 'rpe': 7})
        self.assertEqual((done['status'], done['result']['finished'], done['result']['timeSeconds'], done['result']['rpe']),
                         ('done', True, 49000.0, 9))
        for bad in ({'finished': True}, {'stageNo': 4, 'finished': True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.store.save_result(rid, bad)

    def test_changing_the_stages_keeps_the_results_of_the_ones_kept(self):
        rid = self.race['id']
        self.store.save_result(rid, {'stageNo': 1, 'finished': True, 'timeSeconds': 18000})
        changed = self.store.update(rid, {'stages': [{'date': '2026-11-10', 'distanceKm': 72},
                                                     {'date': '2026-11-11', 'distanceKm': 65}]})
        self.assertEqual((len(changed['stages']), changed['distanceKm']), (2, 137.0))
        self.assertEqual(changed['stages'][0]['result']['timeSeconds'], 18000.0)
        one_day = self.store.update(rid, {'stages': None, 'eventDate': '2026-12-01', 'distanceKm': 80})
        self.assertEqual((one_day['stages'], one_day['eventDate'], one_day['result']), ([], '2026-12-01', None))

    def test_bad_stages_are_refused(self):
        for stages in ([{'date': '2026-11-10'}], [{'date': '2026-11-11'}, {'date': '2026-11-10'}],
                       [{'date': '2026-11-10'}, {'date': 'mañana'}], [{'date': '2026-11-10'}, {'date': '2026-11-11', 'colour': 1}],
                       [{'date': '2026-11-10'}, {'date': '2026-11-11', 'routeFile': 'none.gpx'}]):
            with self.subTest(stages=stages), self.assertRaises(ValueError):
                self.store.create({'name': 'X', 'stages': stages})
        same_day = self.store.create({'name': 'Prólogo y etapa', 'stages': [{'date': '2026-12-05'}, {'date': '2026-12-05'}]})
        self.assertEqual(len(same_day['stages']), 2)                          # two stages the same day: fine


class GoalsApiTests(unittest.TestCase):
    def test_create_list_result_and_delete_through_the_api(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            runtime = AdapterRuntime(EnvConfig(history_db=folder / 'coach.db', record_dir=folder),
                                     Settings(mode='SIMULATOR'), start_workers=False).start()
            httpd = make_server('127.0.0.1', 0, runtime)
            base = f'http://127.0.0.1:{httpd.server_address[1]}'
            Thread(target=httpd.serve_forever, daemon=True).start()

            def call(path, body=None, method=None):
                data = None if body is None else json.dumps(body).encode()
                with urlopen(Request(base + path, data=data, method=method or ('POST' if body is not None else 'GET'),
                                     headers={'Content-Type': 'application/json'}), timeout=10) as r:
                    return r.status, json.loads(r.read())
            try:
                status, event = call('/goals', {'name': 'Sherry Bike Maratón', 'eventDate': '2027-04-25'})
                self.assertEqual((status, event['kind'], event['priority']), (201, 'MTB_MARATHON', 'B'))
                listed = call('/goals')[1]
                self.assertEqual(([g['name'] for g in listed['goals']], listed['kinds']['MTB_MARATHON']),
                                 (['Sherry Bike Maratón'], 'Maratón BTT'))
                self.assertEqual(call(f"/goals/{event['id']}", {'priority': 'A'})[1]['priority'], 'A')
                self.assertEqual(call('/calendar?month=2027-04')[1]['goals'][0]['id'], event['id'])
                with self.assertRaises(HTTPError) as ctx:
                    call('/goals', {'name': '', 'eventDate': '2027-04-25'})
                self.assertEqual(ctx.exception.code, 400)
                self.assertEqual(call(f"/goals/{event['id']}", method='DELETE')[1], {'deleted': event['id']})
                with self.assertRaises(HTTPError) as ctx:
                    call(f"/goals/{event['id']}", {'priority': 'C'})
                self.assertEqual(ctx.exception.code, 404)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
