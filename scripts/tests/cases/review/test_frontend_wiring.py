"""Front-end wiring reads the emitted settings keys from the tree, not from a truncated text block."""

import unittest

from scripts.review.checks import frontend_wiring


class EmittedKeyTests(unittest.TestCase):
    def test_a_flat_settings_object_yields_its_keys(self):
        source = 'html = json.dumps({"port": 1, "mode": "streaming"})\n'
        self.assertEqual(frontend_wiring.literal_keys(source), ({"port", "mode"}, False))

    def test_a_nested_dict_does_not_cut_the_block_short(self):
        source = 'html = json.dumps({"outer": {"inner": 1}, "tail": True})\n'
        self.assertEqual(frontend_wiring.literal_keys(source), ({"outer", "tail"}, False))

    def test_an_expansion_is_reported_so_its_keys_can_be_resolved(self):
        keys, expands = frontend_wiring.literal_keys('html = json.dumps({"port": 1, **defaults()})\n')
        self.assertEqual(keys, {"port"})
        self.assertTrue(expands)

    def test_another_dump_call_is_not_the_settings_object(self):
        source = 'pickle = json.dumps(value)\nhtml = json.dumps({"port": 1})\n'
        self.assertEqual(frontend_wiring.literal_keys(source), ({"port"}, False))

    def test_unparsable_source_yields_nothing(self):
        self.assertEqual(frontend_wiring.literal_keys("html = json.dumps({"), (set(), False))


if __name__ == "__main__":
    unittest.main()
