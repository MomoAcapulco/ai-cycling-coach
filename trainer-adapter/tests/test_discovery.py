import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from coach.bluetooth.device_finder import Claims, find_for_role
from coach.bluetooth.device_registry import DeviceRegistry
from coach.bluetooth.discovery import (Advert, CYCLING_POWER, FTMS, HEART_RATE, TRAINER, HEART_RATE_STRAP, UNKNOWN,
                       ZWIFT_CONTROLLER, ZWIFT_COMPANY_ID, ZWIFT_RIDE_SERVICE, ZWIFT_SERVICE, classify,
                       fits_role, normalize_uuid)
from coach.devices.zwift_controllers import ControllerState, battery_from_packet, decode_any, side_from_packet

RECORDINGS = Path(__file__).resolve().parent / 'fixtures'


def adv(address='AA', name=None, services=(), zwift_type=None, extra_mfr=None):
    mfr = dict(extra_mfr or {})
    if zwift_type is not None:
        mfr[ZWIFT_COMPANY_ID] = bytes([zwift_type, 0x01, 0x02])
    return Advert(address=address, name=name, service_uuids=tuple(services), manufacturer_data=mfr)


class ClassifyTests(unittest.TestCase):
    def test_uuid_normalisation(self):
        self.assertEqual(normalize_uuid('1826'), FTMS)
        self.assertEqual(normalize_uuid('0x180D'), HEART_RATE)
        self.assertEqual(normalize_uuid(FTMS.upper()), FTMS)

    def test_trainer_wins_over_relayed_hr_and_zwift_service(self):
        # A KICKR CORE 2 can advertise FTMS + CPS + HR (relayed strap) + the Zwift service.
        item = classify(adv(name='KICKR CORE 0000', services=(FTMS, CYCLING_POWER, HEART_RATE, ZWIFT_RIDE_SERVICE)))
        self.assertEqual(item.kind, TRAINER)

    def test_cycling_power_only_trainer(self):
        self.assertEqual(classify(adv(services=('1818',))).kind, TRAINER)

    def test_zwift_type_bytes(self):
        expected = {0x02: ('PLAY', 'right'), 0x03: ('PLAY', 'left'), 0x09: ('CLICK', None),
                    0x0E: ('PLAY_FW2', None), 0x07: ('RIDE', 'right'), 0x08: ('RIDE', 'left')}
        for type_byte, (model, side) in expected.items():
            with self.subTest(type_byte=type_byte):
                item = classify(adv(name='Zwift Play', services=(ZWIFT_SERVICE,), zwift_type=type_byte))
                self.assertEqual((item.kind, item.zwift_model, item.side), (ZWIFT_CONTROLLER, model, side))

    def test_zwift_service_without_manufacturer_data_has_no_side(self):
        item = classify(adv(name='Zwift Play', services=(ZWIFT_SERVICE,)))
        self.assertEqual((item.kind, item.side), (ZWIFT_CONTROLLER, None))

    def test_unknown_zwift_type(self):
        item = classify(adv(zwift_type=0x42))
        self.assertEqual((item.kind, item.zwift_model, item.side), (ZWIFT_CONTROLLER, 'UNKNOWN_ZWIFT', None))

    def test_heart_rate_only_by_service_not_name(self):
        self.assertEqual(classify(adv(name='HR50', services=('180d',))).kind, HEART_RATE_STRAP)
        self.assertEqual(classify(adv(name='HR50')).kind, UNKNOWN)

    def test_other_manufacturers_are_ignored(self):
        self.assertEqual(classify(adv(name='Phone', extra_mfr={0x004C: b'\x02\x15'})).kind, UNKNOWN)

    def test_merge_keeps_name_from_a_later_packet(self):
        first = adv(address='X', services=(ZWIFT_SERVICE,))
        later = Advert(address='X', name='Zwift Play', manufacturer_data={ZWIFT_COMPANY_ID: b'\x03'})
        merged = first.merged(later)
        self.assertEqual(merged.name, 'Zwift Play')
        self.assertEqual(classify(merged).side, 'left')

    def test_roles(self):
        left = classify(adv(zwift_type=0x03))
        unknown_side = classify(adv(zwift_type=0x0E))
        self.assertTrue(fits_role(left, 'zwift_left'))
        self.assertFalse(fits_role(left, 'zwift_right'))
        self.assertTrue(fits_role(unknown_side, 'zwift_left') and fits_role(unknown_side, 'zwift_right'))
        kickr = classify(adv(name='KICKR CORE 5A', services=(FTMS,)))
        self.assertTrue(fits_role(kickr, 'trainer'))
        self.assertFalse(fits_role(kickr, 'heart_rate'))   # it relays HR, but it is a trainer
        with self.assertRaises(ValueError):
            fits_role(kickr, 'bike')


class RealScanTests(unittest.TestCase):
    """The scan of the user's devices on 2026-11-12 (Zwift Click v2 pair + HR50 + household devices)."""

    def test_real_scan_is_classified(self):
        path = RECORDINGS / 'ble_scan_20261112_124949.json'
        if not path.exists():
            self.skipTest('scan not available')
        devices = json.loads(path.read_text())['devices']
        found = {}
        for entry in devices:
            a = entry['advert']
            advert = Advert(address=a['address'], name=a['name'], service_uuids=tuple(a['serviceUuids']),
                            manufacturer_data={int(k, 16): bytes.fromhex(v) for k, v in a['manufacturerData'].items()})
            item = classify(advert)
            if item.kind != UNKNOWN:
                found[item.address] = (item.kind, item.side, item.zwift_model)
        self.assertEqual(found, {
            'FA4E0000-0000-4000-8000-C4F41263D137': (ZWIFT_CONTROLLER, 'left', 'CLICK_V2'),
            'FA4E0000-0000-4000-8000-5A32B13A42DE': (ZWIFT_CONTROLLER, 'right', 'CLICK_V2'),
            'FA4E0000-0000-4000-8000-0DAC79FCEBF0': (HEART_RATE_STRAP, None, None),
        })


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = DeviceRegistry(Path(self.temp.name) / 'sub' / 'devices.json')

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_and_one_role_per_device(self):
        item = classify(adv(address='ab-1', name='Zwift Play', zwift_type=0x0E))
        self.registry.remember('zwift_left', item)
        self.assertEqual(self.registry.get('zwift_left')['address'], 'ab-1')
        # The first button press shows it is the right one: it moves, it is not duplicated.
        self.registry.remember('zwift_right', item, confirmed_side=True)
        self.assertIsNone(self.registry.get('zwift_left'))
        self.assertTrue(self.registry.get('zwift_right')['sideConfirmedByButton'])
        self.assertFalse(self.registry.path.with_name('devices.json.tmp').exists())

    def test_damaged_file_is_ignored(self):
        self.registry.path.parent.mkdir(parents=True)
        self.registry.path.write_text('{ broken')
        self.assertEqual(self.registry.load(), {})
        self.registry.path.write_text(json.dumps({'devices': {'bike': {'address': 'x'}, 'trainer': {'name': 'no address'}}}))
        self.assertEqual(self.registry.load(), {})

    def test_forget_and_unknown_role(self):
        self.registry.remember('trainer', classify(adv(address='T', services=(FTMS,))))
        self.registry.forget('trainer')
        self.assertIsNone(self.registry.get('trainer'))
        with self.assertRaises(ValueError):
            self.registry.get('bike')


class FakeScanner:
    """Same API as bleak.BleakScanner's class methods, over a fixed list of advertisements."""
    def __init__(self, adverts, present=None):
        self.adverts = adverts
        self.present = set(present if present is not None else [a.address for a in adverts])
        self.calls = []

    def _pair(self, a):
        device = SimpleNamespace(address=a.address, name=a.name)
        data = SimpleNamespace(local_name=a.name, service_uuids=list(a.service_uuids),
                               manufacturer_data=a.manufacturer_data, rssi=-50)
        return device, data

    async def find_device_by_address(self, address, timeout):
        self.calls.append(('address', address))
        if address in self.present:
            return SimpleNamespace(address=address, name='remembered')
        return None

    async def find_device_by_filter(self, fn, timeout):
        self.calls.append(('filter', None))
        for a in self.adverts:
            device, data = self._pair(a)
            if a.address in self.present and fn(device, data):
                return device
        return None


class FinderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = DeviceRegistry(Path(self.temp.name) / 'devices.json')
        self.scanner = FakeScanner([
            adv('PHONE', 'iPhone'),
            adv('KICKR', 'KICKR CORE 5A', services=(FTMS, HEART_RATE)),
            adv('STRAP', 'HR50 123', services=(HEART_RATE,)),
            adv('PLAY-L', 'Zwift Play', services=(ZWIFT_SERVICE,), zwift_type=0x03),
            adv('PLAY-R', 'Zwift Play', services=(ZWIFT_SERVICE,), zwift_type=0x02),
        ])

    def tearDown(self):
        self.temp.cleanup()

    def find(self, role, **kwargs):
        return asyncio.run(find_for_role(role, registry=self.registry, scanner=self.scanner, **kwargs))

    def test_scan_classifies_and_remembers(self):
        self.assertEqual(self.find('trainer').device.address, 'KICKR')
        self.assertEqual(self.find('heart_rate').device.address, 'STRAP')
        self.assertEqual(self.find('zwift_left').device.address, 'PLAY-L')
        self.assertEqual(self.find('zwift_right').device.address, 'PLAY-R')
        self.assertEqual(self.registry.get('trainer')['address'], 'KICKR')
        self.assertEqual(self.registry.get('zwift_left')['zwiftModel'], 'PLAY')

    def test_known_device_is_found_in_the_single_scan(self):
        self.find('trainer')
        self.scanner.calls.clear()
        found = self.find('trainer')
        self.assertEqual((found.source, found.device.address), ('registry', 'KICKR'))
        self.assertEqual(self.scanner.calls, [('filter', None)])   # one scan, no separate wait for it

    def test_missing_known_device_and_nothing_else(self):
        self.find('heart_rate')
        self.scanner.present.discard('STRAP')
        self.assertIsNone(self.find('heart_rate', scan_timeout=0))

    def test_explicit_id_is_never_replaced(self):
        self.assertEqual(self.find('trainer', explicit_id='KICKR').source, 'env')
        self.assertIsNone(self.find('trainer', explicit_id='GONE'))
        self.assertNotIn(('filter', None), self.scanner.calls)

    def test_trainer_found_by_type_whatever_its_name(self):
        scanner = FakeScanner([adv('NEO', 'Tacx NEO 2T', services=(FTMS,))])
        found = asyncio.run(find_for_role('trainer', registry=self.registry, scanner=scanner))
        self.assertEqual(found.device.address, 'NEO')

    def test_claimed_controllers_are_skipped(self):
        scanner = FakeScanner([adv('A', 'Zwift Play', zwift_type=0x0E), adv('B', 'Zwift Play', zwift_type=0x0E)])
        claims = Claims()
        first = asyncio.run(find_for_role('zwift_left', registry=self.registry, scanner=scanner, claims=claims))
        claims.take(first.device.address)
        second = asyncio.run(find_for_role('zwift_right', registry=self.registry, scanner=scanner, claims=claims))
        self.assertEqual({first.device.address, second.device.address}, {'A', 'B'})
        # Side unknown from the advertisement: not remembered until a button press confirms it.
        self.assertEqual(self.registry.load(), {})


class ControllerSideTests(unittest.TestCase):
    """Uses real packets recorded from the user's controllers on 2026-11-11."""

    def packets(self, suffix):
        files = sorted(RECORDINGS.glob(f'zwift_controller_v36_*_{suffix}.jsonl'))
        if not files:
            self.skipTest('recording not available')
        rows = [json.loads(line) for line in files[0].read_text().splitlines()]
        return [bytes.fromhex(r['hex']) for r in rows if r.get('event') == 'BLE_NOTIFICATION' and r.get('hex')]

    def test_recorded_left_and_right_presses_identify_their_side(self):
        # 1263D137 is the controller configured as LEFT in .env, B13A42DE the RIGHT one.
        for suffix, side in (('1263D137', 'left'), ('B13A42DE', 'right')):
            with self.subTest(side=side):
                sides = {side_from_packet(p) for p in self.packets(suffix)} - {None}
                self.assertEqual(sides, {side})

    def test_recorded_battery(self):
        levels = {battery_from_packet(p) for p in self.packets('1263D137')} - {None}
        self.assertEqual(levels, {80})

    def test_buttons_are_decoded_in_the_wrong_slot_too(self):
        state = ControllerState()
        plus = next(p for p in self.packets('B13A42DE') if 'PLUS' in (decode_any(p) or ()))
        state.on_packet('left', plus)  # the right controller connected to the left slot
        self.assertEqual(state.snapshot()['virtualGear'], 13)
        self.assertEqual(state.detected_side['left'], 'right')

    def test_battery_in_snapshot(self):
        state = ControllerState()
        self.assertEqual(state.on_packet('right', bytes.fromhex('191050')), [])
        self.assertEqual(state.snapshot()['zwiftRightBatteryPercent'], 80)
        self.assertIsNone(battery_from_packet(bytes.fromhex('1910ff')))


if __name__ == '__main__':
    unittest.main()
