"""The dead-code section keeps deletion-shaped findings and drops names something outside reads."""

import unittest

from scripts.review.dead_code import RETIRED, findings


class FindingTests(unittest.TestCase):
    def test_a_function_and_a_class_with_no_reader_are_reported(self):
        output = (
            "scripts/x.py:4: unused function 'orphan' (60% confidence)\n"
            "scripts/x.py:9: unused class 'Leftover' (60% confidence)\n"
        )
        self.assertEqual(len(findings(output)), 2)

    def test_protocol_attributes_methods_and_variables_are_not_reported(self):
        output = (
            "scripts/x.py:4: unused attribute 'close_connection' (60% confidence)\n"
            "scripts/x.py:8: unused method 'do_GET' (60% confidence)\n"
            "scripts/config/models/ids.py:7: unused variable 'ASR_WHISPERCPP_BASE' (60% confidence)\n"
        )
        self.assertEqual(findings(output), [])

    def test_unreachable_code_is_reported(self):
        output = "scripts/x.py:5: unreachable code after 'return' (100% confidence)\n"
        self.assertEqual(len(findings(output)), 1)

    def test_the_retired_pipeline_stays_silent_until_its_decision(self):
        name = next(iter(RETIRED))
        self.assertEqual(findings(f"{name}:339: unused function '_apply_buffer' (60% confidence)\n"), [])

    def test_the_retired_exclusion_survives_an_absolute_path(self):
        name = next(iter(RETIRED))
        output = f"C:/AI/{name}:339: unused function '_apply_buffer' (60% confidence)\n"
        self.assertEqual(findings(output), [])


if __name__ == "__main__":
    unittest.main()
