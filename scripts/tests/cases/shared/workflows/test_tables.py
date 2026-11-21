"""The shared table renderer, and the model listing built on it."""

import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.config.models import ModelDownload
from scripts.download.models import download_catalog
from scripts.shared.tables import render_table
from scripts.tests.shared.paths import CasePaths


class TableTests(unittest.TestCase):
    def test_columns_are_as_wide_as_their_widest_cell(self):
        text = render_table([("a", "long cell"), ("bbb", "c")], ("one", "two"))
        self.assertEqual(
            text.splitlines(),
            ["| one | two       |", "| --- | --------- |", "| a   | long cell |", "| bbb | c         |"],
        )

    def test_a_row_shorter_than_the_header_still_pads(self):
        self.assertEqual(render_table([("x",)], ("one", "two")).splitlines()[-1], "| x   |     |")

    def test_no_rows_renders_the_header_and_rule_only(self):
        self.assertEqual(len(render_table([], ("one",)).splitlines()), 2)


class ModelListingTests(unittest.TestCase):
    def listing(self, models):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            download_catalog._print_models(models)
        return printed.getvalue()

    def model(self, label: str, filename: str, in_use: bool = True) -> ModelDownload:
        return ModelDownload(
            category="tts",
            group="audiocpp",
            label=label,
            filename=filename,
            url="https://example.test/file",
            destination=f"huggingface/models/audiocpp/{filename}",
            in_use=in_use,
        )

    def test_one_row_per_model_with_its_state_and_size(self):
        with CasePaths(__file__).temporary_directory() as folder:
            data = Path(folder)
            (data / "huggingface/models/audiocpp").mkdir(parents=True)
            (data / "huggingface/models/audiocpp/present.gguf").write_bytes(b"x" * (2 * 2**20))
            with patch.object(project_cfg, "DATA_DIR", data):
                text = self.listing(
                    [
                        self.model("audiocpp/present", "present.gguf"),
                        self.model("audiocpp/absent", "absent.gguf", in_use=False),
                    ]
                )
        self.assertIn("| state", text)
        self.assertIn("in use", text)
        self.assertIn("audiocpp/present", text)
        self.assertIn("yes, 2 MiB", text)
        self.assertIn("inactive", text)
        self.assertIn("audiocpp/absent", text)
        self.assertIn("| no ", text)
        self.assertIn("model_admin where LABEL", text)

    def test_a_tiny_voice_tensor_is_reported_in_kibibytes(self):
        with CasePaths(__file__).temporary_directory() as folder:
            data = Path(folder)
            (data / "huggingface/models/audiocpp").mkdir(parents=True)
            (data / "huggingface/models/audiocpp/voice.pt").write_bytes(b"x" * 2048)
            with patch.object(project_cfg, "DATA_DIR", data):
                text = self.listing([self.model("audiocpp/voice", "voice.pt")])
        self.assertIn("yes, 2 KiB", text)


if __name__ == "__main__":
    unittest.main()
