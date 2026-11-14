"""Residency ordering, native passthrough and owned lifecycle; no GPU inference."""

import threading
import unittest
import urllib.error
from contextlib import nullcontext
from email.message import Message
from http.server import BaseHTTPRequestHandler
from unittest.mock import Mock, patch

from scripts.launchers import proxy_util
from scripts.launchers.audiocpp import tts_proxy
from scripts.launchers.runtime import image_on_demand as demand
from scripts.launchers.sdcpp import proxy as sdcpp_proxy
from scripts.launchers.sdcpp import server as sdcpp
from scripts.shared.http_server import request, server
from scripts.tests.shared.process_fixtures import exited_process, running_process


class ResidencyTests(unittest.TestCase):
    def test_failed_image_request_releases_lease_and_restores_conversation(self):
        pipeline = demand.ImageSessionPipeline(Mock())
        with (
            patch.object(pipeline.coordinator, "change") as change,
            patch.object(pipeline.native, "ensure_image_loaded"),
            self.assertRaisesRegex(RuntimeError, "generation failed"),
            pipeline.scope("image")("POST", "/v1/images/generations"),
        ):
            raise RuntimeError("generation failed")
        self.assertEqual([row.args[0] for row in change.call_args_list], ["image", "conversation"])
        self.assertEqual(pipeline.coordinator.mode, "conversation")
        self.assertEqual(pipeline.coordinator.active, 0)

    def test_same_mode_requests_overlap_and_do_not_reload(self):
        change = Mock()
        coordinator = demand.ResidencyCoordinator(change, 1)
        with coordinator.lease("conversation"), coordinator.lease("conversation"):
            self.assertEqual(coordinator.active, 2)
        change.assert_called_once_with("conversation")
        self.assertEqual(coordinator.active, 0)

    def test_mode_change_waits_for_active_request_then_has_fifo_priority(self):
        changed, completed = [], []
        coordinator = demand.ResidencyCoordinator(changed.append, 2)
        ready, release = threading.Event(), threading.Event()

        def image():
            with coordinator.lease("image"):
                completed.append("image")
                ready.set()
                release.wait(2)

        def conversation():
            with coordinator.lease("conversation"):
                completed.append("conversation")

        with coordinator.lease("conversation"):
            first = threading.Thread(target=image)
            first.start()
            with coordinator.condition:
                self.assertTrue(coordinator.condition.wait_for(lambda: len(coordinator.queue) == 1, 1))
            second = threading.Thread(target=conversation)
            second.start()
            self.assertFalse(ready.is_set())
        self.assertTrue(ready.wait(1))
        self.assertEqual(completed, ["image"])
        release.set()
        first.join(2)
        second.join(2)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(completed, ["image", "conversation"])
        self.assertEqual(changed, ["conversation", "image", "conversation"])

    def test_failed_transition_does_not_poison_queue(self):
        change = Mock(side_effect=[RuntimeError("load failed"), None])
        coordinator = demand.ResidencyCoordinator(change, 1)
        with self.assertRaisesRegex(RuntimeError, "load failed"), coordinator.lease("image"):
            pass
        with coordinator.lease("conversation"):
            self.assertEqual(coordinator.active, 1)
        self.assertFalse(coordinator.queue)
        self.assertFalse(coordinator.switching)

    def test_timeout_and_shutdown_release_waiting_tickets(self):
        coordinator = demand.ResidencyCoordinator(Mock(), 0)
        with coordinator.lease("conversation"), self.assertRaises(TimeoutError), coordinator.lease("image"):
            pass
        self.assertFalse(coordinator.queue)
        coordinator.close()
        with self.assertRaisesRegex(RuntimeError, "stopping"), coordinator.lease("image"):
            pass
        self.assertFalse(coordinator.queue)

    def test_metadata_and_management_do_not_switch_modes(self):
        pipeline = demand.ImageSessionPipeline(Mock())
        with patch.object(pipeline.coordinator, "lease", return_value=nullcontext()) as lease:
            for backend, method, path in (
                ("audio", "POST", "/v1/models/unload"),
                ("image", "POST", "/sdcpp/v1/models/load"),
                ("image", "GET", "/sdcpp/v1/models/status"),
                ("kobold", "GET", "/health"),
            ):
                with pipeline.scope(backend)(method, path):
                    pass
            lease.assert_not_called()

    def test_image_generation_checks_native_context_inside_lease(self):
        pipeline = demand.ImageSessionPipeline(Mock())
        with (
            patch.object(pipeline.native, "ensure_image_loaded") as ensure,
            patch.object(pipeline.coordinator, "lease", return_value=nullcontext()) as lease,
        ):
            with pipeline.scope("image")("POST", "/v1/images/generations?test=1"):
                pass
            lease.assert_called_once_with("image")
            ensure.assert_called_once_with()


class NativePassthroughTests(unittest.TestCase):
    def test_native_busy_response_does_not_restart_or_cancel_active_jobs(self):
        sessions = demand.NativeModelSessions()
        busy = urllib.error.HTTPError("http://localhost", 409, "busy", Message(), None)
        with (
            patch.object(sessions, "call", side_effect=busy),
            patch.object(sessions, "_restart_image_server") as restart,
            self.assertRaises(urllib.error.HTTPError),
        ):
            sessions._unload_image()
        restart.assert_not_called()

    def test_native_unload_fault_uses_explicit_owned_server_recovery(self):
        sessions = demand.NativeModelSessions()
        with (
            patch.object(sessions, "call", side_effect=TimeoutError("native control timed out")),
            patch.object(sessions, "_restart_image_server") as restart,
        ):
            sessions._unload_image()
        self.assertIsInstance(restart.call_args.args[0], TimeoutError)

    def test_fault_restart_replaces_only_the_owned_image_process(self):
        sessions = demand.NativeModelSessions()
        audio, old, new = (running_process(pid=pid) for pid in (100, 123, 456))
        sessions.processes = [audio, old]
        with (
            patch.object(demand.launch_util, "kill_process_tree") as kill,
            patch.object(demand.launch_util, "port_listening", return_value=False),
            patch.object(sessions, "_start_image_server", return_value=new),
            patch.object(sessions, "_wait_for_servers"),
        ):
            sessions._restart_image_server(TimeoutError("hung control"))
        kill.assert_called_once_with(123)
        self.assertEqual(sessions.processes, [audio, new])
        self.assertEqual(sessions.restarts[-1]["new_pid"], 456)

    def test_recovery_does_not_replace_an_occupied_unowned_listener(self):
        sessions = demand.NativeModelSessions()
        old = exited_process(pid=123, exit_code=0)
        sessions.processes = [Mock(), old]
        with (
            patch.object(demand.launch_util, "port_listening", return_value=True),
            patch.object(demand.time, "monotonic", side_effect=[0, 0, 11]),
            patch.object(demand.launch_util, "kill_process_tree") as kill,
            patch.object(sessions, "_start_image_server") as start,
            self.assertRaisesRegex(RuntimeError, "unowned"),
        ):
            sessions._restart_image_server(TimeoutError())
        kill.assert_not_called()
        start.assert_not_called()

    def test_failed_native_image_load_restores_audio_without_stopping_servers(self):
        sessions = demand.NativeModelSessions()
        sessions.image_selection = {"recipe": "test", "models": {"model": "native-id"}}
        with (
            patch.object(sessions, "call", side_effect=[{}, RuntimeError("load failed"), {}, {}]) as call,
            patch.object(demand.launch_util, "kill_process_tree") as kill,
            self.assertRaisesRegex(RuntimeError, "load failed"),
        ):
            sessions.change("image")
        self.assertEqual(
            [row.args[1] for row in call.call_args_list],
            ["/v1/models/unload", "/sdcpp/v1/models/load", "/sdcpp/v1/models/unload", "/v1/models/load"],
        )
        kill.assert_not_called()

    def test_cleanup_failure_does_not_skip_other_owned_resources(self):
        pipeline = demand.ImageSessionPipeline(Mock())
        process, frontend = running_process(pid=123), Mock()
        pipeline.kobold_process = process
        pipeline.servers.append(frontend)
        with (
            patch.object(pipeline.native, "close", side_effect=RuntimeError("native cleanup failed")),
            patch.object(demand.launch_util, "kill_process_tree") as kill,
            self.assertRaises(ExceptionGroup),
        ):
            pipeline.close()
        kill.assert_called_once_with(123)
        frontend.shutdown.assert_called_once_with()

    def test_management_bytes_and_native_error_passthrough_for_both_proxies(self):
        observed = []

        class Native(BaseHTTPRequestHandler):
            def do_POST(self):
                observed.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
                proxy_util.send_bytes(self, 409, b"native error: opaque bytes", "text/plain")

            def log_message(self, format, *args):
                pass

        with server(Native) as upstream:
            for module, path in ((proxy_util, "/sdcpp/v1/models/unload"), (tts_proxy, "/v1/models/unload")):
                transform = Mock(side_effect=AssertionError("management must not be transformed"))
                with patch.object(module, "serve_proxy") as serve:
                    if module is proxy_util:
                        module.run_json_proxy(
                            demand.cfg.SDCPP_SERVICE,
                            upstream,
                            transform=transform,
                            transform_paths=sdcpp_proxy.TRANSFORM_PATHS,
                        )
                    else:
                        module.run_tts_json_proxy(demand.cfg.AUDIOCPP_SERVICE, upstream, transform=transform)
                handler = serve.call_args.args[0]
                body = b'{ "opaque-native-command": ??? }\n'
                with server(handler) as url:
                    status, response, _ = request(url + path, body)
                self.assertEqual((status, response), (409, b"native error: opaque bytes"))
                self.assertEqual(observed[-1], (path, body))
                transform.assert_not_called()

    def test_empty_sdcpp_start_does_not_change_standalone(self):
        with patch.object(sdcpp, "launch_process") as launch:
            sdcpp.launch(load_model_on_start=False)
            self.assertNotIn("-m", launch.call_args.args[0])
            sdcpp.launch()
            self.assertIn("-m", launch.call_args.args[0])

    def test_occupied_port_refused_before_starting_any_process(self):
        start = Mock()
        pipeline = demand.ImageSessionPipeline(start)
        with (
            patch.object(demand.launch_util, "llama_server_running", return_value=False),
            patch.object(demand.launch_util, "port_listening", return_value=True),
            self.assertRaisesRegex(RuntimeError, "occupied"),
        ):
            pipeline.start()
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
