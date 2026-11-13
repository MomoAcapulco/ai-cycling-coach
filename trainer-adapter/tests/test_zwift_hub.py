import unittest

from coach.devices.zwift_hub import (GEAR_RATIOS, NEUTRAL_GEAR, RIDE_ON_TRAINER, TRAINER_HANDSHAKE_2, Physical,
                                     Simulation, decode_fields, decode_hub_command, decode_riding_data, describe,
                                     encode_hub_command, encode_hub_request, encode_varint, gear_ratio, unzigzag,
                                     zigzag)


class ZwiftHubCodecTests(unittest.TestCase):
    def test_handshake_bytes(self):
        self.assertEqual(RIDE_ON_TRAINER.hex(), '526964654f6e0201')
        self.assertEqual(TRAINER_HANDSHAKE_2.hex(), '410805')

    def test_varint_and_zigzag(self):
        self.assertEqual(encode_varint(0), b'\x00')
        self.assertEqual(encode_varint(300).hex(), 'ac02')
        self.assertEqual(encode_varint(24000).hex(), 'c0bb01')
        for v in (0, 1, -1, 40, -250, 2500):
            self.assertEqual(unzigzag(zigzag(v)), v)
        with self.assertRaises(ValueError):
            encode_varint(-1)

    def test_hub_request_for_gear_ratio(self):
        self.assertEqual(encode_hub_request(520).hex(), '00088804')

    def test_neutral_gear_and_weights_round_trip(self):
        physical = Physical.of(gear_ratio(NEUTRAL_GEAR), bike_kg=9.5, rider_kg=80)
        msg = encode_hub_command(physical=physical)
        self.assertEqual(msg[0], 0x04)
        self.assertEqual(decode_hub_command(msg),
                         {'physical': {'gearRatioX10000': 24000, 'bikeWeightX100': 950, 'riderWeightX100': 8000}})

    def test_simulation_round_trip_with_negative_grade(self):
        msg = encode_hub_command(simulation=Simulation(incline_x100=-150))
        self.assertEqual(decode_hub_command(msg)['simulation'],
                         {'windX100': 0, 'inclineX100': -150, 'cwaX10000': 5100, 'crrX100000': 400})
        self.assertEqual(decode_hub_command(encode_hub_command(simulation=Simulation(40)))['simulation']['inclineX100'], 40)

    def test_gear_table(self):
        self.assertEqual(len(GEAR_RATIOS), 24)
        self.assertEqual(gear_ratio(12), 2.40)
        self.assertEqual(list(GEAR_RATIOS), sorted(GEAR_RATIOS))
        for bad in (0, 25):
            with self.assertRaises(ValueError):
                gear_ratio(bad)

    def test_riding_data(self):
        # 1000 cm/s = 10 m/s = 36 km/h
        msg = bytes([0x03]) + bytes.fromhex('08b401') + bytes.fromhex('1050') + bytes.fromhex('18e807') + bytes.fromhex('208a01')
        self.assertEqual(decode_riding_data(msg), {'powerWatts': 180, 'cadenceRpm': 80, 'speedKph': 36.0, 'heartRateBpm': 138})
        self.assertIsNone(decode_riding_data(b'\x04\x08\x01'))
        self.assertEqual(describe(msg)['type'], 'RidingData')
        self.assertEqual(describe(b'RideOn\x01\x04'), {'type': 'RideOn', 'tail': '0104'})

    def test_real_riding_data_from_our_kickr(self):
        # First RidingData of diagnostics/zwift_hub_probe_20261112_154311.json; FTMS said 109 W, 60 rpm, 16.97 km/h.
        decoded = decode_riding_data(bytes.fromhex('03086d103c18d703200028e46a30dbb301'))
        self.assertEqual(decoded, {'powerWatts': 109, 'cadenceRpm': 60, 'speedKph': 16.96, 'heartRateBpm': 0,
                                   'unknown5': 13668, 'unknown6': 23003})

    def test_real_gear_confirmations_from_our_kickr(self):
        from coach.devices.zwift_hub import decode_hub_response
        # Answers to HubRequest 520 after gears 12, 13 and 11 (diagnostics/zwift_gear_test_20261112_155523.json).
        for hex_msg, ratio in (('3c08880412060a0440c0bb01', 24000), ('3c08880412060a0440f3cb01', 26099),
                               ('3c08880412060a0440b8ad01', 22200)):
            with self.subTest(ratio=ratio):
                self.assertEqual(decode_hub_response(bytes.fromhex(hex_msg)), {'dataId': 520, 'gearRatioX10000': ratio})
                self.assertEqual(describe(bytes.fromhex(hex_msg))['type'], 'HubResponse')

    def test_trainer_log(self):
        msg = bytes.fromhex('2a080112' + '1e' + '221c') + b'ZP: No handler for opcode 65\x00'
        self.assertEqual(describe(msg), {'type': 'TrainerLog', 'level': 1, 'text': 'ZP: No handler for opcode 65'})

    def test_decoder_survives_garbage(self):
        self.assertEqual(decode_fields(b'\x08'), [])
        self.assertEqual(decode_fields(b'\x0a\x05\x01'), [])
        self.assertEqual(describe(b'\x2a\xff'), {'type': 'TrainerLog', 'level': None, 'text': None})
        self.assertEqual(describe(b'\x3e\x08\x41\x10\x01')['type'], '0x3E')


if __name__ == '__main__':
    unittest.main()
