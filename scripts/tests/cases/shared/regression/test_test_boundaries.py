"""Default-suite boundaries and the most common fixture drift are executable contracts."""

import ast
import ctypes
import os
import subprocess
import sys
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.tests.shared.model_free import fixture_processes, model_free_boundary
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.process_fixtures import running_process


class TestBoundaries(unittest.TestCase):
    def test_fixture_subprocess_scope_is_explicit_and_restored(self):
        with model_free_boundary():
            with fixture_processes():
                sys.audit("subprocess.Popen", sys.executable, [], None, {})
                with self.assertRaisesRegex(AssertionError, "Real process start"):
                    sys.audit("subprocess.Popen", str(project_cfg.FRAMEWORKS_DIR / "engine.exe"), [], None, {})
            with self.assertRaisesRegex(AssertionError, "Real process start"):
                sys.audit("subprocess.Popen", sys.executable, [], None, {})

    def test_real_process_launch_is_blocked_before_spawn(self):
        with model_free_boundary(), self.assertRaisesRegex(AssertionError, "Real process start"):
            subprocess.Popen([sys.executable, "-c", "pass"])

    def test_framework_dll_loading_is_blocked_before_loading(self):
        path = project_cfg.FRAMEWORKS_DIR / "regression-fixture-not-installed.dll"
        with model_free_boundary(), self.assertRaisesRegex(AssertionError, "Real framework DLL"):
            ctypes.CDLL(str(path))

    def test_mocked_launch_remains_available(self):
        process = running_process()
        with model_free_boundary(), patch("subprocess.Popen", return_value=process):
            self.assertIs(subprocess.Popen(["fixture"]), process)

    def test_boundary_also_applies_to_fixture_threads(self):
        errors = []

        def attempted_launch():
            try:
                sys.audit("subprocess.Popen", "fixture", [], None, {})
            except AssertionError as error:
                errors.append(str(error))

        with model_free_boundary():
            thread = Thread(target=attempted_launch)
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)

    @unittest.skipUnless(sys.platform == "win32", "Windows port ownership only")
    def test_owned_port_kill_refuses_unowned_listeners(self):
        from scripts.launchers import launch_util

        with (
            patch.object(launch_util, "listening_process_ids", return_value=[4242]),
            patch.object(launch_util, "describe_process", return_value="node.exe | C:/AI/frameworks/pi"),
            patch("scripts.launchers.launch_util.subprocess.run") as run,
            self.assertRaisesRegex(RuntimeError, "unowned listeners"),
        ):
            launch_util.kill_owned_processes_on_ports([18501], owned_pids=set())
        run.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows port ownership only")
    def test_owned_port_kill_stops_only_owned_pids(self):
        from scripts.launchers import launch_util

        with (
            patch.object(launch_util, "listening_process_ids", return_value=[4242]),
            patch("scripts.launchers.launch_util.subprocess.run") as run,
        ):
            launch_util.kill_owned_processes_on_ports([9931], owned_pids={4242})
        self.assertEqual(run.call_args.args[0][:4], ["taskkill", "/F", "/T", "/PID"])

    @unittest.skipUnless(sys.platform == "win32", "Windows taskkill behavior only")
    def test_taskkill_reports_no_running_instance_as_benign(self):
        import contextlib
        import io
        from unittest.mock import Mock

        from scripts.launchers import launch_util

        result = Mock(
            returncode=128,
            stdout="",
            stderr="ERROR: The process 16696 could not be terminated.\nReason: There is no running instance of the task.",
        )
        with (
            patch.object(launch_util.subprocess, "run", return_value=result),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            launch_util.kill_process_tree(16696)
        self.assertNotIn("WARN", output.getvalue())

    def test_native_preflight_refuses_existing_session(self):
        from scripts.tests.shared import native_suites

        with (
            patch.object(
                native_suites.launch_util,
                "listening_process_ids",
                side_effect=lambda port: [4242] if port == 18501 else [],
            ),
            patch.object(native_suites.launch_util, "describe_process", return_value="node.exe | strata"),
            self.assertRaisesRegex(RuntimeError, "refuse to stop an existing session"),
        ):
            native_suites.refuse_existing_sessions()

    def test_native_policy_refuses_and_restores(self):
        from scripts.launchers import launcher_config as cfg
        from scripts.tests.shared import native_suites

        previous = cfg.LAUNCH.existing_service_policy
        with native_suites.native_policy():
            self.assertIs(cfg.LAUNCH.existing_service_policy, cfg.ExistingServicePolicy.ERROR)
        self.assertIs(cfg.LAUNCH.existing_service_policy, previous)

    def test_native_policy_exports_env_for_child_processes(self):
        from scripts.tests.shared import native_suites

        previous = os.environ.get("AI_EXISTING_SERVICE_POLICY")
        previous_browser = os.environ.get("AI_NO_BROWSER")
        with native_suites.native_policy():
            self.assertEqual(os.environ.get("AI_EXISTING_SERVICE_POLICY"), "error")
            self.assertEqual(os.environ.get("AI_NO_BROWSER"), "1")
        self.assertEqual(os.environ.get("AI_EXISTING_SERVICE_POLICY"), previous)
        self.assertEqual(os.environ.get("AI_NO_BROWSER"), previous_browser)

    def test_browser_open_is_suppressed_in_native_policy(self):
        from scripts.launchers.runtime import browser
        from scripts.tests.shared import native_suites

        with (
            patch.object(browser.webbrowser, "open") as web_open,
            patch.object(browser.os, "startfile", create=True) as start_file,
            native_suites.native_policy(),
        ):
            self.assertFalse(browser.open_browser("http://localhost"))
        web_open.assert_not_called()
        start_file.assert_not_called()

    def test_dsh_availability_checks_the_asar_archive(self):
        from scripts.tests.cases.shared import live_frameworks

        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            resources = root / "resources"
            resources.mkdir()
            (resources / "app.asar").write_bytes(b"")
            exe = root / "DeepSeek Harness.exe"
            exe.write_bytes(b"")
            with patch.object(live_frameworks.cfg.DEEPSEEK_CLIENT, "exe", exe):
                self.assertEqual(live_frameworks.target_available("dsh-headless"), (True, ""))
                (resources / "app.asar").unlink()
                self.assertFalse(live_frameworks.target_available("dsh-headless")[0])

    def test_audiocpp_probe_requests_complete_wav(self):
        from scripts.tests.cases.shared import live_frameworks

        self.assertIs(live_frameworks.audiocpp_payload()["stream"], False)

    def test_progress_bar_reports_each_live_target(self):
        import io

        from scripts.tests.shared.progress import ProgressBar

        stream = io.StringIO()
        bar = ProgressBar(2, "launchers", stream=stream, step=1)
        bar.update("sdcpp")
        bar.update("audiocpp")
        text = stream.getvalue()
        self.assertIn("[PROGRESS] launchers", text)
        self.assertIn("2/2 audiocpp", text)

    def test_native_suite_dispatch(self):
        from scripts.tests.cases.shared import frameworks_smoke as owner

        with (
            patch.object(owner.live_frameworks, "run_live", return_value=True) as live,
            patch.object(owner.quick_validation, "run_probes", return_value=True) as probes,
        ):
            self.assertEqual(owner._run_native_suite("launchers", None, ["ming3-tts"]), 0)
            live.assert_called_once_with(["sdcpp", "audiocpp", "llamacpp", "kobold", "dsh-headless", "practice"])
            probes.assert_not_called()
            live.reset_mock()
            self.assertEqual(owner._run_native_suite("backends", None, ["ming3-tts"]), 0)
            probes.assert_called_once_with(["ming3-tts"])
            live.assert_not_called()

    def test_native_targets_are_disjoint(self):
        from scripts.tests.cases.shared import live_frameworks, quick_validation

        self.assertEqual(set(live_frameworks.LAUNCHER_TARGETS) & set(quick_validation.PROBES), set())
        self.assertNotIn("audiocpp", quick_validation.PROBES)
        self.assertIn("ming3-tts", quick_validation.PROBES)

    def test_regressions_do_not_reintroduce_unconfigured_pid_mocks(self):
        offenders = []
        for path in project_cfg.TEST_CASES_DIR.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            if not any(isinstance(node, ast.FunctionDef) and node.name.startswith("test_") for node in ast.walk(tree)):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                keys = {keyword.arg for keyword in node.keywords}
                if node.func.id in ("Mock", "MagicMock") and "pid" in keys and "info" not in keys:
                    offenders.append(f"{path.relative_to(project_cfg.TEST_CASES_DIR)}:{node.lineno}")
        self.assertEqual(
            offenders, [], "Use process_fixtures; psutil info mocks intentionally have a different contract"
        )
