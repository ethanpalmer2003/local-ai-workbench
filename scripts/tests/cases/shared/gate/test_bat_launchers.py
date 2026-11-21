"""Every .bat resolves to a real module and its argparse entry point accepts --help.

The layout check owns which batches run alone instead of through the shared runner.
"""

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
from scripts.review.checks.layout import BATCH_RUNS_ALONE

MODULE = re.compile(r"python(?:\.exe)?[\"']?\s+-m\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
RUN_MODULE = re.compile(r'^set\s+"?RUN_MODULE=([A-Za-z_][\w.]*)"?', re.MULTILINE)

# - Modules reached by a bat but not help-smoked, with the reason.
SKIP_MODULES = {
    "scripts.tests.run": "runs through its __main__ block and has no main()",
    "scripts.download.models.download_models": "delegates argument parsing to download_catalog",
    "scripts.tools.stage_runner": "takes a module path and forwards the rest of the command",
    "scripts.launchers.llamacpp.language_practice": "delegates argument parsing to workspace.main",
    "scripts.launchers.llamacpp.llamacpp_pi": "delegates argument parsing to llamacpp_coding.main",
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
            if relative in BATCH_RUNS_ALONE:
                continue
            modules = batch_modules(path)
            self.assertTrue(modules, f"{relative}: no python -m target")
            for module in modules:
                self.assertIsNotNone(importlib.util.find_spec(module), f"{relative}: missing module {module}")

    def test_the_framework_update_batch_confirms_the_run_a_person_started(self):
        text = (project_cfg.BAT_DIR / "update_frameworks.bat").read_text(encoding="utf-8")
        self.assertIn("--yes", text, "a double-clicked update must not wait on the consent prompt")

    def test_argparse_entry_points_accept_help(self):
        for path in sorted(project_cfg.BAT_DIR.rglob("*.bat")):
            relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
            if relative in BATCH_RUNS_ALONE:
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
