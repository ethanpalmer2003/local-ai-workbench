"""Pinned corpus manifest, extraction and identity; no network and no native work."""

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.benchmarks.shared import language_corpus
from scripts.download.benchmarks import fleurs

LANGUAGES = ("en", "es", "fr", "ja")


def archive(directory: Path, members: dict[str, bytes]) -> Path:
    """A gzipped tar holding exactly these members, compressed like the corpus archives."""
    path = directory / "audio.tar.gz"
    with tarfile.open(path, mode="w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return path


class CorpusManifestTests(unittest.TestCase):
    def test_manifest_pins_a_revision_and_twenty_distinct_clips_per_language(self):
        spec = fleurs.spec()
        self.assertRegex(spec["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(spec["split"], "test")
        languages = [clip["language"] for clip in spec["clips"]]
        for code in LANGUAGES:
            self.assertEqual(languages.count(code), 20)
        for field in ("reference", "member", "id"):
            values = [clip[field] for clip in spec["clips"]]
            self.assertEqual(len(values), len(set(values)), f"repeated {field}")

    def test_manifest_hash_tracks_the_tracked_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "corpus.json"
            path.write_text(json.dumps({"corpus": "a", "clips": [1]}), encoding="utf-8")
            with patch.object(fleurs, "manifest_path", return_value=path):
                first = fleurs.manifest_sha256()
                path.write_text(json.dumps({"corpus": "b", "clips": [1]}), encoding="utf-8")
                self.assertNotEqual(first, fleurs.manifest_sha256())

    def test_an_incomplete_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "corpus.json"
            path.write_text(json.dumps({"corpus": "a", "clips": []}), encoding="utf-8")
            with patch.object(fleurs, "manifest_path", return_value=path), self.assertRaises(ValueError):
                fleurs.spec()

    def test_identity_carries_the_revision_and_manifest_hash_the_report_records(self):
        identity = language_corpus.identity()
        self.assertEqual(identity["corpus"], "google/fleurs")
        self.assertRegex(identity["revision"], r"^[0-9a-f]{40}$")
        self.assertRegex(identity["manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(identity["clips"], 80)


class ExtractionTests(unittest.TestCase):
    def test_only_the_wanted_members_are_written(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = archive(root, {"test/a.wav": b"AAA", "test/b.wav": b"BBB", "test/c.wav": b"CCC"})
            target = root / "out" / "a.wav"
            fleurs._extract(source, {"test/a.wav": target})
            self.assertEqual(target.read_bytes(), b"AAA")
            self.assertFalse((root / "out" / "b.wav").exists())

    def test_a_member_missing_from_the_archive_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = archive(root, {"test/a.wav": b"AAA"})
            with self.assertRaises(ValueError) as raised:
                fleurs._extract(source, {"test/zzz.wav": root / "zzz.wav"})
            self.assertIn("test/zzz.wav", str(raised.exception))

    def test_a_clip_lives_under_its_language_inside_the_revision_folder(self):
        clip = {"config": "ja_jp", "member": "test/123.wav"}
        self.assertEqual(fleurs.clip_path(clip, Path("root")), Path("root/ja_jp/123.wav"))

    def test_clip_rows_record_bytes_and_digest_for_the_download_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "en_us" / "1.wav"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"WAVE")
            manifest = {"clips": [{"id": "en-0", "config": "en_us", "member": "test/1.wav"}]}
            rows = fleurs._clip_rows(manifest, "en_us", root)
        self.assertEqual(rows[0]["file"], "en_us/1.wav")
        self.assertEqual(rows[0]["bytes"], 4)
        self.assertEqual(rows[0]["sha256"], hashlib.sha256(b"WAVE").hexdigest())


if __name__ == "__main__":
    unittest.main()
