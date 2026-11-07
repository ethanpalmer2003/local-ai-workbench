from dataclasses import dataclass


@dataclass(frozen=True)
class CodingTask:
    name: str
    prompt: str
    files: dict[str, str]
    checks: str


TASKS = (
    CodingTask(
        "whitespace",
        "Fix normalize_spaces(text) in text_utils.py: replace every run of Unicode whitespace with one ASCII space, "
        "strip leading/trailing whitespace, and preserve all non-whitespace characters. Empty input returns ''.",
        {"text_utils.py": "def normalize_spaces(text: str) -> str:\n    return text.strip().replace('  ', ' ')\n"},
        """import unittest
from text_utils import normalize_spaces

class Checks(unittest.TestCase):
    def test_cases(self):
        for source, expected in [('', ''), ('   ', ''), ('a    b', 'a b'),
                                 ('\\ta\\nb\\r\\nc ', 'a b c'), ('cafÃ©\\u2003çŒ«', 'cafÃ© çŒ«'),
                                 ('a-b.c', 'a-b.c'), (' a b ', 'a b')]:
            with self.subTest(source=source):
                self.assertEqual(normalize_spaces(source), expected)

unittest.main()
""",
    ),
    CodingTask(
        "duration",
        "Implement parse_duration(text) in duration.py. Accept surrounding whitespace and either nonnegative integer "
        "seconds, MM:SS, or HH:MM:SS. Return integer seconds. The last field and the middle field of HH:MM:SS "
        "must be 0..59; minutes in MM:SS and hours are unbounded. Reject empty strings, signs, decimals, empty "
        "fields, nondigits and more than three fields with ValueError. Use only the standard library.",
        {"duration.py": "def parse_duration(text: str) -> int:\n    raise NotImplementedError\n"},
        """import unittest
from duration import parse_duration

class Checks(unittest.TestCase):
    def test_valid(self):
        for text, value in [('0', 0), (' 75 ', 75), ('1:05', 65), ('90:00', 5400),
                            ('01:02:03', 3723), ('123:59:59', 446399)]:
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), value)
                self.assertIs(type(parse_duration(text)), int)

    def test_invalid(self):
        for text in ['', ' ', '-1', '+1', '1.5', ':1', '1:', '1:60', '1:60:00',
                     '1:00:60', '1:2:3:4', '1:x', '1: 2']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)

unittest.main()
""",
    ),
    CodingTask(
        "ledger",
        "Fix the two-file expense report. ledger.totals(csv_text) reads CSV headers category,amount, ignores "
        "empty rows, strips category whitespace, sums amounts exactly with Decimal, and returns dict[str, Decimal]. "
        "Amounts may be negative and categories may be CSV-quoted with commas. report.render(csv_text) returns "
        "category: amount lines sorted by category, formatted to two decimal places, with no trailing newline; "
        "empty/header-only input returns ''. Preserve these public function names; use only the standard library.",
        {
            "ledger.py": "def totals(csv_text):\n    return dict(line.split(',') for line in csv_text.splitlines()[1:])\n",
            "report.py": "from ledger import totals\n\ndef render(csv_text):\n    return str(totals(csv_text))\n",
        },
        """import unittest
from decimal import Decimal
from ledger import totals
from report import render

class Checks(unittest.TestCase):
    def test_totals(self):
        text = 'category,amount\\n food ,0.10\\nfood,0.20\\nfood,-0.05\\n\\n"travel, local",2.50\\n'
        self.assertEqual(totals(text), {'food': Decimal('0.25'), 'travel, local': Decimal('2.50')})
        self.assertTrue(all(isinstance(value, Decimal) for value in totals(text).values()))
        self.assertEqual(render(text), 'food: 0.25\\ntravel, local: 2.50')

    def test_sorted_and_empty(self):
        self.assertEqual(render('category,amount\\nz,1\\na,2\\n'), 'a: 2.00\\nz: 1.00')
        for text in ['', 'category,amount\\n']:
            self.assertEqual(totals(text), {})
            self.assertEqual(render(text), '')

unittest.main()
""",
    ),
)
