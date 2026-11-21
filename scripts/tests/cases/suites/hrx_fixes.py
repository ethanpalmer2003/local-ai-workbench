"""The HRX fix registry: a marker proves a fix is present, a patch proves it is still needed."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.download.frameworks.llamacpp.hrx import fixes
from scripts.tests.shared.paths import CasePaths


def result(code: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], code, "", "")


class FixStateTests(unittest.TestCase):
    def record(self, folder: Path) -> tuple[fixes.Fix, Path]:
        root = folder / "llama.cpp"
        root.mkdir()
        (root / "file.txt").write_text("plain\n", encoding="utf-8")
        patch_file = folder / "one.patch"
        patch_file.write_text("--- a/file.txt\n+++ b/file.txt\n", encoding="utf-8")
        return fixes.Fix("one", "llama.cpp", "file.txt", "fixed", patch_file, "why"), root

    def test_state_reads_the_marker_first_then_the_patch(self):
        with CasePaths(__file__).temporary_directory() as folder:
            record, root = self.record(Path(folder))
            with (
                patch.object(fixes, "roots", return_value={"llama.cpp": root}),
                patch.object(fixes, "_git", return_value=result(0)) as git,
            ):
                self.assertIs(fixes.state(record), fixes.FixState.NEEDED)
                fixes.apply(record)
                git.assert_called_with(root, "apply", str(record.patch))
                (root / "file.txt").write_text("fixed\n", encoding="utf-8")
                self.assertIs(fixes.state(record), fixes.FixState.APPLIED)

    def test_a_moved_upstream_reports_drifted_instead_of_pretending(self):
        with CasePaths(__file__).temporary_directory() as folder:
            record, root = self.record(Path(folder))
            with (
                patch.object(fixes, "roots", return_value={"llama.cpp": root}),
                patch.object(fixes, "_git", return_value=result(1)),
            ):
                self.assertIs(fixes.state(record), fixes.FixState.DRIFTED)

    def test_ensure_applies_what_it_can_and_counts_what_it_cannot(self):
        with CasePaths(__file__).temporary_directory() as folder:
            record, root = self.record(Path(folder))
            with (
                patch.object(fixes, "roots", return_value={"llama.cpp": root}),
                patch.object(fixes, "records", return_value=(record,)),
                patch.object(fixes, "_git", return_value=result(1)),
            ):
                self.assertEqual(fixes.ensure(), 0)

    def test_every_registered_fix_names_an_existing_patch_and_marker(self):
        records = fixes.records()
        self.assertTrue(records)
        for record in records:
            with self.subTest(fix=record.identity):
                self.assertTrue(record.patch.is_file(), str(record.patch))
                self.assertIn(record.repository, fixes.roots())
                self.assertTrue(record.reason)
                self.assertFalse(Path(record.marker_file).is_absolute(), record.marker_file)
