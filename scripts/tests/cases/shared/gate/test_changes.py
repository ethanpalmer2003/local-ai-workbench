"""One git call answers the upstream copy of a whole change set, and a broken answer is not an edit."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.shared import changes


def _batch(*entries: tuple[str, bytes | None]) -> bytes:
    """`cat-file --batch` output for one path per entry, None meaning git has no such object."""
    payload = b""
    for path, content in entries:
        if content is None:
            payload += f"@{{upstream}}:{path} missing\n".encode()
            continue
        # - a found object answers `<oid> <type> <size>`, then the bytes and one newline
        payload += b"0" * 40 + f" blob {len(content)}\n".encode() + content + b"\n"
    return payload


class UpstreamTextTests(unittest.TestCase):
    def test_a_whole_change_set_costs_one_process(self):
        paths = ["scripts/a.py", "scripts/b.py", "scripts/gone.py"]
        payload = _batch(("scripts/a.py", b"x = 1\n"), ("scripts/b.py", b"y = 2\n"), ("scripts/gone.py", None))
        with patch.object(
            changes.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, payload, b"")
        ) as run:
            texts = changes.upstream_texts(paths, Path("root"))
        self.assertEqual(texts, {"scripts/a.py": "x = 1\n", "scripts/b.py": "y = 2\n"})
        run.assert_called_once()

    def test_content_holding_a_blank_line_survives_the_size_header(self):
        content = b'"""Doc."""\n\nVALUE = 1\n'
        payload = _batch(("scripts/a.py", content))
        with patch.object(changes.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, payload, b"")):
            texts = changes.upstream_texts(["scripts/a.py"], Path("root"))
        self.assertEqual(texts["scripts/a.py"], content.decode())

    def test_an_empty_change_set_asks_git_nothing(self):
        with patch.object(changes.subprocess, "run", side_effect=AssertionError("git was asked")):
            self.assertEqual(changes.upstream_texts([], Path("root")), {})

    def test_a_failed_read_raises_instead_of_reporting_every_path_missing(self):
        failure = subprocess.CompletedProcess([], 128, b"", b"fatal: no upstream configured")
        with patch.object(changes.subprocess, "run", return_value=failure), self.assertRaises(changes.GitError):
            changes.upstream_texts(["scripts/a.py"], Path("root"))
