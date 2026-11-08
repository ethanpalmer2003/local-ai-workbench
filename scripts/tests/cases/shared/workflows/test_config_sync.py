"""Configuration ownership, synchronization preview and replacement preservation."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import models
from scripts.config import sync_configs as sync
from scripts.config.audiocpp import server
from scripts.tests.shared.paths import CasePaths


class ConfigSyncTests(unittest.TestCase):
    def test_preview_is_read_only_and_apply_preserves_replaced_files(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            target = root / "comfy/file.json"
            target.parent.mkdir()
            target.write_bytes(b"old")
            saved = []

            def archive(path, _root):
                saved.append(path.read_bytes())
                path.rename(root / "preserved.json")

            with (
                patch.object(sync.project_cfg, "COMFYUI_ROCM_DIR", target.parent),
                patch.object(sync.project_cfg, "STATE_DIR", root / "state"),
                patch.object(sync, "comfyui_files", return_value={target: b"new"}),
                patch.object(sync, "archive_path", side_effect=archive) as preserve,
                patch("builtins.print"),
            ):
                self.assertEqual(sync.sync_comfyui(), [target])
                self.assertEqual(target.read_bytes(), b"old")
                preserve.assert_not_called()
                self.assertEqual(sync.sync_comfyui(True), [target])
                self.assertEqual(saved, [b"old"])
                self.assertEqual(target.read_bytes(), b"new")
                self.assertEqual(sync.sync_comfyui(True), [])
                self.assertEqual(preserve.call_count, 1)

    def test_removed_managed_workflow_is_preserved_and_unrelated_files_are_left_alone(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            installation = root / "comfy"
            workflows = installation / "user/default/workflows"
            workflows.mkdir(parents=True)
            owned, unrelated = workflows / "owned.json", workflows / "personal.json"
            unrelated.write_bytes(b"personal")
            with (
                patch.object(sync.project_cfg, "COMFYUI_ROCM_DIR", installation),
                patch.object(sync.project_cfg, "STATE_DIR", root / "state"),
                patch.object(sync, "comfyui_files", return_value={owned: b"tracked"}) as sources,
                patch("builtins.print"),
            ):
                sync.sync_comfyui(True)
                owned.write_bytes(b"local edits")
                sources.return_value = {}
                record = root / "state/comfyui/workflow-sync.json"
                before = record.read_bytes()
                self.assertEqual(sync.sync_comfyui(), [owned])
                self.assertEqual(owned.read_bytes(), b"local edits")
                self.assertEqual(record.read_bytes(), before)
                with patch.object(sync, "archive_path", side_effect=lambda path, _: path.rename(root / "retired.json")):
                    self.assertEqual(sync.sync_comfyui(True), [owned])
                self.assertEqual((root / "retired.json").read_bytes(), b"local edits")
                self.assertEqual(unrelated.read_bytes(), b"personal")
                self.assertEqual(json.loads(record.read_text())["workflows"], [])

    def test_invalid_workflow_ownership_cannot_escape_the_workflow_folder(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            record = root / "record.json"
            with patch.object(sync.project_cfg, "COMFYUI_ROCM_DIR", root):
                record.write_text(
                    json.dumps({"installation": root.resolve().as_posix(), "workflows": ["../personal.json"]})
                )
                with self.assertRaisesRegex(ValueError, "workflow name"):
                    sync.workflow_retirements({}, record)

    def test_audio_settings_use_catalog_paths_and_are_independent_copies(self):
        config = server.read()
        known = {model.path.as_posix() for model in models.MODELS}
        self.assertTrue(all(model["path"] in known for model in config["models"]))
        config["models"].clear()
        self.assertTrue(server.read()["models"])

    def test_missing_source_folder_aborts_without_retiring_anything(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            with (
                patch.object(sync.project_cfg, "COMFYUI_ROCM_DIR", root),
                patch.object(sync.project_cfg, "CONFIG_DIR", root / "missing"),
                patch.object(sync, "archive_path") as archive,
            ):
                with self.assertRaisesRegex(FileNotFoundError, "workflow folder"):
                    sync.sync_comfyui(True)
                archive.assert_not_called()

    def test_ownership_from_another_installation_is_not_reused(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            record = root / "record.json"
            record.write_text(json.dumps({"installation": "C:/other/comfy", "workflows": ["owned.json"]}))
            with patch.object(sync.project_cfg, "COMFYUI_ROCM_DIR", root):
                self.assertEqual(sync.workflow_retirements({}, record), [])

    def test_audio_base_changes_are_read_without_regeneration(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "server.json"
            path.write_text(json.dumps({"backend": "vulkan", "models": []}), encoding="utf-8")
            with patch.object(server, "CONFIG_PATH", path):
                self.assertEqual(server.read()["backend"], "vulkan")
                path.write_text(json.dumps({"backend": "cpu", "models": []}), encoding="utf-8")
                self.assertEqual(server.read()["backend"], "cpu")
