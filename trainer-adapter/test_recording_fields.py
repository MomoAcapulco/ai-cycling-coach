import unittest
from recording import FIELDS
class TestCaptureFields(unittest.TestCase):
    def test_explicit_grade_and_phase(self):
        for field in ('targetGradePercent','controlStatus','experimentPhase','ftmsFlags','heartRateBpm'):
            self.assertIn(field, FIELDS)
