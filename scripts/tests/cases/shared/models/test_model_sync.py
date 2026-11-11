"""Model sync catches missing references without treating optional downloads as installed."""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.download.models.model_sync import ModelReference, audit_models, strata_references
from scripts.tests.shared.paths import CasePaths


class ModelSyncTests(unittest.TestCase):
    def test_strata_split_reference_detects_missing_second_shard(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            first = root / "model-00001-of-00002.gguf"
            first.write_bytes(b"first shard")
            config = Mock(config_path=root / "install" / "strata-model.json", config={"args": ["--native", str(first)]})
            with patch("scripts.launchers.strata.strata_pi.saved_connections", return_value=[config]):
                references = strata_references()
            report = audit_models({"models": root}, references, [])
            self.assertEqual(list(report.missing), [str(root / "model-00002-of-00002.gguf")])
            self.assertEqual(report.unreferenced, [])

    def test_missing_optional_unreferenced_and_source_references_are_distinct(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            installed = root / "models"
            installed.mkdir()
            for name in ("used.gguf", "cataloged.gguf", "unknown.gguf", "source-only.safetensors"):
                (installed / name).write_bytes(b"model")
            source = root / "config.py"
            source.write_text('MODEL = "source-only.safetensors"\nOTHER = "prefix-unknown.gguf"\n', encoding="utf-8")
            references = [
                ModelReference(installed / "used.gguf", "runtime"),
                ModelReference(installed / "cataloged.gguf", "download catalog:optional", False),
                ModelReference(installed / "missing.gguf", "runtime"),
                ModelReference(installed / "not-downloaded.gguf", "download catalog:candidate", False),
            ]
            report = audit_models({"models": installed}, references, [source])
            self.assertEqual(report.installed_count, 4)
            self.assertEqual(report.missing, {str(installed / "missing.gguf"): ["runtime"]})
            self.assertEqual(report.unreferenced, [str(installed / "unknown.gguf")])
            self.assertEqual(report.catalog_only, [str(installed / "cataloged.gguf")])
            self.assertFalse(report.in_sync)

    def test_cache_metadata_and_other_groups_do_not_create_false_positives(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / ".cache").mkdir()
            (root / ".cache" / "cached.bin").write_bytes(b"cache")
            (root / "model.gguf.done").write_text("done", encoding="utf-8")
            report = audit_models({"models": root}, [ModelReference(root.parent / "other.gguf", "other")], [])
            self.assertTrue(report.in_sync)
            self.assertEqual(report.installed_count, 0)

    def test_unavailable_root_is_not_reported_as_clean(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder) / "disconnected"
            report = audit_models({"models": root}, [], [])
            self.assertFalse(report.in_sync)
            self.assertEqual(report.unavailable_roots, [str(root)])


if __name__ == "__main__":
    unittest.main()
