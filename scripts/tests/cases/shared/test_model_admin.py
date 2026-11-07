import contextlib
import io
import unittest
import uuid
from pathlib import Path
from unittest.mock import ANY, patch

from scripts.config import models as model_cfg
from scripts.config.models.types import ModelDownload
from scripts.tests.shared.paths import CasePaths
from scripts.tools import model_admin


class ModelAdminTests(unittest.TestCase):
    swift = "llamacpp/Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp"

    def test_where_finds_catalog_and_profile_references(self):
        model = model_admin.model_for(self.swift)
        refs, warnings = model_admin.references(model)
        sources = {ref.source for ref in refs}
        self.assertTrue(any(source.startswith("download catalog:") for source in sources))
        self.assertTrue(any(source.startswith("LLAMACPP_PROFILES[") for source in sources))
        self.assertEqual(warnings, [])
        self.assertTrue(model_admin.mentions(model))

    def test_catalog_entry_lives_in_json_and_generated_ids(self):
        model = model_admin.model_for(self.swift)
        self.assertEqual(model.category, "llms")
        self.assertEqual(model_admin.catalog.CATALOG_PATH.name, "catalog.json")
        self.assertIn(self.swift, model_admin.entry_json(model))
        self.assertTrue(model_admin.catalog.ids_match())
        # - ids.py covers the tracked catalog; MODELS also merges the private input overlay
        public = model_admin.catalog.load_catalog(overlay=False)
        self.assertEqual({str(item) for item in model_cfg.ModelId}, {item.label for item in public})
        self.assertTrue({item.label for item in public} <= {item.label for item in model_cfg.MODELS})

    def test_temp_catalog_round_trip_keeps_paths_and_ids(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            catalog_path = root / "catalog.json"
            ids_path = root / "ids.py"
            entries = [model_admin.catalog.entry_dict(model_admin.model_for(self.swift))]
            model_admin.catalog.save_catalog(entries, catalog_path)
            models = model_admin.catalog.load_catalog(catalog_path)
            self.assertEqual([model.label for model in models], [self.swift])
            model_admin.catalog.write_ids(models, ids_path)
            self.assertTrue(model_admin.catalog.ids_match(models, ids_path))

    def test_remove_refuses_a_referenced_model_without_moving_it(self):
        model = model_admin.model_for(self.swift)
        if not model.path.is_file():
            self.skipTest("this model's weights are not installed in this checkout")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(model_admin.command_remove(model, apply=False), 1)
        self.assertIn("[FAIL] Refusing removal", output.getvalue())
        self.assertTrue(model.path.is_file())

    def test_remove_dry_run_plans_trash_without_touching_an_unreferenced_file(self):
        with CasePaths(__file__).temporary_directory() as folder:
            token = uuid.uuid4().hex
            source = Path(folder) / f"temp-{token}.gguf"
            source.write_bytes(b"weights")
            model = ModelDownload("llamacpp", f"test/temp-{token}", None, str(source))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(model_admin.command_remove(model, apply=False), 0)
            self.assertTrue(source.is_file())
            self.assertIn("[Dry run]", output.getvalue())
            self.assertIn("trash", output.getvalue())

    def test_trash_target_stays_under_project_trash(self):
        target = model_admin.trash_target(Path("C:/AI/data/huggingface/models/example.gguf"), "stamp")
        self.assertIn("trash", target.parts)
        self.assertIn("model_admin", target.parts)

    def test_path_matches_split_gguf_parts(self):
        base = Path("C:/AI/data/models/foo-00001-of-00003.gguf")
        part = Path("C:/AI/data/models/foo-00002-of-00003.gguf")
        self.assertTrue(model_admin.path_matches(part, base))
        self.assertFalse(model_admin.path_matches(Path("C:/AI/data/models/bar.gguf"), base))

    def test_remove_apply_edits_catalog_and_moves_weights(self):
        model = model_admin.model_for(self.swift)
        entry = model_admin.catalog.entry_dict(model)
        with CasePaths(__file__).temporary_directory() as folder:
            source = Path(folder) / "weights.gguf"
            source.write_bytes(b"weights")
            with (
                patch.object(model_admin, "references", return_value=([], [])),
                patch.object(model_admin, "mentions", return_value=[]),
                patch.object(model_admin, "installed_files", return_value=[source]),
                patch.object(model_admin.catalog, "load_entries", return_value=[entry]),
                patch.object(model_admin.catalog, "save_catalog") as save,
                patch.object(model_admin.catalog, "write_ids") as ids,
                patch.object(model_admin, "backup_file"),
                patch.object(model_admin, "move_to_trash") as move,
                patch.object(model_admin, "run_model_sync", return_value=0),
            ):
                self.assertEqual(model_admin.command_remove(model, apply=True), 0)
        save.assert_called_once_with([])
        ids.assert_called_once()
        move.assert_called_once_with(source, ANY)

    def test_replace_apply_rewrites_active_references_and_retires_old(self):
        old = model_admin.model_for(self.swift)
        new = model_admin.model_for("llamacpp/gemma-4-E4B-it-Q4_0")
        with CasePaths(__file__).temporary_directory() as folder:
            source = Path(folder) / "config.py"
            source.write_text(f'MODEL = "{old.label}"\n', encoding="utf-8")
            with (
                patch.object(model_admin, "references", return_value=([], [])),
                patch.object(model_admin, "mentions", return_value=[]),
                patch.object(model_admin, "rewrite_files", return_value=[source]),
                patch.object(model_admin, "installed_files", return_value=[]),
                patch.object(
                    model_admin.catalog,
                    "load_entries",
                    return_value=[
                        model_admin.catalog.entry_dict(old),
                        model_admin.catalog.entry_dict(new),
                    ],
                ),
                patch.object(model_admin.catalog, "save_catalog") as save,
                patch.object(model_admin.catalog, "write_ids") as ids,
                patch.object(model_admin, "backup_file"),
                patch.object(model_admin, "run_model_sync", return_value=0),
            ):
                self.assertEqual(
                    model_admin.command_replace(
                        old, new, apply=True, include_docs=False, include_tests=False
                    ),
                    0,
                )
            self.assertIn(new.label, source.read_text(encoding="utf-8"))
        save.assert_called_once_with([model_admin.catalog.entry_dict(new)])
        ids.assert_called_once()

    def test_replace_dry_run_prints_the_label_and_file_substitution(self):
        old = model_admin.model_for(self.swift)
        new = model_admin.model_for("llamacpp/gemma-4-E4B-it-Q4_0")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                model_admin.command_replace(old, new, apply=False, include_docs=False, include_tests=False), 0
            )
        text = output.getvalue()
        self.assertIn(f"{old.label} -> {new.label}", text)
        self.assertIn(f"{old.path.name} -> {new.path.name}", text)
        self.assertIn("[Dry run]", text)
