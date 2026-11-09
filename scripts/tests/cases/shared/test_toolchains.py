"""Toolchain checks: version parsing, npm/uv/pip status and update dispatch."""

import unittest
from unittest.mock import patch

from scripts.download.frameworks import toolchains


def _tool(name: str = "demo", latest: str = "2.0.0") -> toolchains.Toolchain:
    return toolchains.Toolchain(name, ["demo", "--version"], lambda: latest, ["demo", "update"])


class ToolchainTests(unittest.TestCase):
    def test_version_parsing(self) -> None:
        self.assertEqual(toolchains._version("npm 10.9.2"), (10, 9, 2))
        self.assertEqual(toolchains._version("pip 25.2 (python 3.13)"), (25, 2, 0))
        self.assertIsNone(toolchains._version("no version"))

    def test_a_missing_executable_is_reported(self) -> None:
        with (
            patch.object(toolchains, "toolchains", return_value=[_tool()]),
            patch.object(toolchains.shutil, "which", return_value=None),
        ):
            rows = toolchains.check()
        self.assertEqual(rows[0].status, "missing")

    def test_a_behind_tool_is_available_and_a_current_one_is_not(self) -> None:
        behind = _tool("behind", latest="2.0.0")
        current = _tool("current", latest="1.0.0")
        with (
            patch.object(toolchains, "toolchains", return_value=[behind, current]),
            patch.object(toolchains.shutil, "which", return_value="C:/bin/demo.exe"),
            patch.object(toolchains, "_run", return_value=(0, "demo 1.0.0")),
        ):
            rows = toolchains.check()
        self.assertEqual([row.status for row in rows], ["available", "current"])
        self.assertEqual(rows[0].latest, "2.0.0")

    def test_apply_updates_only_available_rows(self) -> None:
        behind = _tool("behind")
        current = _tool("current", latest="1.0.0")
        rows = [
            toolchains.Row("behind", "1.0.0", "2.0.0", "available"),
            toolchains.Row("current", "1.0.0", "1.0.0", "current"),
        ]
        calls: list[list[str]] = []

        def fake_run(command: list[str]) -> tuple[int, str]:
            calls.append(command)
            return 0, "updated"

        with (
            patch.object(toolchains, "toolchains", return_value=[behind, current]),
            patch.object(toolchains, "_run", side_effect=fake_run),
        ):
            self.assertFalse(toolchains.apply(rows))
        self.assertEqual(calls, [["demo", "update"]])

    def test_a_failed_toolchain_update_is_reported(self) -> None:
        rows = [toolchains.Row("behind", "1.0.0", "2.0.0", "available")]
        with (
            patch.object(toolchains, "toolchains", return_value=[_tool("behind")]),
            patch.object(toolchains, "_run", return_value=(1, "denied")),
        ):
            self.assertTrue(toolchains.apply(rows))
