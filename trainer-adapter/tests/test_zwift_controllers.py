import unittest
from coach.devices.zwift_controllers import ControllerState, decode_packet

RELEASED = bytes.fromhex('2308ffffffff0f')


def make_button(side, button):
    from coach.devices.zwift_controllers import BUTTON_MASKS, ALL_RELEASED
    mask = BUTTON_MASKS[side][button]
    return bytes.fromhex('2308') + (ALL_RELEASED & ~mask).to_bytes(5, 'little')


class ZwiftControllerTests(unittest.TestCase):
    def test_button_mapping(self):
        for side, buttons in [('left', ['MINUS', 'UP', 'DOWN', 'LEFT', 'RIGHT']),
                              ('right', ['PLUS', 'Z', 'B', 'A', 'Y'])]:
            for button in buttons:
                with self.subTest(side=side, button=button):
                    self.assertEqual(decode_packet(make_button(side, button), side), {button})

    def test_gear_changes_only_on_button_down(self):
        state = ControllerState()
        self.assertEqual(state.on_packet('right', make_button('right', 'PLUS'))[0]['gear'], 13)
        self.assertEqual(state.on_packet('right', make_button('right', 'PLUS')), [])
        state.on_packet('right', RELEASED)
        state.on_packet('left', make_button('left', 'MINUS'))
        self.assertEqual(state.snapshot()['virtualGear'], 12)

    def test_bounds(self):
        state = ControllerState(initial_gear=24)
        state.on_packet('right', make_button('right', 'PLUS'))
        self.assertEqual(state.snapshot()['virtualGear'], 24)
        state = ControllerState(initial_gear=1)
        state.on_packet('left', make_button('left', 'MINUS'))
        self.assertEqual(state.snapshot()['virtualGear'], 1)

    def test_other_buttons_do_not_shift(self):
        state = ControllerState()
        state.on_packet('right', make_button('right', 'Z'))
        state.on_packet('left', make_button('left', 'UP'))
        self.assertEqual(state.snapshot()['virtualGear'], 12)

    def test_non_button_packet(self):
        self.assertIsNone(decode_packet(bytes.fromhex('2a00'), 'left'))

if __name__ == '__main__':
    unittest.main()
