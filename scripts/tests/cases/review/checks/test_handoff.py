"""The handoff bundle ranks the files that ask for judgment and leaves the mechanical findings out."""

import ast
import json
import unittest
import unittest.mock
from pathlib import Path

from scripts.review import handoff
from scripts.tests.shared.paths import CasePaths


def handler(source: str) -> ast.ExceptHandler:
    tree = ast.parse(source)
    return next(node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler))


class HandlerTests(unittest.TestCase):
    def test_a_handler_that_does_nothing_is_silent(self):
        for source in (
            "try:\n    f()\nexcept Exception:\n    pass\n",
            "try:\n    f()\nexcept Exception:\n    return None\n",
            "try:\n    f()\nexcept Exception:\n    return False\n",
            "try:\n    f()\nexcept Exception:\n    continue\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(handoff.silent_except(handler(source)))

    def test_a_handler_that_raises_logs_or_returns_a_value_is_not_silent(self):
        for source in (
            "try:\n    f()\nexcept Exception:\n    raise\n",
            "try:\n    f()\nexcept Exception:\n    print('failed')\n",
            "try:\n    f()\nexcept Exception:\n    return 0\n",
        ):
            with self.subTest(source=source):
                self.assertFalse(handoff.silent_except(handler(source)))

    def test_a_broad_handler_catches_everything(self):
        self.assertTrue(handoff.broad_except(handler("try:\n    f()\nexcept:\n    pass\n")))
        self.assertTrue(handoff.broad_except(handler("try:\n    f()\nexcept Exception:\n    pass\n")))
        self.assertTrue(handoff.broad_except(handler("try:\n    f()\nexcept (OSError, Exception):\n    pass\n")))
        self.assertFalse(handoff.broad_except(handler("try:\n    f()\nexcept OSError:\n    pass\n")))

    def test_a_suppress_block_weighs_the_same_as_the_try_form(self):
        source = (
            '"""Module."""\n\n'
            "import contextlib\n\n\n"
            "def quietly() -> None:\n"
            "    with contextlib.suppress(OSError):\n"
            "        open('x')\n"
            "    with contextlib.suppress(Exception):\n"
            "        open('y')\n"
        )
        self.assertEqual(handoff.suppression_sites(ast.parse(source)), [(7, False), (9, True)])


class FullRunTests(unittest.TestCase):
    def run_record(self, folder: Path, created: str, stages: str) -> Path:
        summary = folder / "20261120-133000"
        summary.mkdir(parents=True)
        payload = f'{{"title": "validate", "created": "{created}", "total_seconds": 653.0, "stages": {stages}}}'
        (summary / "summary.json").write_text(payload, encoding="utf-8")
        return folder

    def test_a_recorded_run_is_read_with_every_stage_verdict(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            self.run_record(
                root,
                "2026-11-20T13:31:00",
                '[{"key": "gate", "status": "ok", "seconds": 55.0, "high": 80},'
                ' {"key": "launchers", "status": "skipped", "seconds": 1.0, "high": 380}]',
            )
            run = handoff.last_full_run(root)
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.created, "2026-11-20T13:31:00")
        self.assertEqual([key for key, _, _ in run.stages], ["gate", "launchers"])
        self.assertEqual([status for _, status, _ in run.stages], ["ok", "skipped"])

    def test_an_absent_record_leaves_the_bundle_blocked(self):
        self.assertEqual(handoff.last_full_run(Path("missing")), None)
        issues = handoff.full_run_issues(None)
        self.assertEqual(len(issues), 1)
        self.assertIn("No recorded full validation", issues[0])

    def test_a_failed_stage_blocks_the_bundle_and_is_named(self):
        run = handoff.FullRun(
            created="2026-11-20T13:31:00", total_seconds=90.0, stages=[("gate", "ok", 55.0), ("suite", "failed", 30.0)]
        )
        self.assertIn("failed at suite", handoff.full_run_issues(run, current={})[0])

    def test_matching_fingerprints_accept_a_run_a_later_commit_followed(self):
        run = handoff.FullRun(
            created="2026-11-20T13:31:00",
            total_seconds=653.0,
            stages=[("gate", "ok", 55.0), ("suite", "ok", 30.0)],
            fingerprints={"gate": "a", "suite": "b"},
        )
        self.assertEqual(handoff.full_run_issues(run, current={"gate": "a", "suite": "b"}), [])

    def test_a_stage_whose_inputs_moved_blocks_the_bundle(self):
        run = handoff.FullRun(
            created="2026-11-20T13:31:00",
            total_seconds=653.0,
            stages=[("gate", "ok", 55.0), ("suite", "ok", 30.0)],
            fingerprints={"gate": "a", "suite": "b"},
        )
        issues = handoff.full_run_issues(run, current={"gate": "moved", "suite": "b"})
        self.assertIn("inputs of gate changed", issues[0])
        self.assertIn("skipped", issues[0])

    def test_the_brief_states_the_run_and_every_stage(self):
        run = handoff.FullRun(
            created="2026-11-20T13:31:00",
            total_seconds=653.0,
            stages=[("gate", "ok", 55.0), ("launchers", "skipped", 1.0)],
        )
        text = "\n".join(handoff.full_run_report(run))
        self.assertIn("2026-11-20T13:31:00", text)
        self.assertIn("gate ok, launchers skipped", text)
        self.assertIn("skipped live stage had no changed source", text)
        clean = handoff.FullRun(created="2026-11-20T13:31:00", total_seconds=653.0, stages=[("gate", "ok", 55.0)])
        self.assertNotIn("skipped live stage", "\n".join(handoff.full_run_report(clean)))

    def test_the_brief_points_at_the_reviewer_role(self):
        record: handoff.FileRecord = {
            "path": "scripts/pkg/module.py",
            "lines": 3,
            "functions": [],
            "classes": [],
            "silent_excepts": [],
            "broad_excepts": [],
            "undocumented": [],
        }
        text = "\n".join(handoff.brief([record]))
        self.assertIn("## The full test behind this bundle", text)
        self.assertIn("REVIEW-REQUEST.md", text)


class BundleTests(unittest.TestCase):
    def test_a_file_record_carries_the_call_shapes_and_the_smells(self):
        source = (
            '"""Module."""\n\n\n'
            "def documented(value: int) -> str:\n"
            '    """Say it."""\n'
            "    return str(value)\n\n\n"
            "def undocumented(value):\n"
            "    try:\n        return int(value)\n"
            "    except Exception:\n        pass\n"
        )
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "scripts" / "pkg").mkdir(parents=True)
            path = root / "scripts" / "pkg" / "module.py"
            path.write_text(source, encoding="utf-8")
            record = handoff.file_record(path, root)
        self.assertEqual(record["path"], "scripts/pkg/module.py")
        self.assertEqual([item["name"] for item in record["functions"]], ["documented", "undocumented"])
        self.assertEqual(record["functions"][0]["signature"], "(value: int) -> str")
        self.assertEqual(record["undocumented"], [record["functions"][1]["line"]])
        self.assertEqual(len(record["silent_excepts"]), 1)
        self.assertEqual(len(record["broad_excepts"]), 1)

    def test_the_brief_names_the_heavy_files_and_leaves_the_gate_alone(self):
        records: list[handoff.FileRecord] = [
            {
                "path": "scripts/heavy.py",
                "lines": 400,
                "functions": [{"name": "run", "line": 1, "span": 90, "signature": "() -> None", "documented": True}],
                "classes": [],
                "silent_excepts": [10, 20],
                "broad_excepts": [30],
                "undocumented": [],
            },
            {
                "path": "scripts/calm.py",
                "lines": 20,
                "functions": [],
                "classes": [],
                "silent_excepts": [],
                "broad_excepts": [],
                "undocumented": [],
            },
        ]
        text = "\n".join(handoff.brief(records, ranked=1))
        self.assertIn("| scripts/heavy.py | 400 | 1 | 2 | 1 | 1 |", text)
        self.assertNotIn("scripts/calm.py", text)
        # - the not-to-report rules live in the request, so the brief points there instead of restating them
        self.assertNotIn("Do not spend judgment on them", text)

    def test_a_path_option_narrows_the_index_to_one_subtree(self):
        with CasePaths(__file__).temporary_directory() as folder:
            workspace = Path(folder)
            keep = workspace / "scripts" / "launchers" / "a.py"
            keep.parent.mkdir(parents=True)
            keep.write_text("VALUE = 1\n", encoding="utf-8")
            other = workspace / "scripts" / "tools" / "b.py"
            other.parent.mkdir(parents=True)
            other.write_text("VALUE = 2\n", encoding="utf-8")
            records = handoff.index(workspace, workspace / "scripts" / "launchers")
        self.assertEqual([record["path"] for record in records], ["scripts/launchers/a.py"])

    def test_the_brief_rolls_the_weight_up_by_area(self):
        records: list[handoff.FileRecord] = [
            {
                "path": "scripts/launchers/a.py",
                "lines": 10,
                "functions": [],
                "classes": [],
                "silent_excepts": [1],
                "broad_excepts": [],
                "undocumented": [],
            },
            {
                "path": "scripts/tools/b.py",
                "lines": 10,
                "functions": [],
                "classes": [],
                "silent_excepts": [],
                "broad_excepts": [],
                "undocumented": [],
            },
        ]
        text = "\n".join(handoff.brief(records))
        self.assertIn("| scripts/launchers | 1 | 3 |", text)
        self.assertIn("| scripts/tools | 1 | 0 |", text)

    def test_evidence_reads_the_accepted_pairs_and_a_live_similarity_report(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            baseline = root / "duplicate-baseline.json"
            baseline.write_text('{"pairs": {"a.py|b.py": 2}}', encoding="utf-8")
            (root / "x.py").write_text("def run():\n    pass\n", encoding="utf-8")
            (root / "y.py").write_text("def run():\n    pass\n", encoding="utf-8")
            report_folder = root / "similarity" / "1800000000000000000"
            report_folder.mkdir(parents=True)
            (report_folder / "report.json").write_text(
                '{"created": "2026-11-16", "threshold": 0.95, "sources": {"x.py": "1"}, '
                '"findings": [{"a": "x.py :: run", "b": "y.py :: run", "best": 0.99}]}',
                encoding="utf-8",
            )
            with (
                unittest.mock.patch.object(handoff, "DUPLICATE_BASELINE", baseline),
                unittest.mock.patch.object(handoff, "SIMILARITY_ROOT", root / "similarity"),
                unittest.mock.patch.object(handoff, "changed_since_report", return_value=0),
            ):
                text = "\n".join(handoff.evidence_report(root=root))
        self.assertIn("| a.py <-> b.py | 2 |", text)
        self.assertIn("| x.py :: run | y.py :: run | 0.99 |", text)
        self.assertIn("0 file(s) changed since", text)

    def test_a_pair_naming_a_symbol_the_tree_lost_is_dropped_and_flagged(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "x.py").write_text("def run():\n    pass\n", encoding="utf-8")
            (root / "y.py").write_text("def run():\n    pass\n", encoding="utf-8")
            report_folder = root / "similarity" / "1800000000000000000"
            report_folder.mkdir(parents=True)
            (report_folder / "report.json").write_text(
                '{"created": "2026-11-16", "threshold": 0.95, "findings": ['
                '{"a": "x.py :: run", "b": "y.py :: run", "best": 0.99}, '
                '{"a": "x.py :: gone", "b": "y.py :: run", "best": 0.98}]}',
                encoding="utf-8",
            )
            with (
                unittest.mock.patch.object(handoff, "DUPLICATE_BASELINE", root / "absent.json"),
                unittest.mock.patch.object(handoff, "SIMILARITY_ROOT", root / "similarity"),
                unittest.mock.patch.object(handoff, "changed_since_report", return_value=0),
            ):
                text = "\n".join(handoff.evidence_report(root=root))
        self.assertIn("| x.py :: run | y.py :: run | 0.99 |", text)
        self.assertNotIn("x.py :: gone", text)
        self.assertIn("1 pair(s) name a file or symbol the tree no longer has", text)

    def test_a_clean_screen_is_the_answer_even_with_no_pair(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            report_folder = root / "similarity" / "1800000000000000000"
            report_folder.mkdir(parents=True)
            (report_folder / "report.json").write_text(
                '{"created": "2026-11-19", "threshold": 0.95, "findings": []}', encoding="utf-8"
            )
            with (
                unittest.mock.patch.object(handoff, "DUPLICATE_BASELINE", root / "absent.json"),
                unittest.mock.patch.object(handoff, "SIMILARITY_ROOT", root / "similarity"),
            ):
                text = "\n".join(handoff.evidence_report(root=root))
        self.assertIn("No pair cleared the threshold in that run.", text)
        self.assertNotIn("None available", text)

    def test_the_changed_count_reads_the_manifest_the_report_stored(self):
        with unittest.mock.patch.object(handoff.staleness, "manifest", return_value={"a.py": "2"}):
            self.assertEqual(handoff.changed_since_report({"a.py": "1"}), 1)
            self.assertEqual(handoff.changed_since_report({"a.py": "2"}), 0)
            self.assertEqual(handoff.changed_since_report({"gone.py": "1"}), 1)
        self.assertEqual(handoff.changed_since_report({}), 0)
        self.assertEqual(handoff.changed_since_report(None), 0)

    def test_a_dropped_pair_is_its_own_reason_to_rerun_the_screen(self):
        evidence = handoff.SimilarityEvidence(
            created="2026-11-19T00:00:00", threshold=0.95, changed=0, findings=[], dropped=2
        )
        self.assertIn("2 pair(s) name a file or symbol", handoff.stale_note(evidence) or "")

    def test_evidence_says_so_when_the_opt_in_checks_have_not_run(self):
        with CasePaths(__file__).temporary_directory() as folder:
            missing = Path(folder) / "absent"
            with (
                unittest.mock.patch.object(handoff, "DUPLICATE_BASELINE", missing),
                unittest.mock.patch.object(handoff, "SIMILARITY_ROOT", missing),
            ):
                text = "\n".join(handoff.evidence_report())
        self.assertIn("None recorded", text)
        self.assertIn("None available", text)

    def test_a_stale_screen_is_flagged(self):
        finding: handoff.SimilarityFinding = {"a": "x", "b": "y", "best": 0.99}
        fresh = handoff.SimilarityEvidence(created="2026-11-19T00:00:00", threshold=0.95, changed=1, findings=[finding])
        changed = handoff.SimilarityEvidence(created="2026-11-19T00:00:00", threshold=0.95, changed=40, findings=[])
        old = handoff.SimilarityEvidence(created="2020-01-01T00:00:00", threshold=0.95, changed=1, findings=[])
        self.assertIsNone(handoff.stale_note(fresh))
        self.assertIn("40 changed file(s)", handoff.stale_note(changed) or "")
        self.assertIn("days old", handoff.stale_note(old) or "")

    def test_the_request_names_the_files_and_the_gate_it_leaves_alone(self):
        records: list[handoff.FileRecord] = [
            {
                "path": "scripts/launchers/a.py",
                "lines": 10,
                "functions": [],
                "classes": [],
                "silent_excepts": [],
                "broad_excepts": [],
                "undocumented": [],
            }
        ]
        text = "\n".join(handoff.review_request(records))
        self.assertIn("- scripts/launchers/a.py", text)
        self.assertIn("What not to spend the review on", text)
        self.assertIn("a deterministic check already fails on", text)
        # - the request asks for a general review, so it states no checklist of questions to answer
        self.assertIn("from your own knowledge", text)
        self.assertNotIn("Is any abstraction", text)
        # - the exclusions focus the effort without bounding what a reviewer may propose
        self.assertIn("a library this repository does not have", text)
        self.assertIn("rather than treat it as the whole rubric", text)

    def test_a_run_writes_the_brief_the_request_and_the_index(self):
        record: handoff.FileRecord = {
            "path": "scripts/pkg/module.py",
            "lines": 3,
            "functions": [],
            "classes": [],
            "silent_excepts": [],
            "broad_excepts": [],
            "undocumented": [],
        }
        with CasePaths(__file__).temporary_directory() as folder:
            destination = Path(folder) / "bundle"
            run = handoff.FullRun(
                created="2026-11-20T13:31:00",
                total_seconds=653.0,
                stages=[("gate", "ok", 55.0)],
                fingerprints={"gate": ""},
            )
            with (
                unittest.mock.patch.object(handoff, "index", return_value=[record]),
                unittest.mock.patch.object(handoff, "last_full_run", return_value=run),
                unittest.mock.patch.object(handoff.validate, "stage_fingerprints", return_value={"gate": ""}),
            ):
                self.assertEqual(handoff.main(["--out", str(destination)]), 0)
            self.assertTrue((destination / "HANDOFF.md").is_file())
            self.assertTrue((destination / "REVIEW-REQUEST.md").is_file())
            index = json.loads((destination / "ast_map.json").read_text(encoding="utf-8"))
        self.assertEqual(index["files"][0]["path"], "scripts/pkg/module.py")

    def test_a_run_without_a_full_validation_writes_nothing(self):
        with CasePaths(__file__).temporary_directory() as folder:
            destination = Path(folder) / "bundle"
            with unittest.mock.patch.object(handoff, "last_full_run", return_value=None):
                self.assertEqual(handoff.main(["--out", str(destination)]), 1)
            self.assertFalse(destination.exists())


class RetentionTests(unittest.TestCase):
    def test_a_new_bundle_moves_every_bundle_but_the_newest_two_to_trash(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            for name in ("1", "2", "3"):
                (root / name).mkdir()
            newest = root / "4"
            newest.mkdir()
            moved: list[Path] = []
            with (
                unittest.mock.patch.object(handoff.cleanup, "superseded", wraps=handoff.cleanup.superseded) as rule,
                unittest.mock.patch.object(
                    handoff.cleanup, "move_to_trash", side_effect=lambda paths, stamp, dry_run: moved.extend(paths)
                ),
            ):
                handoff.prune_superseded(newest)
        self.assertEqual([item.name for item in moved], ["2", "1"])
        self.assertEqual(rule.call_args.kwargs["keep"], handoff.HANDOFF_KEEP)

    def test_a_folder_with_two_bundles_moves_nothing(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            for name in ("1", "2"):
                (root / name).mkdir()
            with unittest.mock.patch.object(handoff.cleanup, "move_to_trash", return_value=0):
                self.assertEqual(handoff.prune_superseded(root / "2"), [])

    def test_a_bundle_holding_a_saved_review_is_never_pruned(self):
        # - the reviewer's findings are not this builder's file to move
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            for name in ("1", "2", "3", "4"):
                (root / name).mkdir()
            (root / "1" / "REVIEW.md").write_text("# Findings\n", encoding="utf-8")
            moved: list[Path] = []
            with unittest.mock.patch.object(
                handoff.cleanup, "move_to_trash", side_effect=lambda paths, stamp, dry_run: moved.extend(paths)
            ):
                handoff.prune_superseded(root / "4")
        self.assertEqual([item.name for item in moved], ["2"])
