"""A voice's clip pool: container preference, superseded takes and excluded ids."""

import tempfile
import unittest
from pathlib import Path

from scripts.download.input import voice_model


class VoiceFilesTests(unittest.TestCase):
    def test_a_manual_voice_may_arrive_as_mp3(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "1.mp3").write_bytes(b"")
            (root / "2.mp3").write_bytes(b"")
            found = voice_model.get_files([root])
        self.assertEqual([path.name for path in found], ["1.mp3", "2.mp3"])

    def test_a_container_that_exists_wins_over_the_later_ones(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "1.wav").write_bytes(b"")
            (root / "2.mp3").write_bytes(b"")
            found = voice_model.get_files([root])
        self.assertEqual([path.name for path in found], ["1.wav"])

    def test_a_superseded_take_and_an_excluded_id_stay_out_of_the_pool(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("1.mp3", "[old]1.mp3", "2.mp3"):
                (root / name).write_bytes(b"")
            found = voice_model.voice_files([root], {"2"}, root / "generated")
        self.assertEqual([path.name for path in found], ["1.mp3"])

    def test_no_supported_container_fails_loudly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "1.flac").write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "No .ogg, .wav or .mp3"):
                voice_model.get_files([root])


if __name__ == "__main__":
    unittest.main()
