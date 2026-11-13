"""Several devices of the same kind: remember them all, never guess (coach/bluetooth/device_finder.py)."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coach.app.server import AdapterState, make_server
from coach.bluetooth.device_finder import Ambiguous, Claims, Found, find_for_role, still_preferred
from coach.bluetooth.device_registry import DeviceRegistry
from coach.bluetooth.discovery import FTMS, HEART_RATE, classify
from tests.test_discovery import FakeScanner, adv

STRAP_A = adv('STRAP-A', 'HR50 111', services=(HEART_RATE,))
STRAP_B = adv('STRAP-B', 'Garmin HRM', services=(HEART_RATE,))
KICKR = adv('KICKR', 'KICKR CORE 5A', services=(FTMS, HEART_RATE))   # also relays HR: never a strap


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = DeviceRegistry(Path(self.temp.name) / 'devices.json')

    def tearDown(self):
        self.temp.cleanup()

    def find(self, role, adverts, present=None, **kwargs):
        scanner = FakeScanner(adverts, present)
        return asyncio.run(find_for_role(role, registry=self.registry, scanner=scanner, scan_timeout=0, **kwargs))

    def addresses(self, role):
        return [e['address'] for e in self.registry.known(role)]


class OneStrapPerDayTests(Base):
    def test_strap_a_today_strap_b_tomorrow_both_remembered(self):
        self.assertEqual(self.find('heart_rate', [STRAP_A, KICKR]).device.address, 'STRAP-A')
        found = self.find('heart_rate', [STRAP_B, KICKR])                  # day 2: only B is on
        self.assertEqual((found.source, found.device.address), ('scan', 'STRAP-B'))
        self.assertEqual(set(self.addresses('heart_rate')), {'STRAP-A', 'STRAP-B'})   # A is NOT forgotten
        found = self.find('heart_rate', [STRAP_A, KICKR])                  # day 3: A again, recognised
        self.assertEqual((found.source, found.device.address), ('registry', 'STRAP-A'))
        self.assertEqual(self.addresses('heart_rate')[0], 'STRAP-A')       # most recently used first


class TwoStrapsAtOnceTests(Base):
    def test_two_unknown_straps_are_never_guessed(self):
        result = self.find('heart_rate', [STRAP_A, STRAP_B, KICKR])
        self.assertIsInstance(result, Ambiguous)
        self.assertEqual({c['address'] for c in result.candidates}, {'STRAP-A', 'STRAP-B'})
        self.assertIn('elige uno en Ajustes', result.message())
        self.assertEqual(self.registry.known('heart_rate'), [])            # nothing remembered by chance
        self.assertEqual({c['address'] for c in self.registry.pending_json()['heart_rate']}, {'STRAP-A', 'STRAP-B'})

    def test_choosing_a_candidate_remembers_and_prefers_it(self):
        self.find('heart_rate', [STRAP_A, STRAP_B])
        self.registry.prefer('heart_rate', 'STRAP-B')
        self.assertEqual(self.registry.pending_json(), {})
        found = self.find('heart_rate', [STRAP_A, STRAP_B])
        self.assertEqual((found.source, found.device.address), ('registry', 'STRAP-B'))

    def test_a_known_strap_wins_over_an_unknown_one(self):
        self.find('heart_rate', [STRAP_A])
        found = self.find('heart_rate', [STRAP_B, STRAP_A])               # a neighbour's B is also around
        self.assertEqual(found.device.address, 'STRAP-A')
        self.assertEqual(self.addresses('heart_rate'), ['STRAP-A'])        # B was not added

    def test_both_known_and_present_last_used_unless_one_is_preferred(self):
        self.find('heart_rate', [STRAP_A])
        self.find('heart_rate', [STRAP_B])                                 # B used last
        self.assertEqual(self.find('heart_rate', [STRAP_A, STRAP_B]).device.address, 'STRAP-B')
        self.registry.prefer('heart_rate', 'STRAP-A')                     # "Usar este"
        self.assertEqual(self.find('heart_rate', [STRAP_A, STRAP_B]).device.address, 'STRAP-A')
        self.assertEqual(self.find('heart_rate', [STRAP_B]).device.address, 'STRAP-B')  # preferred absent: B
        self.assertEqual(self.find('heart_rate', [STRAP_A, STRAP_B]).device.address, 'STRAP-A')  # still preferred

    def test_any_brand_is_found_by_type(self):
        self.assertEqual(self.find('heart_rate', [STRAP_B]).device.address, 'STRAP-B')     # a Garmin, not an HR50
        nameless = adv('X', None, services=(HEART_RATE,))
        self.assertEqual(self.find('heart_rate', [nameless], present=['X']).device.address, 'X')

    def test_old_name_filters_in_env_are_ignored_with_a_note(self):
        import io
        from contextlib import redirect_stdout
        from coach.app.runtime import EnvConfig
        out = io.StringIO()
        with redirect_stdout(out):
            env = EnvConfig.from_env({'HR_DEVICE_NAME': 'HR50', 'WAHOO_DEVICE_NAME': 'KICKR CORE'})
        self.assertFalse(hasattr(env, 'hr_device_name'))
        self.assertIn('HR_DEVICE_NAME in .env is ignored', out.getvalue())
        self.assertIn('WAHOO_DEVICE_NAME in .env is ignored', out.getvalue())


class TrainerAndControllerTests(Base):
    def test_two_unknown_trainers_are_not_guessed(self):
        other = adv('NEO', 'Tacx NEO 2T', services=(FTMS,))
        self.assertIsInstance(self.find('trainer', [KICKR, other]), Ambiguous)
        self.registry.prefer('trainer', 'NEO')
        self.assertEqual(self.find('trainer', [KICKR, other]).device.address, 'NEO')

    def test_two_controllers_without_side_are_the_pair_not_ambiguous(self):
        a, b = adv('A', 'Zwift Play', zwift_type=0x0E), adv('B', 'Zwift Play', zwift_type=0x0E)
        claims = Claims()
        first = self.find('zwift_left', [a, b], claims=claims)
        self.assertIsInstance(first, Found)
        claims.take(first.device.address)
        second = self.find('zwift_right', [a, b], claims=claims)
        self.assertEqual({first.device.address, second.device.address}, {'A', 'B'})

    def test_two_left_controllers_announcing_the_side_are_ambiguous(self):
        mine, other = adv('L1', 'Zwift Click', zwift_type=0x0B), adv('L2', 'Zwift Click', zwift_type=0x0B)
        self.assertIsInstance(self.find('zwift_left', [mine, other]), Ambiguous)

    def test_a_device_known_in_another_role_is_never_a_candidate(self):
        controller = adv('C', 'Zwift Play', zwift_type=0x0E)
        self.registry.remember('zwift_right', classify(controller), confirmed_side=True)
        self.assertIsNone(self.find('zwift_left', [controller]))


class RegistryFileTests(Base):
    def test_version_1_file_is_read_and_converted(self):
        self.registry.path.write_text(json.dumps({'version': 1, 'devices': {
            'heart_rate': {'address': 'STRAP-A', 'name': 'HR50 111', 'kind': 'HEART_RATE',
                           'rememberedAtUtc': '2026-11-12T10:00:00+00:00'}}}))
        self.assertEqual(self.addresses('heart_rate'), ['STRAP-A'])
        self.find('heart_rate', [STRAP_B])
        saved = json.loads(self.registry.path.read_text())
        self.assertEqual(saved['version'], 2)
        self.assertEqual({e['address'] for e in saved['devices']['heart_rate']}, {'STRAP-A', 'STRAP-B'})

    def test_forget_one_or_all(self):
        self.find('heart_rate', [STRAP_A])
        self.find('heart_rate', [STRAP_B])
        self.registry.forget('heart_rate', 'strap-a')                     # case-insensitive
        self.assertEqual(self.addresses('heart_rate'), ['STRAP-B'])
        self.registry.forget('heart_rate')
        self.assertEqual(self.registry.load(), {})

    def test_prefer_an_unknown_address_fails(self):
        with self.assertRaises(KeyError):
            self.registry.prefer('heart_rate', 'NOPE')

    def test_still_preferred_tells_the_worker_to_switch(self):
        self.find('heart_rate', [STRAP_A])
        self.find('heart_rate', [STRAP_B])
        self.assertTrue(still_preferred(self.registry, 'heart_rate', 'STRAP-B'))   # nothing preferred yet
        self.registry.prefer('heart_rate', 'STRAP-A')
        self.assertFalse(still_preferred(self.registry, 'heart_rate', 'STRAP-B'))
        self.assertTrue(still_preferred(self.registry, 'heart_rate', 'STRAP-A'))
        self.assertTrue(still_preferred(None, 'heart_rate', 'X'))


class DevicesEndpointTests(Base):
    def setUp(self):
        super().setUp()
        self.httpd = make_server('127.0.0.1', 0, AdapterState(registry=self.registry))
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as r:
            return json.loads(r.read())

    def test_list_choose_and_forget(self):
        self.find('heart_rate', [STRAP_A, STRAP_B])                        # two unknown: pending
        listing = self.call('GET', '/devices')
        self.assertEqual(len(listing['pending']['heart_rate']), 2)
        self.assertNotIn('item', listing['pending']['heart_rate'][0])
        self.assertIn('envFilters', listing)
        chosen = self.call('POST', '/devices/heart_rate/use', {'address': 'STRAP-B'})
        self.assertEqual(chosen['known']['heart_rate'][0]['address'], 'STRAP-B')
        self.assertTrue(chosen['known']['heart_rate'][0]['preferred'])
        self.assertEqual(chosen['remembered']['heart_rate']['address'], 'STRAP-B')
        after = self.call('DELETE', '/devices/heart_rate?address=STRAP-B')
        self.assertEqual(after['known'], {})

    def test_errors(self):
        for method, path, body, code in (('POST', '/devices/heart_rate/use', {'address': 'NOPE'}, 404),
                                         ('POST', '/devices/bike/use', {'address': 'X'}, 404),
                                         ('POST', '/devices/heart_rate/use', {'address': 7}, 400),
                                         ('DELETE', '/devices/bike', None, 404)):
            with self.subTest(path=path, body=body), self.assertRaises(HTTPError) as ctx:
                self.call(method, path, body)
            self.assertEqual(ctx.exception.code, code)


if __name__ == '__main__':
    unittest.main()
