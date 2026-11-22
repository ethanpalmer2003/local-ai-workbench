"""The Breeze 2 vocal-event table: the vendor's file, the adapter's source, and the filter's behavior."""

import json
import unittest
from pathlib import Path

from scripts.config.audiocpp import tts_events
from scripts.launchers.audiocpp import tts_text_processing

EXPECTED_EVENTS = 34


class BreezeEventTableTests(unittest.TestCase):
    def test_the_documented_english_set_is_complete(self):
        events = tts_events.events()
        self.assertEqual(len(events), EXPECTED_EVENTS)
        self.assertTrue(all(event.category for event in events))

    def test_every_spelling_is_parenthesized_and_belongs_to_one_event(self):
        seen: dict[str, str] = {}
        for event in tts_events.events():
            self.assertTrue(event.tags, event.canonical)
            for tag in event.tags:
                self.assertTrue(tag.startswith("(") and tag.endswith(")"), tag)
                self.assertNotIn(tag, seen, f"{tag} belongs to {seen.get(tag)} and {event.canonical}")
                seen[tag] = event.canonical

    def test_the_file_names_its_source(self):
        payload = json.loads(tts_events.EVENTS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["source"], "https://docs.breezeblue.ai/guides/audio-tags")
        self.assertRegex(payload["retrieved"], r"^\d{4}-\d{2}-\d{2}$")

    def test_the_vendors_spellings_are_accepted(self):
        accepted = tts_events.tags()
        for tag in ("(laughs)", "(clears throat)", "(breathing heavily)", "(smacks lips)", "(pause)"):
            self.assertIn(tag, accepted)
        # - the model card's plain forms work too, and the adapter keeps them
        for tag in ("(laugh)", "(sigh)", "(cough)"):
            self.assertIn(tag, accepted)


class BreezeVocalAdapterTests(unittest.TestCase):
    def test_the_adapter_reads_the_file_rather_than_its_own_list(self):
        self.assertEqual(tts_text_processing.BREEZE_VOCAL_EVENTS.allowed_vocal_events, tts_events.tags())

    def test_a_documented_event_passes_through(self):
        self.assertEqual(tts_text_processing.filter_breeze_vocal_events("(laughs) hello"), "(laughs) hello")

    def test_a_bare_event_keeps_the_spelling_the_caller_typed(self):
        # - both the vendor's tag and the model card's plain form are sent as written, never rewritten
        for tag in ("(laugh)", "(laughs)", "(giggles)", "(clears throat)", "(breathing heavily)", "(pause)"):
            with self.subTest(tag=tag):
                self.assertEqual(tts_text_processing.filter_breeze_vocal_events(f"{tag} hi"), f"{tag} hi")

    def test_an_undocumented_parenthetical_is_unwrapped(self):
        self.assertEqual(tts_text_processing.filter_breeze_vocal_events("(waves hello)"), "waves hello")

    def test_an_event_with_extra_words_is_trimmed_to_the_event(self):
        self.assertEqual(tts_text_processing.filter_breeze_vocal_events("(giggles softly)"), "(giggles)")

    def test_the_path_points_at_the_tracked_file(self):
        self.assertTrue(Path(tts_events.EVENTS_PATH).is_file())
