"""Gate timings are medians over retained logs; a corrupt file is skipped, not fatal."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.review import gate_times


def _write(folder: Path, name: str, sections: list[tuple[str, float]], total: float) -> None:
    payload = {
        "total_seconds": total,
        "work_seconds": total + 1.0,
        "sections": [{"section": section, "seconds": seconds, "status": 0} for section, seconds in sections],
    }
    (folder / name).write_text(json.dumps(payload), encoding="utf-8")


class GateTimesTests(unittest.TestCase):
    def test_medians_cover_sections_and_both_totals(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "a.json", [("lint", 1.0), ("types", 9.0)], 10.0)
            _write(root, "b.json", [("lint", 3.0), ("types", 7.0)], 12.0)
            _write(root, "c.json", [("lint", 2.0)], 5.0)
            rows = {row.section: row for row in gate_times.medians(gate_times.summaries(root))}
        self.assertEqual((rows["lint"].median_seconds, rows["lint"].runs), (2.0, 3))
        self.assertEqual((rows["types"].median_seconds, rows["types"].runs), (8.0, 2))
        self.assertEqual(rows["total_seconds"].median_seconds, 10.0)
        self.assertEqual(rows["work_seconds"].median_seconds, 11.0)

    def test_a_missing_dir_and_a_corrupt_file_yield_what_survives(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "broken.json").write_text("{nope", encoding="utf-8")
            self.assertEqual(gate_times.medians(gate_times.summaries(root / "absent")), [])
            self.assertEqual(gate_times.report(root), render_table_header_only())
            _write(root, "a.json", [("lint", 1.0)], 2.0)
            self.assertEqual(len(gate_times.medians(gate_times.summaries(root))), 3)


def render_table_header_only() -> str:
    from scripts.shared.tables import render_table

    return render_table([], ["section", "median_s", "runs"])


if __name__ == "__main__":
    unittest.main()
