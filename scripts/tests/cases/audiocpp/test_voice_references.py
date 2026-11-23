"""Reference-clip quality checks for the clone voices."""

import unittest
from unittest.mock import patch

from scripts.review import voice_references


class VoiceReferences(unittest.TestCase):
    def test_sound_annotations_scene_text_and_broken_characters_are_flagged(self):
        self.assertEqual(voice_references.problems("in three two one... cough cough"), ["sound annotation: cough"])
        self.assertEqual(voice_references.problems("(whispering) hello"), ["scene direction brackets"])
        self.assertEqual(voice_references.problems("Iâ€™m here"), ["broken characters"])
        self.assertEqual(voice_references.problems("Hello there."), [])

    def test_a_voice_without_a_reference_is_reported(self):
        with (
            patch.object(voice_references.cfg, "AUDIOCPP_PROXY_CLONE_VOICES", ["2b"]),
            patch.object(voice_references.audiocpp_catalog, "resolve_voice_ref", return_value=None),
        ):
            rows = voice_references.report()
        self.assertEqual(rows, [{"voice": "2b", "clip": "", "problems": ["no reference clip"]}])

    def test_a_conforming_reference_reports_no_problems(self):
        with (
            patch.object(voice_references.cfg, "AUDIOCPP_PROXY_CLONE_VOICES", ["2b"]),
            patch.object(
                voice_references.audiocpp_catalog, "resolve_voice_ref", return_value=("clip.wav", "Operator, come in.")
            ),
        ):
            rows = voice_references.report()
        self.assertEqual(rows, [{"voice": "2b", "clip": "clip.wav", "problems": []}])
