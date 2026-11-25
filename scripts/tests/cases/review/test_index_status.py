"""Index sizes come from the live stores, so the report cannot drift from them."""

import unittest
from pathlib import Path

from scripts.review.lists import index_status


class IndexStatusTests(unittest.TestCase):
    def test_both_indexes_report_positive_counts(self):
        rows = {row.name: row for row in index_status.status()}
        self.assertEqual(set(rows), {"codebase-memory", "graphify"})
        for row in rows.values():
            self.assertGreater(row.nodes, 0, row.name)
            self.assertGreater(row.edges, 0, row.name)

    def test_missing_stores_report_themselves_instead_of_failing(self):
        import sqlite3
        import tempfile

        missing = Path("definitely-not-here")
        self.assertEqual(index_status.codebase_status(missing).nodes, 0)
        self.assertEqual(index_status.graphify_status(missing).nodes, 0)
        self.assertIn("no readable database", index_status.codebase_status(missing).detail)
        self.assertIn("no readable graph", index_status.graphify_status(missing).detail)
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "empty.db"
            connection = sqlite3.connect(str(db))
            try:
                with connection:
                    connection.execute("create table projects (name text, indexed_at text, root_path text)")
                    connection.execute("create table nodes (id text, project text, file_path text)")
                    connection.execute("create table edges (id text, project text)")
            finally:
                connection.close()
            self.assertIn("not indexed", index_status.codebase_status(db).detail)

    def test_graphify_groups_match_the_labels_file(self):
        import json

        labels = json.loads((index_status.GRAPH_JSON.parent / ".graphify_labels.json").read_text(encoding="utf-8"))
        row = next(row for row in index_status.status() if row.name == "graphify")
        self.assertEqual(row.groups, f"{len(labels)} communities")


if __name__ == "__main__":
    unittest.main()
