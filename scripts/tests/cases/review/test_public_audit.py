"""The public audit flags the categories that must not reach a public repo."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.review import public_audit
from scripts.tests.shared.model_free import fixture_processes
from scripts.tests.shared.paths import CasePaths


class PublicAuditTests(unittest.TestCase):
    def test_secret_home_path_and_local_words_are_reported(self):
        # - the fixture uses an invented token: a real term here would itself be the leak
        text = "key github_pat_abcdefghijklmnopqrstuvwxyz01 home C:\\Users\\someone\\x note zzfixture\n"
        with patch.object(public_audit, "local_words", return_value=("zzfixture",)):
            findings = public_audit.scan_text("scripts/config/example.json", text, ())
        categories = {finding.category for finding in findings}
        self.assertEqual(categories, {"secrets", "home-path", "ocabulary"})

    def test_self_referential_files_are_still_screened_for_vocabulary(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(public_audit, "tracked_files", return_value=["scripts/review/public_audit.py"]),
            patch.object(public_audit, "local_words", return_value=("zzfixture",)),
        ):
            target = Path(folder) / "scripts" / "review" / "public_audit.py"
            target.parent.mkdir(parents=True)
            target.write_text("# zzfixture\n", encoding="utf-8")
            findings = public_audit.audit(Path(folder))
        self.assertEqual([finding.category for finding in findings], ["ocabulary"])

    @fixture_processes()
    def test_history_scan_uses_a_dialect_that_can_match(self):
        # - POSIX ERE rejects the vocabulary lookarounds, and a refusal once read as "clean"
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            git = ["git", "-C", str(root), "-c", "user.email=t@example.com", "-c", "user.name=t"]
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
            (root / "notes.md").write_text("a zzfixture line\n", encoding="utf-8")
            subprocess.run([*git, "add", "notes.md"], check=True, capture_output=True)
            subprocess.run([*git, "commit", "-q", "-m", "fixture"], check=True, capture_output=True)
            with (
                patch.object(public_audit, "voice_terms", return_value=()),
                patch.object(public_audit, "local_words", return_value=("zzfixture",)),
            ):
                findings = public_audit.history_findings(root)
        self.assertEqual([finding.path for finding in findings], ["notes.md"])

    def test_machine_paths_only_count_outside_documentation(self):
        config_hit = public_audit.scan_text("scripts/config/server.json", '"path": "C:/AI/data/x.gguf"', ())
        doc_hit = public_audit.scan_text("scripts/config/README.md", "exported to C:/AI/data/x.gguf", ())
        self.assertEqual([finding.category for finding in config_hit], ["machine-path"])
        self.assertEqual(doc_hit, [])

    def test_local_voice_ids_are_matched_as_whole_words(self):
        findings = public_audit.scan_text(
            "scripts/config/example.json", "voice alpha, model bravo", ("alpha", "charlie")
        )
        self.assertEqual([finding.detail for finding in findings], ["alpha"])

    def test_credential_fields_and_env_placeholders(self):
        text = '{"adminpassword": "hunter2x", "apiKey": "${ENV_KEY}", "token": "noop"}'
        findings = public_audit.scan_text("scripts/config/x.json", text, ())
        self.assertEqual([finding.category for finding in findings], ["credentials"])

    def test_clean_text_produces_no_findings(self):
        self.assertEqual(public_audit.scan_text("scripts/launchers/x.py", 'PATH = "{AI_ROOT}/data/x"', ()), [])

    def test_voice_terms_reach_into_file_names_but_not_prose(self):
        text = "download/alpha_config.py and summarize the result"
        findings = public_audit.scan_text("scripts/download/notes.py", text, ("alpha", "zznotaterm"))
        self.assertEqual([finding.detail for finding in findings], ["alpha"])

    def test_voice_terms_ignore_short_ids_that_collide_with_words(self):
        with (
            patch.object(public_audit.local_overlay, "voice_ids", return_value=("ab", "alpha")),
            patch.object(public_audit.local_overlay, "character_cards", return_value={}),
        ):
            self.assertEqual(public_audit.voice_terms(), ("alpha",))


if __name__ == "__main__":
    unittest.main()
