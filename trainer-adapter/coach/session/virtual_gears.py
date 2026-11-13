"""Virtual gear numbers and ratios: Zwift's 24-gear table (coach/devices/zwift_hub.GEAR_RATIOS).

Used for the display (and in REPLAY). Physical shifting on the trainer is coach/devices/gear_shifter.py.
"""
from coach.devices.zwift_hub import GEAR_RATIOS, NEUTRAL_GEAR

GEAR_COUNT = len(GEAR_RATIOS)
START_GEAR = NEUTRAL_GEAR


def relative_ratio(gear: int) -> float:
    """Ratio of ``gear`` relative to neutral (gear 12 = 1.0)."""
    if not 1 <= gear <= GEAR_COUNT:
        raise ValueError(f'gear outside 1..{GEAR_COUNT}')
    return round(GEAR_RATIOS[gear - 1] / GEAR_RATIOS[START_GEAR - 1], 4)


def shift(gear: int, delta: int) -> int:
    if delta not in (-1, 1):
        raise ValueError('shift delta must be -1 or +1')
    return max(1, min(GEAR_COUNT, gear + delta))
