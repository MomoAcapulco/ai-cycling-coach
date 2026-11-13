"""DISPLAY-ONLY virtual gearing model. No trainer control or BLE writes.

Approximate, configurable relative ratios (not Zwift's proprietary ratios).
Use solely for UI and unit tests until a safe physics model is validated.
"""
from math import pow

GEAR_COUNT = 24
START_GEAR = 12
STEP = 1.08


def relative_ratio(gear: int) -> float:
    if not 1 <= gear <= GEAR_COUNT:
        raise ValueError('gear outside 1..24')
    return round(pow(STEP, gear - START_GEAR), 4)


def shift(gear: int, delta: int) -> int:
    if delta not in (-1, 1):
        raise ValueError('shift delta must be -1 or +1')
    return max(1, min(GEAR_COUNT, gear + delta))
