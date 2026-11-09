"""Model update signals: source checks, newer-release hints and overlay-aware catalog writes."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from scripts.config.models import ModelDownload, catalog
from scripts.download.models import updates


class FakeHub:
    """A Hub double: one repository with the given files and versioned sibling ids."""

    def __init__(self, files: dict[str, int], ids: list[str] | None = None, broken: bool = False) -> None:
        self.files = files
        self.ids = ids or []
        self.broken = broken

    def model_info(self, repo_id: str, *, revision: str | None = None, files_metadata: bool = False) -> Any:
        if self.broken:
            raise OSError("offline")
        siblings = [SimpleNamespace(rfilename=name, size=size, lfs=None) for name, size in self.files.items()]
        return SimpleNamespace(siblings=siblings)

    def list_models(self, *, search: str, limit: int) -> Any:
        return [SimpleNamespace(id=repo) for repo in self.ids]


def _model(url: str, path: Path | None = None, label: str = "koboldcpp/family-v1.1") -> ModelDownload:
    return cast(
        ModelDownload,
        cast(object, SimpleNamespace(label=label, url=url, path=path or Path("missing.gguf"), in_use=True)),
    )


class ModelUpdatesTests(unittest.TestCase):
    def test_release_parsing(self) -> None:
        self.assertEqual(
            updates._release("bartowski/TheDrummer_Orion-26B-A4B-v1.1-GGUF"), ("TheDrummer_Orion-26B-A4B", (1, 1))
        )
        self.assertEqual(updates._release("a/family-v1"), ("family", (1,)))
        self.assertIsNone(updates._release("ggml-org/whisper.cpp"))
        self.assertIsNone(updates._release("bartowski/plain-GGUF"))

    def test_size_formatting(self) -> None:
        self.assertEqual(updates._size(2 * 1024**3), "2.0 GiB")
        self.assertEqual(updates._size(None), "-")

    def test_matching_source_and_size_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "family.gguf"
            path.write_bytes(b"x" * 8)
            hub = FakeHub({"family.gguf": 8})
            row = updates.check(_model("https://huggingface.co/a/b/blob/main/family.gguf", path), hub)
        self.assertEqual(row.source, "ok")

    def test_size_drift_is_reported_as_changed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "family.gguf"
            path.write_bytes(b"x" * 8)
            hub = FakeHub({"family.gguf": 9})
            row = updates.check(_model("https://huggingface.co/a/b/blob/main/family.gguf", path), hub)
        self.assertEqual(row.source, "changed")

    def test_a_newer_release_is_only_a_hint(self) -> None:
        hub = FakeHub({"family-v1.1.gguf": 8}, ids=["a/family-v1.2-GGUF", "a/family-v1.0-GGUF", "b/other-v9-GGUF"])
        url = "https://huggingface.co/a/family-v1.1-GGUF/blob/main/family-v1.1.gguf"
        row = updates.check(_model(url), hub)
        self.assertEqual(row.source, "ok")
        self.assertEqual(row.newer, "1.2")

    def test_an_unversioned_family_gets_no_version_hint(self) -> None:
        hub = FakeHub({"ggml-large-v3.bin": 8}, ids=["x/ggml-large-v3.5-GGUF"])
        url = "https://huggingface.co/ggml-org/whisper.cpp/blob/main/ggml-large-v3.bin"
        self.assertEqual(updates.check(_model(url), hub).newer, "")

    def test_missing_and_unreachable_sources_are_reported(self) -> None:
        missing = updates.check(_model("https://huggingface.co/a/b/blob/main/gone.gguf"), FakeHub({"other.gguf": 1}))
        broken = updates.check(_model("https://huggingface.co/a/b/blob/main/gone.gguf"), FakeHub({}, broken=True))
        self.assertEqual(missing.source, "missing")
        self.assertEqual(broken.source, "unreachable")

    def test_an_entry_without_a_source_is_named(self) -> None:
        row = updates.check(_model(""), FakeHub({}))
        self.assertEqual(row.source, "no url")


class CatalogOverlayTests(unittest.TestCase):
    def _files(self, folder: Path) -> tuple[Path, Path]:
        public = folder / "catalog.json"
        overlay = folder / "models.private.json"
        public.write_text(json.dumps({"version": 1, "models": []}), encoding="utf-8")
        overlay.write_text(json.dumps({"version": 1, "models": []}), encoding="utf-8")
        return public, overlay

    def _entry(self, label: str) -> dict[str, Any]:
        group = label.split("/", 1)[0]
        return {
            "category": "llms",
            "group": group,
            "label": label,
            "filename": f"folder/{label.split('/', 1)[1]}.gguf",
            "url": None,
            "in_use": False,
            "notes": "",
            "sha256": None,
            "roles": [],
            "runtimes": [],
            "source_page": None,
        }

    def test_entries_are_written_where_they_are_listed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            public, overlay = self._files(Path(folder))
            with (
                patch.object(catalog, "CATALOG_PATH", public),
                patch.object(catalog, "overlay_path", return_value=overlay),
                patch.object(catalog, "clear_cache"),
            ):
                catalog.upsert_entry(self._entry("koboldcpp/private"), overlay)
                self.assertEqual(catalog.entry_home("koboldcpp/private"), overlay)
                catalog.upsert_entry(self._entry("llamacpp/public"), public)
                self.assertEqual(catalog.entry_home("llamacpp/public"), public)
                # - an unknown label defaults to the overlay, which is where personal entries live
                catalog.upsert_entry(self._entry("koboldcpp/second"))
                self.assertEqual(catalog.entry_home("koboldcpp/second"), overlay)
                self.assertEqual(catalog.remove_entry("koboldcpp/private"), overlay)
                self.assertIsNone(catalog.remove_entry("koboldcpp/private"))
            self.assertEqual(
                [entry["label"] for entry in json.loads(overlay.read_text(encoding="utf-8"))["models"]],
                ["koboldcpp/second"],
            )
            self.assertEqual(
                [entry["label"] for entry in json.loads(public.read_text(encoding="utf-8"))["models"]],
                ["llamacpp/public"],
            )
