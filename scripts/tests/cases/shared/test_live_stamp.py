"""Live suite stamps: a passing target set is skipped while its sources are unchanged."""

import os
import unittest
from unittest.mock import patch

from scripts.tests.shared import live_stamp


class LiveStampTests(unittest.TestCase):
    def test_a_recorded_target_set_is_unchanged_whatever_the_order(self) -> None:
        store: dict[str, dict[str, str]] = {}
        with (
            patch.object(live_stamp, "_stamps", side_effect=lambda: store),
            patch.object(live_stamp, "_save", side_effect=store.update),
        ):
            live_stamp.record("launchers", ["sdcpp", "kobold"])
            self.assertTrue(live_stamp.unchanged("launchers", ["kobold", "sdcpp"]))
            self.assertFalse(live_stamp.unchanged("launchers", ["sdcpp"]))
            self.assertFalse(live_stamp.unchanged("backends", ["sdcpp", "kobold"]))

    def test_force_disables_the_skip(self) -> None:
        with patch.dict(os.environ, {"AI_LIVE_FORCE": "1"}):
            self.assertTrue(live_stamp.forced())
            self.assertFalse(live_stamp.unchanged("launchers", ["sdcpp"]))
