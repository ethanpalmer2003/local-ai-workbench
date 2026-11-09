"""Every .bat resolves to a real module and its argparse entry point accepts --help."""

import contextlib
import importlib
import importlib.util
import inspect
import io
import re
import sys
import unittest
from unittest.mock import patch

from scripts.config import project_config as project_cfg

MODULE = re.compile(r"python(?:\.exe)?[\"']?\s+-m\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
RUN_MODULE = re.compile(r'^set\s+"?RUN_MODULE=([A-Za-z_][\w.]*)"?', re.MULTILINE)

# - Modules reached by a bat but not help-smoked, with the reason.
SKIP_MODULES = {
    "scripts.tests.run": "runs through its __main__ block and has no main()",
    "scripts.download.models.download_models": "delegates argument parsing to download_catalog",
    "scripts.tools.stage_runner": "takes a module path and forwards the rest of the command",
    "scripts.launchers.llamacpp.language_practice": "delegates argument parsing to workspace.main",
    "scripts.launchers.kill_all_services": "no argparse; running it would stop services",
    "scripts.launchers.llamacpp.llamacpp_pi": "delegates argument parsing to llamacpp_coding.main",
}

# - Bats with no `python -m` target (external CLI or another bootstrap script).
SKIP_BATCHES = {
    "bat/_run.bat": "shared runner; the module is supplied by the calling batch",
    "bat/resume_command_code_session.bat": "calls the framework-local cmdc shim",
    "bat/models/sync_python_env.bat": "runs uv sync against the project environment",
    "bat/browser/comfyui/comfyui_bootstrap.bat": "bootstraps ComfyUI's own python main.py",
    "bat/browser/comfyui/launch_comfyui.bat": "delegates to comfyui_bootstrap.bat",
}


def batch_modules(path) -> set[str]:
    lines = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().lower().startswith(("rem ", "::")):
            continue
        lines.append(line)
    text = "\n".join(lines)
    # - simple batches set RUN_MODULE for the shared runner; special ones call python -m directly
    return set(MODULE.findall(text)) | set(RUN_MODULE.findall(text))


class BatLaunchers(unittest.TestCase):
    def test_every_bat_targets_a_real_module(self):
        batches = sorted(project_cfg.BAT_DIR.rglob("*.bat"))
        self.assertTrue(batches)
        for path in batches:
            relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
            if relative in SKIP_BATCHES:
                continue
            modules = batch_modules(path)
            self.assertTrue(modules, f"{relative}: no python -m target")
            for module in modules:
                self.assertIsNotNone(importlib.util.find_spec(module), f"{relative}: missing module {module}")

    def test_argparse_entry_points_accept_help(self):
        for path in sorted(project_cfg.BAT_DIR.rglob("*.bat")):
            relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
            if relative in SKIP_BATCHES:
                continue
            for module_name in sorted(batch_modules(path)):
                if module_name in SKIP_MODULES:
                    continue
                module = importlib.import_module(module_name)
                entry = getattr(module, "main", None)
                if not callable(entry):
                    self.assertIn(module_name, SKIP_MODULES, f"{relative}: {module_name} has no main()")
                    continue
                source = inspect.getsource(module)
                if "argparse" not in source or "add_help=False" in source:
                    self.assertIn(module_name, SKIP_MODULES, f"{relative}: {module_name} cannot accept --help")
                    continue
                required = [
                    parameter
                    for parameter in inspect.signature(entry).parameters.values()
                    if parameter.default is inspect.Parameter.empty
                    and parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
                ]
                self.assertEqual(required, [], f"{relative}: {module_name}.main() requires arguments")
                with (
                    patch.object(sys, "argv", [module_name, "--help"]),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    entry()
                self.assertEqual(raised.exception.code, 0, f"{relative}: {module_name} rejected --help")
