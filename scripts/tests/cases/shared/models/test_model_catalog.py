"""Model restore destinations and explicit selection; no network access."""

import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.download.models import download
from scripts.download.models.sources import parse_url
from scripts.tests.shared.http_fixtures import http_response
from scripts.tests.shared.paths import CasePaths


class ModelCatalogTests(unittest.TestCase):
    def test_chat_candidates_use_capabilities_across_storage_owners(self):
        from scripts.config import models
        from scripts.launchers.llamacpp import chat_models

        expected = {row.label for row in models.MODELS if "chat" in row.roles and "llamacpp" in row.runtimes}
        self.assertEqual({row["id"] for row in chat_models.catalog()}, expected)
        self.assertTrue(any(key.startswith("koboldcpp/") for key in expected))
        self.assertFalse(any("mmproj" in key.lower() for key in expected))
        with self.assertRaises(ValueError):
            chat_models.path("llamacpp/gemma-4-E4B-it-mmproj-q8_0")

    def test_audit_and_metadata_keep_registry_coverage(self):
        from scripts.config import models
        from scripts.config import project_config as project_cfg
        from scripts.download.models import analyze_model, model_sync

        self.assertTrue(all(row.path.is_relative_to(model_sync.MODEL_ROOTS[row.group]) for row in models.MODELS))
        self.assertEqual(model_sync.MODEL_ROOTS["strata"], project_cfg.component("strata").models_dir / "models")
        with patch.object(model_sync, "installed_model_files", return_value=set()):
            rows = analyze_model.discover()
        gemma = next(row for row in models.MODELS if row.label == "llamacpp/gemma-4-E4B-it-Q4_0")
        metadata = rows[str(gemma.path.resolve())]["registry"][0]
        self.assertEqual(metadata["roles"], list(gemma.roles))
        self.assertEqual(metadata["runtimes"], list(gemma.runtimes))

    def test_https_assets_verify_before_publication_and_preserve_bad_download(self):
        from scripts.download.models.http_transfer import download_verified

        response = http_response(b"asset")
        with CasePaths(__file__).temporary_directory() as folder, patch("requests.get", return_value=response):
            destination = Path(folder) / "model.bin"
            download_verified(response.url, destination, hashlib.sha256(b"asset").hexdigest())
            self.assertEqual(destination.read_bytes(), b"asset")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                download_verified(response.url, Path(folder) / "bad.bin", "0" * 64)
            self.assertFalse((Path(folder) / "bad.bin").exists())
            self.assertEqual(len(list(Path(folder).glob("bad.bin.*.part"))), 1)

    def test_https_assets_require_checksum_before_network_access(self):
        from scripts.download.models.http_transfer import download_verified

        with patch("requests.get") as fetch, self.assertRaisesRegex(ValueError, "pinned SHA256"):
            download_verified("https://example.test/model", Path("unused"), None)
        fetch.assert_not_called()

    def test_range_resume_uses_shared_token_and_verifies_before_publishing(self):
        from scripts.download.models.hub_transfer import download_ranges

        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            partial, destination = root / "partial", root / "model.gguf"
            partial.write_bytes(b"GG")
            payload = b"GGUF-data"
            metadata = SimpleNamespace(size=len(payload), etag=hashlib.sha256(payload).hexdigest())
            response = http_response(payload[2:], status=206, headers={"Content-Range": "bytes 2-8/9"})
            session = MagicMock()
            session.get.return_value = response
            with (
                patch("huggingface_hub.get_hf_file_metadata", return_value=metadata) as info,
                patch(
                    "huggingface_hub.utils.build_hf_headers", return_value={"Authorization": "Bearer test"}
                ) as headers,
                patch("huggingface_hub.utils.get_session", return_value=session),
                patch("scripts.config.project_config.HF_TOKEN", "test-token"),
            ):
                download_ranges(
                    parse_url("https://huggingface.co/owner/repo/resolve/revision/model.gguf"), destination, partial
                )
            self.assertEqual(info.call_args.kwargs["token"], "test-token")
            headers.assert_called_once_with(token="test-token")
            self.assertEqual(session.get.call_args.kwargs["headers"]["Range"], "bytes=2-8")
            self.assertEqual(destination.read_bytes(), payload)
            self.assertFalse(partial.exists())

    def test_nested_source_is_materialized_at_exact_consumer_path(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            cached = root / "cached.gguf"
            cached.write_bytes(b"model")
            model = download.ModelDownload(
                "audiocpp",
                "voice",
                "https://huggingface.co/owner/repo/blob/v1/nested/source.gguf",
                "models/audio/consumer.gguf",
            )
            with (
                patch.object(download.project_cfg, "DATA_DIR", root),
                patch("huggingface_hub.hf_hub_download", return_value=str(cached)) as fetch,
            ):
                download.download_model(model)
                self.assertEqual(model.path.read_bytes(), b"model")
                self.assertEqual(fetch.call_args.kwargs["filename"], "nested/source.gguf")
                self.assertEqual(fetch.call_args.kwargs["revision"], "v1")
                self.assertEqual(fetch.call_args.kwargs["local_dir"], str(model.path.parent))

    def test_existing_consumer_file_skips_hub_and_range_downloads(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            model = download.ModelDownload(
                "audiocpp",
                "drama",
                "https://huggingface.co/Jmica/Drama-3-GGUF/blob/main/model.gguf",
                "audiocpp/model.gguf",
            )
            with patch.object(download.project_cfg, "DATA_DIR", root):
                model.path.parent.mkdir()
                model.path.write_bytes(b"existing-model")
                with (
                    patch("huggingface_hub.hf_hub_download") as fetch,
                    patch("scripts.download.models.hub_transfer.download_ranges") as ranges,
                ):
                    download.download_model(model)
                    download.download_model(model, range_download=True)
                fetch.assert_not_called()
                ranges.assert_not_called()
                self.assertEqual(model.path.read_bytes(), b"existing-model")

    def test_listing_does_not_download_and_active_skips_candidates(self):
        with patch.object(download, "download_model") as fetch, patch("builtins.print"):
            download.main(["--list"])
            fetch.assert_not_called()
            download.main(["--active", "--group", "llamacpp", "--download"])
            self.assertTrue(fetch.called)
            self.assertTrue(
                all(call.args[0].in_use and call.args[0].group == "llamacpp" for call in fetch.call_args_list)
            )

    def test_catalog_labels_and_destinations_are_unique_and_relative(self):
        self.assertEqual(len(download.MODELS), len({model.label for model in download.MODELS}))
        self.assertEqual(len(download.MODELS), len({model.destination for model in download.MODELS}))
        sources = [
            parse_url(model.url)
            for model in download.MODELS
            if model.url is not None and model.url.startswith("https://huggingface.co/")
        ]
        self.assertEqual(len(sources), len(set(sources)))
        for model in download.MODELS:
            if model.url and not model.url.startswith("https://huggingface.co/"):
                self.assertTrue(model.url.startswith("https://"))
                self.assertRegex(model.sha256 or "", r"^[a-f0-9]{64}$")
            self.assertFalse(Path(model.destination).is_absolute())
            self.assertNotIn("..", Path(model.destination).parts)
            if model.in_use:
                self.assertIsNotNone(model.url)

    def test_inactive_listing_excludes_active_models(self):
        from dataclasses import replace
        active = next(model for model in download.MODELS if model.group == "llamacpp")
        sample = (active, replace(active, label="llamacpp/fixture-inactive", in_use=False))
        with patch.object(download, "MODELS", sample), patch("builtins.print") as output, patch.object(download, "download_model") as fetch:
            download.main(["--inactive", "--group", "llamacpp"])
        text = "\n".join(str(call.args[0]) for call in output.call_args_list)
        for model in sample:
            self.assertEqual(model.label in text, not model.in_use)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
