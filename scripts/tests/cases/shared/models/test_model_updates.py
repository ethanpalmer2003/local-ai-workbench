"""Model update signals: source checks, newer-release hints, overlay writes and the refresh path."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from scripts.config.models import ModelDownload, catalog
from scripts.download.models import download_models, transfer, update_models, updates


class FakeHub:
    """A Hub double: one repository with the given files and versioned sibling ids."""

    def __init__(
        self,
        files: dict[str, int],
        ids: list[str] | None = None,
        broken: bool = False,
        repo_files: list[str] | None = None,
    ) -> None:
        self.files = files
        self.ids = ids or []
        self.broken = broken
        self.repo_files = repo_files if repo_files is not None else list(files)

    def model_info(self, repo_id: str, *, revision: str | None = None, files_metadata: bool = False) -> Any:
        if self.broken:
            raise OSError("offline")
        siblings = [SimpleNamespace(rfilename=name, size=size, lfs=None) for name, size in self.files.items()]
        return SimpleNamespace(siblings=siblings)

    def list_models(self, *, search: str, limit: int) -> Any:
        return [SimpleNamespace(id=repo) for repo in self.ids]

    def list_repo_files(self, repo_id: str, *, revision: str | None = None) -> Any:
        return list(self.repo_files)


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


class UpdateModelsTests(unittest.TestCase):
    def _old(self) -> ModelDownload:
        return cast(
            ModelDownload,
            cast(
                object,
                SimpleNamespace(
                    label="koboldcpp/Family-v1.1-IQ3_XXS",
                    group="koboldcpp",
                    category="llms",
                    filename="Family-v1.1-IQ3_XXS.gguf",
                    destination="huggingface/models/llms/character_models/Family-v1.1-IQ3_XXS.gguf",
                    url="https://huggingface.co/a/Family-v1.1-GGUF/blob/main/Family-v1.1-IQ3_XXS.gguf",
                    in_use=True,
                    notes="",
                    sha256=None,
                    roles=("chat",),
                    runtimes=("llamacpp",),
                    source_page=None,
                    path=Path("Family-v1.1-IQ3_XXS.gguf"),
                ),
            ),
        )

    def _drifted(self, folder: str) -> ModelDownload:
        path = Path(folder) / "Family-v1.1-IQ3_XXS.gguf"
        path.write_bytes(b"12345678")
        return cast(
            ModelDownload,
            cast(
                object,
                SimpleNamespace(
                    label="koboldcpp/Family-v1.1-IQ3_XXS",
                    group="koboldcpp",
                    category="llms",
                    filename="Family-v1.1-IQ3_XXS.gguf",
                    url="https://huggingface.co/a/Family-v1.1-GGUF/blob/main/Family-v1.1-IQ3_XXS.gguf",
                    in_use=True,
                    notes="",
                    sha256=None,
                    roles=(),
                    runtimes=(),
                    source_page=None,
                    path=path,
                ),
            ),
        )

    def test_file_matching_prefers_the_version_swap(self) -> None:
        hub = FakeHub({}, repo_files=["Family-v1.2-IQ3_XXS.gguf", "Family-v1.2-IQ4_XS.gguf"])
        self.assertEqual(update_models._file_for(hub, self._old(), "a/Family-v1.2-GGUF"), "Family-v1.2-IQ3_XXS.gguf")

    def test_file_matching_falls_back_to_a_unique_quant(self) -> None:
        hub = FakeHub({}, repo_files=["renamed-IQ3_XXS.gguf"])
        self.assertEqual(update_models._file_for(hub, self._old(), "a/Family-v1.2-GGUF"), "renamed-IQ3_XXS.gguf")
        ambiguous = FakeHub({}, repo_files=["one-IQ3_XXS.gguf", "two-IQ3_XXS.gguf"])
        self.assertIsNone(update_models._file_for(ambiguous, self._old(), "a/Family-v1.2-GGUF"))

    def test_the_new_entry_keeps_ownership_and_moves_the_file(self) -> None:
        entry = update_models._entry(self._old(), "Family-v1.2-IQ3_XXS.gguf", "a/Family-v1.2-GGUF")
        self.assertEqual(entry["label"], "koboldcpp/Family-v1.2-IQ3_XXS")
        self.assertEqual(entry["filename"], "Family-v1.2-IQ3_XXS.gguf")
        self.assertEqual(entry["group"], "koboldcpp")
        self.assertEqual(entry["url"], "https://huggingface.co/a/Family-v1.2-GGUF/blob/main/Family-v1.2-IQ3_XXS.gguf")

    def test_plan_upgrades_a_newer_versioned_release(self) -> None:
        hub = FakeHub(
            {"Family-v1.1-IQ3_XXS.gguf": 8}, ids=["a/Family-v1.2-GGUF"], repo_files=["Family-v1.2-IQ3_XXS.gguf"]
        )
        actions = update_models.plan(hub, [self._old()])
        self.assertEqual(
            [(action.kind, action.label) for action in actions], [("upgrade", "koboldcpp/Family-v1.2-IQ3_XXS")]
        )

    def test_plan_refreshes_a_size_drift(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            actions = update_models.plan(FakeHub({"Family-v1.1-IQ3_XXS.gguf": 9}), [self._drifted(folder)])
        self.assertEqual([action.kind for action in actions], ["refresh"])
        self.assertEqual(actions[0].expected, 9)

    def test_apply_upgrade_downloads_then_replaces(self) -> None:
        old = self._old()
        entry = update_models._entry(old, "Family-v1.2-IQ3_XXS.gguf", "a/Family-v1.2-GGUF")
        new = cast(ModelDownload, cast(object, SimpleNamespace(label=entry["label"])))
        action = update_models.Action("upgrade", old, entry)
        with (
            patch.object(update_models.model_admin, "references", return_value=([], [])),
            patch.object(update_models.catalog, "entry_home", return_value=Path("overlay.json")),
            patch.object(update_models.catalog, "upsert_entry") as upsert,
            patch.object(update_models.catalog, "get", return_value=new),
            patch.object(update_models.transfer, "download") as download,
            patch.object(update_models.model_admin, "command_replace", return_value=0) as replace,
        ):
            self.assertTrue(update_models._apply_upgrade(action))
        upsert.assert_called_once_with(entry, Path("overlay.json"))
        download.assert_called_once_with(new)
        replace.assert_called_once()

    def test_a_failed_upgrade_download_keeps_the_old_entry(self) -> None:
        old = self._old()
        entry = update_models._entry(old, "Family-v1.2-IQ3_XXS.gguf", "a/Family-v1.2-GGUF")
        action = update_models.Action("upgrade", old, entry)
        with (
            patch.object(update_models.model_admin, "references", return_value=([], [])),
            patch.object(update_models.catalog, "upsert_entry"),
            patch.object(update_models.catalog, "remove_entry") as remove,
            patch.object(update_models.catalog, "get", return_value=object()),
            patch.object(update_models.transfer, "download", side_effect=OSError("offline")),
        ):
            self.assertFalse(update_models._apply_upgrade(action))
        remove.assert_called_once_with(entry["label"])

    def test_refresh_swaps_in_the_complete_download(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            model = self._drifted(folder)
            part = model.path.with_name(model.path.name + ".part")

            def fake_stream(target: ModelDownload, expected: int | None = None, limit: int | None = None) -> Path:
                part.write_bytes(b"new")
                return part

            with (
                patch.object(update_models.transfer, "fetch_part", side_effect=fake_stream),
                patch.object(update_models.model_admin, "move_to_trash") as move,
            ):
                self.assertTrue(update_models._apply_refresh(update_models.Action("refresh", model, expected=3)))
            self.assertEqual(model.path.read_bytes(), b"new")
        move.assert_called_once()

    def test_a_failed_refresh_keeps_the_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            model = self._drifted(folder)
            with patch.object(update_models.transfer, "fetch_part", side_effect=RuntimeError("HTTP 500")):
                self.assertFalse(update_models._apply_refresh(update_models.Action("refresh", model)))
            self.assertEqual(model.path.read_bytes(), b"12345678")

    def test_a_limited_refresh_keeps_the_partial_and_the_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            model = self._drifted(folder)
            part = model.path.with_name(model.path.name + ".part")

            def fake_stream(target: ModelDownload, expected: int | None = None, limit: int | None = None) -> Path:
                part.write_bytes(b"abc")
                return part

            with patch.object(update_models.transfer, "fetch_part", side_effect=fake_stream):
                self.assertTrue(update_models._apply_refresh(update_models.Action("refresh", model), limit=3))
            self.assertEqual(model.path.read_bytes(), b"12345678")


class FakeResponse:
    """A requests response double for the streaming fetch."""

    def __init__(self, status: int, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.status_code = status
        self.headers = headers
        self.chunks = chunks

    def iter_content(self, chunk_size: int):
        yield from self.chunks

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class TransferTests(unittest.TestCase):
    def test_the_single_default_mode_is_the_hub_client(self) -> None:
        self.assertEqual(transfer.DEFAULT_MODE, "hub")
        self.assertEqual(transfer.MODES, ("hub", "stream"))

    def test_the_resolve_url_keeps_the_revision_and_subfolder(self) -> None:
        model = cast(
            ModelDownload, cast(object, SimpleNamespace(url="https://huggingface.co/a/b/blob/main/sub/f.gguf"))
        )
        self.assertEqual(transfer.resolve_url(model), "https://huggingface.co/a/b/resolve/main/sub/f.gguf")

    def test_stream_part_resumes_a_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            model = _model("https://huggingface.co/a/b/blob/main/f.gguf", Path(folder) / "f.gguf")
            part = transfer.part_path(model)
            part.write_bytes(b"abc")
            response = FakeResponse(206, {"Content-Length": "5"}, [b"45678"])
            with patch.object(transfer.requests, "get", return_value=response) as get:
                result = transfer.stream_part(model, expected=8)
            self.assertEqual(result.read_bytes(), b"abc45678")
            self.assertEqual(get.call_args.kwargs["headers"]["Range"], "bytes=3-")

    def test_stream_part_rejects_an_error_status(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            model = _model("https://huggingface.co/a/b/blob/main/f.gguf", Path(folder) / "f.gguf")
            with (
                patch.object(transfer.requests, "get", return_value=FakeResponse(404, {}, [])),
                self.assertRaises(RuntimeError),
            ):
                transfer.stream_part(model)


class DownloadModelsTests(unittest.TestCase):
    def test_no_arguments_fetch_only_the_missing_active_files(self) -> None:
        with patch.object(download_models.download_catalog, "main") as main:
            self.assertEqual(download_models.main([]), 0)
        main.assert_called_once_with(["--active", "--download"])

    def test_repo_flags_go_to_the_arbitrary_downloader(self) -> None:
        with patch.object(download_models.cli_download, "main") as main:
            self.assertEqual(download_models.main(["--url", "https://huggingface.co/a/b/blob/main/f.gguf"]), 0)
        main.assert_called_once()


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
