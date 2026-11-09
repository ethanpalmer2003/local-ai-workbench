"""Run provenance: what a long run records about the build, weights, settings and corpus.

Git is faked here: the model-free suite forbids starting processes, and the real command runs
whenever a benchmark records its provenance.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.benchmarks.shared import provenance
from scripts.config import project_config

COMMIT = "a" * 40


def fake_git(command, **_kwargs):
    """Answer a git call the way a clean checkout would; keep the command for assertions."""
    if "--show-toplevel" in command:
        return subprocess.CompletedProcess(command, 0, stdout=f"{command[2]}\n")
    output = f"{COMMIT}\n" if "rev-parse" in command else ""
    return subprocess.CompletedProcess(command, 0, stdout=output)


class WorkspaceTests(unittest.TestCase):
    def test_the_workspace_records_a_commit_and_a_dirty_flag(self):
        with patch.object(provenance.subprocess, "run", side_effect=fake_git):
            state = provenance.workspace_state()
        self.assertEqual(state["path"], str(project_config.BASE_DIR))
        self.assertEqual(state["commit"], COMMIT)
        self.assertFalse(state["dirty"])

    def test_uncommitted_changes_are_visible_in_the_record(self):
        def dirty_git(command, **_kwargs):
            if "--show-toplevel" in command:
                return subprocess.CompletedProcess(command, 0, stdout=f"{command[2]}\n")
            output = f"{COMMIT}\n" if "rev-parse" in command else " M scripts/x.py\n"
            return subprocess.CompletedProcess(command, 0, stdout=output)

        with patch.object(provenance.subprocess, "run", side_effect=dirty_git):
            self.assertTrue(provenance.git_state(project_config.BASE_DIR)["dirty"])

    def test_a_folder_inside_the_workspace_does_not_borrow_its_commit(self):
        def nested_git(command, **_kwargs):
            top = str(project_config.BASE_DIR) if "--show-toplevel" in command else ""
            return subprocess.CompletedProcess(command, 0, stdout=top + "\n")

        install = Path(project_config.BASE_DIR) / "frameworks" / "llamacpp"
        with patch.object(provenance.subprocess, "run", side_effect=nested_git):
            self.assertEqual(provenance.git_state(install), {"commit": None, "dirty": None})

    def test_a_folder_outside_a_checkout_records_no_commit_instead_of_failing(self):
        failed = subprocess.CalledProcessError(128, "git")
        with patch.object(provenance.subprocess, "run", side_effect=failed):
            state = provenance.git_state(Path("not-a-repo"))
        self.assertEqual(state, {"commit": None, "dirty": None})

    def test_a_framework_identity_names_its_install_folder(self):
        with patch.object(provenance.subprocess, "run", side_effect=fake_git):
            state = provenance.framework_state("lemonade_server")
        self.assertEqual(state["key"], "lemonade_server")
        self.assertEqual(state["dir"], str(project_config.component("lemonade_server").framework_dir))
        self.assertEqual(state["commit"], COMMIT)


class FileIdentityTests(unittest.TestCase):
    def test_a_present_weight_records_size_and_modification_time(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.gguf"
            path.write_bytes(b"weights")
            identity = provenance.file_identity("chat", path)
        self.assertTrue(identity["present"])
        self.assertEqual(identity["bytes"], 7)
        self.assertIn("modified", identity)

    def test_an_absent_weight_stays_visible_instead_of_being_dropped(self):
        identity = provenance.file_identity("chat", Path("missing.gguf"))
        self.assertFalse(identity["present"])
        self.assertNotIn("bytes", identity)


class CorpusTests(unittest.TestCase):
    def test_corpus_state_attaches_the_download_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "download.json").write_text(json.dumps({"clips": [{"id": "en-0"}]}), encoding="utf-8")
            state = provenance.corpus_state({"corpus": "google/fleurs"}, root)
        self.assertEqual(state["corpus"], "google/fleurs")
        self.assertEqual(state["downloaded"]["clips"][0]["id"], "en-0")

    def test_a_corpus_without_download_evidence_is_not_claimed_as_downloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            state = provenance.corpus_state({"corpus": "google/fleurs"}, Path(folder))
        self.assertIsNone(state["downloaded"])


class BlockTests(unittest.TestCase):
    def test_the_block_carries_every_part_a_later_run_needs_to_compare(self):
        with patch.object(provenance.subprocess, "run", side_effect=fake_git):
            block = provenance.block(
                subject="example",
                config={"tokens": 8},
                frameworks=[{"key": "llamacpp", "commit": COMMIT}],
                models=[{"label": "chat", "present": True}],
                corpus={"corpus": "google/fleurs", "manifest_sha256": "ff"},
            )
        self.assertEqual(block["subject"], "example")
        self.assertIn("recorded_at", block)
        self.assertIn("execution_context", block)
        self.assertEqual(block["workspace"]["commit"], COMMIT)
        self.assertEqual(block["config"]["tokens"], 8)
        self.assertEqual(block["corpus"]["manifest_sha256"], "ff")

    def test_settings_digest_ignores_key_order_and_changes_with_values(self):
        first = provenance.digest({"a": 1, "b": 2})
        self.assertEqual(first, provenance.digest({"b": 2, "a": 1}))
        self.assertNotEqual(first, provenance.digest({"a": 1, "b": 3}))


if __name__ == "__main__":
    unittest.main()
