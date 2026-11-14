"""Shared benchmark startup reuses user services and cleans up only owned workers."""

import unittest
from unittest.mock import Mock, call, patch

from scripts.shared import backends
from scripts.tests.shared.process_fixtures import running_process


class BackendSessions(unittest.TestCase):
    def test_live_workflow_refuses_existing_listener_before_spawning(self):
        from scripts.tests.cases.suites import live_frameworks

        with (
            patch.object(live_frameworks.launch_util, "_listening_pids", return_value=[("8888", 42)]),
            patch.object(live_frameworks.subprocess, "Popen") as start,
            patch.object(live_frameworks.launch_util, "kill_process_tree") as stop,
            self.assertRaisesRegex(RuntimeError, "sessions retained"),
            live_frameworks.running_framework("audiocpp"),
        ):
            pass
        start.assert_not_called()
        stop.assert_not_called()

    def test_shared_image_readiness_uses_models_route(self):
        from scripts.launchers import launch_util, launcher_config
        from scripts.launchers.runtime import backend_readiness

        expected = f"http://127.0.0.1:{launcher_config.SDCPP_SERVICE.port}/v1/models"
        self.assertEqual(backend_readiness.ready_url("sdcpp", launcher_config.SDCPP_SERVICE.port), expected)
        with patch.object(launch_util.urllib.request, "urlopen") as get:
            self.assertTrue(launch_util.backend_running(launcher_config.SDCPP_SERVICE.port))
        self.assertEqual(get.call_args.args[0], expected)
        with patch.object(launch_util.urllib.request, "urlopen") as get:
            self.assertTrue(launch_util.backend_running(18889, backend="sdcpp"))
        self.assertEqual(get.call_args.args[0], backend_readiness.ready_url("sdcpp", 18889))

    def setUp(self):
        self.enterContext(patch.object(backends, "require_native_execution", return_value={}))
        self.enterContext(patch.object(backends, "BenchmarkVram"))
        self.enterContext(patch.object(backends.launch_util, "listening_process_ids", return_value=[42]))

    def test_healthy_services_are_reused(self):
        with (
            patch.object(backends, "BenchmarkVram") as vram_factory,
            patch.object(backends, "http_ready", return_value=True),
            patch.object(backends, "start") as start,
            patch.object(backends.launch_util, "kill_process_tree") as stop,
        ):
            with backends.backend_sessions(Mock(), ("audio", "kobold")):
                pass
            vram_factory.return_value.__enter__.return_value.watch_backend.assert_has_calls(
                [call("audio", [42]), call("kobold", [42])]
            )
            start.assert_not_called()
            stop.assert_not_called()

    def test_native_context_refusal_precedes_startup_and_monitoring(self):
        with (
            patch.object(backends, "require_native_execution", side_effect=RuntimeError("AppContainer")),
            patch.object(backends, "BenchmarkVram") as monitor,
            patch.object(backends, "start") as start,
            self.assertRaisesRegex(RuntimeError, "AppContainer"),
            backends.backend_sessions(Mock(), ("audio",)),
        ):
            pass
        monitor.assert_not_called()
        start.assert_not_called()

    def test_only_owned_process_is_stopped_after_failure(self):
        process = running_process(pid=123)

        def start(name, run, owned):
            owned.append(process)

        with (
            patch.object(backends, "http_ready", side_effect=[True, False]),
            patch.object(backends, "require_free") as free,
            patch.object(backends, "start", side_effect=start),
            patch.object(backends.launch_util, "kill_process_tree") as stop,
        ):
            with (
                self.assertRaisesRegex(RuntimeError, "test failure"),
                backends.backend_sessions(Mock(), ("kobold", "audio")),
            ):
                raise RuntimeError("test failure")
            free.assert_called_once_with("audio")
            stop.assert_called_once_with(123)
            process.wait.assert_called_once_with(timeout=10)

    def test_occupied_unhealthy_service_is_never_replaced(self):
        with (
            patch.object(backends, "http_ready", return_value=False),
            patch.object(backends, "listening", return_value=True),
            patch.object(backends, "start") as start,
            self.assertRaisesRegex(RuntimeError, "existing services will not be replaced"),
            backends.backend_sessions(Mock(), ("audio",)),
        ):
            pass
        start.assert_not_called()

    def test_startup_failure_still_cleans_up_owned_process(self):
        process = running_process(pid=456)

        def start(name, run, owned):
            owned.append(process)
            raise RuntimeError("startup failed")

        with (
            patch.object(backends, "http_ready", return_value=False),
            patch.object(backends, "require_free"),
            patch.object(backends, "start", side_effect=start),
            patch.object(backends.launch_util, "kill_process_tree") as stop,
            self.assertRaisesRegex(RuntimeError, "startup failed"),
            backends.backend_sessions(Mock(), ("audio",)),
        ):
            pass
        stop.assert_called_once_with(456)

    def test_auto_start_can_be_disabled(self):
        with (
            patch.object(backends, "http_ready", return_value=False),
            patch.object(backends, "start") as start,
            self.assertRaisesRegex(RuntimeError, "automatic startup is disabled"),
            backends.backend_sessions(Mock(), ("audio",), start_missing=False),
        ):
            pass
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
