"""Single-source Pi package inventory and safe add/remove synchronization."""

import json
import unittest
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.config.coding_agents.pi import packages
from scripts.download.frameworks import update_config
from scripts.download.frameworks.coding_agents.pi import packages as manager
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import llamacpp, llamacpp_coding
from scripts.tests.shared.paths import CasePaths


class PiPackageTests(unittest.TestCase):
    def fixture(self, stack: ExitStack, entries: list[dict[str, Any]]) -> Path:
        root = Path(stack.enter_context(CasePaths(__file__).temporary_directory()))
        config = {"core_package": "pi-core", "extensions": entries, "local_extensions": [], "default_tools": []}
        stack.enter_context(patch.object(packages.inventory, "CONFIG", config))
        stack.enter_context(patch.object(packages, "INSTALL_DIR", root / "install"))
        stack.enter_context(patch.object(packages, "STATE_FILE", root / "state/packages.json"))
        stack.enter_context(patch.object(manager.project_cfg, "STATE_DIR", root / "state"))
        stack.enter_context(patch.object(packages.project_cfg, "GENERATED_DIR", root / "state/generated"))
        return root

    def test_manifest_drives_loading_flags_environment_and_update_inventory(self):
        with ExitStack() as stack:
            self.fixture(
                stack,
                [
                    {"package": "new-lens", "cli_args": ["--quiet-context"], "environment": {"TEST_FLAG": "1"}},
                    {"package": "disabled-extension", "enabled": False},
                ],
            )
            self.assertEqual([path.name for path in packages.package_paths()], ["new-lens"])
            self.assertEqual(packages.cli_args(), ("--quiet-context",))
            self.assertEqual(packages.environment(packages.package_paths(), {}), {"TEST_FLAG": "1"})
            tools = update_config.pi_tools()
            self.assertEqual([tool.package for tool in tools], ["pi-core", "new-lens", "disabled-extension"])
            self.assertEqual([tool.in_use for tool in tools], [True, True, False])

    def test_removal_plan_keeps_core_and_unrelated_dependencies(self):
        with ExitStack() as stack:
            root = self.fixture(stack, [{"package": "new-lens"}])
            packages.INSTALL_DIR.mkdir()
            (packages.INSTALL_DIR / "package.json").write_text(
                json.dumps({"dependencies": {"pi-core": "1", "old-extension": "1", "unrelated": "1"}}), encoding="utf-8"
            )
            packages.STATE_FILE.parent.mkdir()
            packages.STATE_FILE.write_text(json.dumps({"managed": ["old-extension", "pi-core"]}), encoding="utf-8")
            self.assertEqual(manager.sync_plan(), (["new-lens"], ["old-extension"]))
            settings = root / "settings.json"
            settings.write_text(
                json.dumps(
                    {"theme": "dark", "packages": ["npm:old-extension@1", "npm:unrelated", "C:/old/pi-lsp-extension"]}
                ),
                encoding="utf-8",
            )
            packages.sync_settings(settings, packages.package_paths())
            data = json.loads(settings.read_text())
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["packages"], ["npm:unrelated", packages.package_path("new-lens").as_posix()])

    def test_duplicate_names_and_path_escape_are_rejected(self):
        for entries in (
            [{"package": "../escape"}],
            [{"package": "same"}, {"package": "same"}],
            [{"package": "pi-core"}],
        ):
            with self.subTest(entries=entries), ExitStack() as stack:
                self.fixture(stack, entries)
                with self.assertRaises(ValueError):
                    packages.extensions()

    def test_sync_preview_never_runs_npm_or_writes_settings(self):
        with ExitStack() as stack:
            root = self.fixture(stack, [{"package": "new-lens"}])
            run = stack.enter_context(patch.object(manager.subprocess, "run"))
            stack.enter_context(patch("builtins.print"))
            manager.sync(False)
            run.assert_not_called()
            self.assertFalse(packages.STATE_FILE.exists())
            self.assertFalse((root / "state/pi/agent/settings.json").exists())

    def test_normal_pi_launcher_has_the_manifest_flags(self):
        with CasePaths(__file__).temporary_directory() as folder:
            with patch.object(cfg.PI_CLIENT, "agent_dir", Path(folder)):
                command = llamacpp_coding.pi_command(llamacpp.LlamaConfig())
            for argument in packages.cli_args():
                self.assertIn(argument, command)
            environment = packages.environment(cfg.PI_CLIENT.packages, {"PATH": "original"})
            self.assertEqual(environment["PI_LENS_NO_CONTEXT_INJECTION"], "1")

    def test_lens_configuration_is_an_editable_file(self):
        environment = packages.environment(cfg.PI_CLIENT.packages, {})
        path = Path(environment["PI_LENS_CONFIG_PATH"])
        self.assertTrue(path.is_relative_to(packages.project_cfg.CONFIG_DIR))
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["lsp"]["servers"]["pyright"]["extensions"], [".py", ".pyi"]
        )


if __name__ == "__main__":
    unittest.main()
