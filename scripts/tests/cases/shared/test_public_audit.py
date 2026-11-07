"""The public audit flags the categories that must not reach a public repo."""

import unittest
from unittest.mock import patch

from scripts.review import public_audit


class PublicAuditTests(unittest.TestCase):
    def test_secret_home_path_and_private_words_are_reported(self):
        text = "key github_pat_abcdefghijklmnopqrstuvwxyz01 home C:\\Users\\someone\\x note ZZFIXTURE\n"
        findings = public_audit.scan_text("scripts/config/example.json", text, ())
        categories = {finding.category for finding in findings}
        self.assertEqual(categories, {"secrets", "home-path", "private-word"})

    def test_machine_paths_only_count_outside_documentation(self):
        config_hit = public_audit.scan_text("scripts/config/server.json", '"path": "C:/AI/data/x.gguf"', ())
        doc_hit = public_audit.scan_text("scripts/config/README.md", "exported to C:/AI/data/x.gguf", ())
        self.assertEqual([finding.category for finding in config_hit], ["machine-path"])
        self.assertEqual(doc_hit, [])

    def test_private_voice_ids_are_matched_as_whole_words(self):
        findings = public_audit.scan_text("scripts/config/example.json", "voice alpha, model bravo", ("alpha", "charlie"))
        self.assertEqual([finding.detail for finding in findings], ["alpha"])

    def test_credential_fields_and_env_placeholders(self):
        text = '{"adminpassword": "hunter2x", "apiKey": "${ENV_KEY}", "token": "noop"}'
        findings = public_audit.scan_text("scripts/config/x.json", text, ())
        self.assertEqual([finding.category for finding in findings], ["credentials"])

    def test_clean_text_produces_no_findings(self):
        self.assertEqual(public_audit.scan_text("scripts/launchers/x.py", 'PATH = "{AI_ROOT}/data/x"', ()), [])

    def test_voice_terms_reach_into_file_names_but_not_prose(self):
        text = "download/alpha_config.py and summazzfixture the result"
        findings = public_audit.scan_text("scripts/download/notes.py", text, ("alpha", "zzfixture"))
        self.assertEqual([finding.detail for finding in findings], ["alpha"])

    def test_voice_terms_ignore_short_ids_that_collide_with_words(self):
        with patch.object(public_audit.inputs, "voice_ids", return_value=("ab", "alpha")), patch.object(
            public_audit.inputs, "character_cards", return_value={}
        ):
            self.assertEqual(public_audit.voice_terms(), ("alpha",))


if __name__ == "__main__":
    unittest.main()
