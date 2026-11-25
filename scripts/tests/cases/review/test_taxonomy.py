"""The taxonomy diff flags new cross-family members and index drift, nothing else."""

import tempfile
import unittest
from pathlib import Path

from scripts.review.lists import taxonomies


def _registry() -> dict[str, taxonomies.Taxonomy]:
    return {
        "Alpha": taxonomies.Taxonomy("Alpha", "label", "owner-a", frozenset({"x", "shared"})),
        "Beta": taxonomies.Taxonomy("Beta", "label", "owner-b", frozenset({"y", "shared"})),
        "Gamma": taxonomies.Taxonomy("Gamma", "entry", "owner-c", frozenset({"z"})),
    }


class TaxonomyDiffTests(unittest.TestCase):
    def test_overlap_names_both_sides_and_the_members(self):
        self.assertEqual(taxonomies.overlapping(_registry()), [("Alpha", "Beta", frozenset({"shared"}))])

    def test_disjoint_taxonomies_report_nothing(self):
        registry = _registry()
        registry["Beta"] = taxonomies.Taxonomy("Beta", "label", "owner-b", frozenset({"y"}))
        self.assertEqual(taxonomies.overlapping(registry), [])

    def test_drift_fires_in_either_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.md"
            path.write_text("| Family | Applies to |\n| --- | --- |\n| Alpha | things |\n", encoding="utf-8")
            self.assertEqual(taxonomies.index_drift(_registry(), path), {"Beta"})
            path.write_text(
                "| Family | Applies to |\n| --- | --- |\n| Alpha | things |\n| Extra | things |\n", encoding="utf-8"
            )
            self.assertEqual(taxonomies.index_drift(_registry(), path), {"Beta", "Extra"})

    def test_live_registry_matches_the_index_and_holds_only_known_overlaps(self):
        known = taxonomies.build_taxonomies()
        self.assertEqual(taxonomies.index_drift(known), set())
        names = sorted(known)
        raw = set()
        for index, left in enumerate(names):
            for right in names[index + 1 :]:
                if known[left].members & known[right].members:
                    raw.add(frozenset((left, right)))
        self.assertEqual(raw, set(taxonomies.KNOWN_OVERLAPS))


if __name__ == "__main__":
    unittest.main()
