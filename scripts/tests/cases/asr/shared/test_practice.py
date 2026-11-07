"""Practice routing/lifecycle contracts without models, microphones or GPU access."""

import io
import json
import queue
import subprocess
import threading
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector, server
from scripts.launchers.asr.shared import live
from scripts.launchers.asr.shared.requests import parse
from scripts.launchers.asr.shared.segment_stream import SegmentStream
from scripts.launchers.audiocpp import asr
from scripts.launchers.koboldcpp import kobold, kobold_lite
from scripts.tests.shared.model_free import fixture_processes
from scripts.tests.shared.process_fixtures import running_process


class PracticeTests(unittest.TestCase):
    def test_chat_model_commands_use_allowlisted_model_and_refuse_browser_paths(self):
        from scripts.config import models
        from scripts.launchers.llamacpp import chat_models, language_practice
        candidate = next(row for row in models.MODELS if row.group == 'llamacpp' and row.path != cfg.GEMMA_AUDIO_ASR.model and 'mmproj' not in row.path.name)
        command = language_practice.chat_command(candidate.label)
        self.assertEqual(command[command.index('-m') + 1], str(candidate.path))
        self.assertNotIn('--mmproj', command)
        with self.assertRaises(ValueError):
            chat_models.path('C:/arbitrary.gguf')

    def test_llm_selection_is_allowlisted_and_shared_gemma_requires_same_weights(self):
        from scripts.launchers.asr.shared.practice_runtime import PracticeRuntime
        from scripts.launchers.asr.shared.practice_selection import Selection
        from scripts.launchers.llamacpp import chat_models
        controls = Selection(cfg.AsrStartupEngine.GEMMA_AUDIO, 'tts')
        runtime = PracticeRuntime.__new__(PracticeRuntime)
        runtime.controls = controls
        self.assertTrue(runtime.shares_gemma())
        other = next(row for row in chat_models.catalog() if row['id'] != controls.llm)
        controls.llm = other['id']
        self.assertFalse(runtime.shares_gemma())
        catalog = {'asr': [{'id': 'asr', 'available': True}], 'tts': [{'id': 'tts', 'available': True}],
                   'llm': [{'id': 'allowed', 'available': True}, {'id': 'missing', 'available': False}]}
        with patch.object(controls, 'catalog', return_value=catalog):
            for key in ('C:/arbitrary.gguf', 'missing'):
                with self.assertRaises(ValueError):
                    controls.select({'asr': 'asr', 'tts': 'tts', 'llm': key})
            self.assertEqual(controls.select({'asr': 'asr', 'tts': 'tts', 'llm': 'allowed'})['llm'], 'allowed')

    def test_http_entry_runs_lifecycle_before_forwarding_a_cold_request(self):
        from scripts.launchers.shared.services import service_lifecycle as owner
        from scripts.launchers.shared.services.service_lifecycle import Service, ServiceLifecycle
        process = running_process(pid=123)
        start = Mock(return_value=process)
        manager = ServiceLifecycle({'chat': Service(start)}, {'llm': 'chat'})
        runtime = SimpleNamespace(lifecycle=manager, stage_for=lambda method, path: 'llm')
        def serve(handler, *_args):
            instance = handler.__new__(handler)
            instance.path = '/v1/chat/completions'
            instance.headers = Message()
            instance._route_request = Mock()
            instance.do_POST()
            start.assert_called_once()
            instance._route_request.assert_called_once_with('POST')
        with patch.object(server, 'serve_proxy', side_effect=serve), patch.object(live, 'Sessions'), patch.object(owner, 'stop_owned'):
            server.run_proxy(cfg.AsrStartupEngine.AUDIOCPP, '127.0.0.1', 9999, runtime=runtime)
            manager.close()
        self.assertEqual([row['phase'] for row in manager.events], ['startup_ready', 'request'])

    def test_on_demand_services_split_timings_and_keep_other_shared_models(self):
        from scripts.launchers.shared.services import service_lifecycle as owner
        from scripts.launchers.shared.services.service_lifecycle import Service, ServiceLifecycle
        clock = [0.0]
        process = running_process(pid=123)
        def start():
            clock[0] += 10
            return process
        def load(_stage):
            clock[0] += 20
        start_mock, load_mock, unload_mock = Mock(side_effect=start), Mock(side_effect=load), Mock()
        service = Service(start_mock, load_mock, unload_mock)
        manager = ServiceLifecycle({'audio': service}, {'asr': 'audio', 'tts': 'audio'},
                                   models={'asr': 'asr-q8.gguf', 'tts': 'kokoro-q8.gguf'})
        start_mock.assert_not_called()
        with patch.object(owner.time, 'perf_counter', side_effect=lambda: clock[0]), patch.object(owner, 'stop_owned') as stop:
            with manager.use('asr'):
                clock[0] += 3
            manager.ensure('tts')
            manager.release('asr')
            stop.assert_not_called()
            self.assertEqual(manager.states['tts'], 'loaded')
            unload_mock.assert_called_once_with('asr')
            manager.release('tts')
            stop.assert_called_once_with(process)
        start_mock.assert_called_once()
        phases = {row['phase']: row for row in manager.events[:3]}
        self.assertEqual(phases['startup_ready']['duration_ms'], 10000)
        self.assertEqual(phases['model_load']['duration_ms'], 20000)
        self.assertEqual(phases['request']['duration_ms'], 3000)
        self.assertTrue(phases['request']['excludes_startup'])
        manager.models['asr'] = 'different.gguf'
        self.assertEqual(phases['request']['model'], 'asr-q8.gguf')
        self.assertEqual(phases['model_load']['model'], 'asr-q8.gguf')

    def test_reused_services_cannot_be_unloaded_by_workspace(self):
        from scripts.launchers.shared.services import service_lifecycle as owner
        from scripts.launchers.shared.services.service_lifecycle import Service, ServiceLifecycle
        service = Service(lambda: None)
        manager = ServiceLifecycle({'chat': service}, {'llm': 'chat'})
        manager.ensure('llm')
        with patch.object(owner, 'stop_owned') as stop:
            with self.assertRaisesRegex(RuntimeError, 'not owned'):
                manager.release('llm')
            manager.close()
        stop.assert_not_called()
        self.assertEqual(manager.states['llm'], 'external')

    def test_active_requests_block_unload_and_failures_remain_visible(self):
        from scripts.launchers.shared.services import service_lifecycle as owner
        from scripts.launchers.shared.services.service_lifecycle import Service, ServiceLifecycle
        process = running_process(pid=1)
        manager = ServiceLifecycle({'chat': Service(lambda: process)}, {'llm': 'chat'})
        with patch.object(owner, 'stop_owned'):
            with manager.use('llm'), self.assertRaisesRegex(RuntimeError, 'active'):
                manager.release('llm')
            manager.close()
        broken = Service(lambda: process, Mock(side_effect=RuntimeError('synthetic model load failure')))
        failed = ServiceLifecycle({'audio': broken}, {'tts': 'audio'})
        with self.assertRaisesRegex(RuntimeError, 'synthetic'):
            failed.ensure('tts')
        self.assertEqual(failed.states['tts'], 'failed')
        self.assertEqual(failed.events[-1]['phase'], 'load_failed')
        with patch.object(owner, 'stop_owned') as stop:
            failed.release('tts')
            stop.assert_called_once_with(process)

    def test_unloading_tts_does_not_cancel_asr_capture(self):
        from scripts.launchers.asr.shared.lifecycle_http import change
        runtime, sessions = Mock(), Mock()
        change('/workspace/lifecycle', {'stage': 'tts', 'action': 'unload'}, runtime, sessions)
        sessions.reset.assert_not_called()
        runtime.lifecycle.release.assert_called_once_with('tts')

    def test_practice_and_tests_have_one_html_without_duplicate_controls(self):
        from html.parser import HTMLParser

        from scripts.launchers.audiocpp import tts_proxy
        ids = []
        class Controls(HTMLParser):
            def handle_starttag(self, tag, attrs):
                ids.extend(value for name, value in attrs if name == 'id')
        practice = tts_proxy._test_asset('/practice')
        tests = tts_proxy._test_asset('/test/')
        self.assertIsNotNone(practice)
        self.assertEqual(practice, tests)
        assert practice is not None
        html = practice[0].decode('utf-8')
        Controls().feed(html)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn('<iframe', html)
        self.assertNotIn('Type a greeting', html)
        self.assertNotIn('id="instructions"', html)
        self.assertIn('<div id="history" role="log" aria-live="polite"></div>', html)
        self.assertIn('<div id="workspace-options">', html)

        self.assertNotIn('detail-level', ids)
        self.assertNotIn('show-metrics', ids)
        self.assertIn('html[data-view=practice] .test-only', html)
        self.assertIn('document.documentElement.dataset.view', html)
        self.assertNotIn('capture-stop', ids)
        composer = html.split('<form id="form">', 1)[1].split('</form>', 1)[0]
        self.assertIn('id="record"', composer)
        self.assertIn('id="upload-turns"', composer)
        self.assertIn('<details id="measurements">', html)
        for name in ('enable-asr', 'enable-llm', 'enable-tts', 'measurements'):
            self.assertIn(name, ids)

    def test_shared_test_page_uses_actual_practice_tts_without_advertising_streaming(self):
        from scripts.launchers.asr.shared import http_api
        spec = {'id': cfg.LANGUAGE_PRACTICE.tts_model, 'family': 'kokoro_tts', 'path': 'selected.gguf'}
        with patch.object(http_api.practice_models, 'tts_spec', return_value=spec), patch.object(
            http_api.audiocpp_catalog, 'runtime_defaults', return_value={}) as defaults:
            result = http_api.test_defaults()
        self.assertEqual(defaults.call_args.kwargs['specs'], [spec])
        self.assertEqual(defaults.call_args.args[0].model, cfg.LANGUAGE_PRACTICE.tts_model)
        self.assertFalse(result['streaming_supported'])
        self.assertTrue(result['practice_gateway'])
        self.assertEqual(result['practice_url'], '/practice')

    def test_launcher_starts_only_gateway_without_eager_models(self):
        from scripts.launchers.asr.shared import practice_asr, practice_models
        from scripts.launchers.asr.shared import workspace as practice
        from scripts.tests.shared.paths import CasePaths
        with CasePaths(__file__).temporary_directory() as folder, patch.object(
            practice.project_cfg, 'component', return_value=SimpleNamespace(state_dir=Path(folder))), patch.object(
            practice.launch_util, 'port_listening', return_value=False), patch.object(
            practice, 'run_session', return_value=False) as run, patch.object(
            practice_asr, 'asr_models', return_value=[]), patch.object(
            practice_models, 'active_tts_id', None), patch('sys.argv', ['practice', '--no-browser']):
            chat = Mock()
            practice.main(chat)
        chat.assert_not_called()
        run.assert_called_once()

    def test_cohere_resident_upload_sets_native_model_identifier(self):
        from scripts.launchers.asr.shared import resident_backend
        from scripts.launchers.asr.shared.resident_backend import ResidentBackend
        from scripts.launchers.shared.transport.multipart import audio_upload
        body, kind = audio_upload(b'wave', {'language': 'en'})
        with patch.object(resident_backend.requests, 'post', return_value=(b'{"text":"hello"}', 'application/json')) as post:
            ResidentBackend(cfg.COHERE_ASR).transcribe(body, kind)
        self.assertIn(b'benchmark-asr', post.call_args.args[1])

    def test_model_switch_validates_allowlist_and_refuses_active_requests(self):
        from scripts.launchers.asr.shared.practice_selection import Selection
        control = Selection(cfg.AsrStartupEngine.AUDIOCPP, 'tts')
        catalog = {'asr': [{'id': 'known', 'available': True}], 'tts': [{'id': 'tts', 'available': True}]}
        with patch.object(control, 'catalog', return_value=catalog):
            with self.assertRaises(ValueError):
                control.select({'asr': 'C:/arbitrary.exe', 'tts': 'tts'})
            with control.request(), control.request(), self.assertRaises(RuntimeError):
                control.select({'asr': 'known', 'tts': 'tts'})
            self.assertEqual(control.select({'asr': 'known', 'tts': 'tts'}), {'asr': 'known', 'tts': 'tts'})
            with self.assertRaises(RuntimeError):
                control.select({'asr': 'known', 'tts': 'tts'})

    def test_kokoro_missing_japanese_resources_are_visible_not_claimed_ready(self):
        from scripts.launchers.audiocpp import kokoro
        spec = {'languages': ['en-us', 'ja', 'zh'], 'ui': {'builtin_voices': ['af_heart', 'jf_alpha', 'zf_xiaobei']}}
        metadata = {'audiocpp.model_spec.json': json.dumps(spec),
                    'audiocpp.embedded_files.names': ['g2p/ja.json', 'g2p/zh.json']}
        with patch.object(kokoro, 'inspect_metadata', return_value={'metadata': metadata}):
            rows = {row['locale']: row for row in kokoro.language_profiles()}
        self.assertFalse(rows['ja']['available'])
        self.assertIn('unidic/dicrc', rows['ja']['unavailable_reason'])
        self.assertTrue(rows['zh']['available'])
        self.assertTrue(rows['en-us']['available'])

    def test_language_options_intersect_selected_asr_with_installed_tts(self):
        from scripts.config import models
        from scripts.launchers.asr.shared import languages
        catalog = {'language_names': {'en': 'English', 'ja': 'Japanese', 'th': 'Thai'}, 'models': [
            {'name': 'Selected ASR', 'model_ids': ['checkpoint'], 'tasks': ['asr'],
             'languages': ['en', 'ja', 'th'], 'notes': '',
             'coverage_tiers': {'transcription_ready': ['en-US', 'ja-JP'], 'adaptation_required': ['th-TH']}}]}
        model = SimpleNamespace(label='checkpoint', path=Path('selected.gguf'))
        voices = [{'code': code, 'locale': code, 'voice': code + '-voice'} for code in ('en', 'ja', 'th')]
        with patch.object(languages.model_languages, 'read_catalog', return_value=catalog), patch.object(
            languages.selector, 'model', return_value=Path('selected.gguf')), patch.object(models, 'MODELS', [model]), patch.object(
            languages.practice_models, 'language_profiles', return_value=voices), patch.object(
            languages.practice_models, 'tts_models', return_value=[
                {'id': 'tts', 'label': 'TTS', 'default_language': 'en-us'}
            ]), patch.object(
            languages.practice_models, 'tts_id', return_value='tts'):
            result = languages.capabilities(cfg.AsrStartupEngine.AUDIOCPP)
        self.assertEqual({row['code'] for row in result['common']}, {'en', 'ja'})
        self.assertEqual(len(result['asr']['languages']), 3)

    def test_nemotron_file_upload_uses_streaming_model_transport(self):
        stream = Mock(events=queue.Queue(), done=threading.Event())
        stream.events.put({"type": "transcript.text.done", "text": "Hello"})
        import numpy as np
        samples = np.zeros(512, dtype=np.float32)
        from scripts.launchers.shared.transport.multipart import audio_upload

        body, content_type = audio_upload(b"dummy", {"language": "en"})
        with patch("scripts.launchers.shared.media.audio.decode_audio", return_value=(samples, 16000)), patch("scripts.launchers.shared.media.audio.mono_resample", return_value=samples), patch.object(asr, "StreamingPost", return_value=stream) as transport:
            data, kind = asr.transcribe(body, content_type)
        self.assertIn("/v1/audio/transcriptions/live?", transport.call_args.args[0])
        self.assertEqual(json.loads(data), {"text": "Hello"})
        self.assertEqual(kind, "application/json")
        stream.finish.assert_called_once()
        stream.close.assert_called_once()

    def test_segment_decoding_waits_for_vad_end_and_emits_final_text(self):
        backend = Mock()
        backend.transcribe.return_value = (b'{"text":"Bonjour"}', "application/json")
        stream = SegmentStream(backend, "fr")
        stream.start()
        stream.send(bytes(2048))
        backend.transcribe.assert_not_called()
        stream.finish()
        self.assertTrue(stream.done.wait(2))
        event = stream.events.get_nowait()
        self.assertEqual(event["type"], "transcript.text.done")
        self.assertEqual(event["text"], "Bonjour")
        request = parse(*backend.transcribe.call_args.args)
        self.assertEqual(request.language, "fr")
        self.assertTrue(request.audio.startswith(b"RIFF"))
        stream.close()

    def test_segment_failures_and_buffer_limit_are_explicit(self):
        backend = Mock()
        backend.transcribe.return_value = (b'{"text":""}', "application/json")
        stream = SegmentStream(backend, "en")
        with self.assertRaisesRegex(RuntimeError, "buffer limit"):
            stream.send(bytes(16000 * 2 * 33))
        stream.send(bytes(1024))
        stream.finish()
        self.assertTrue(stream.done.wait(2))
        self.assertEqual(stream.events.get_nowait()["type"], "error")
        stream.close()

    def test_all_selected_alternatives_have_automatic_turn_routes(self):
        for engine in (cfg.AsrStartupEngine.SPEECHCPP, cfg.AsrStartupEngine.WHISPER_VULKAN, cfg.AsrStartupEngine.PARAKEET_V3):
            self.assertTrue(live.supported(engine))
            self.assertTrue(selector.model(engine).suffix in (".gguf", ".bin"))
        self.assertFalse(live.supported(cfg.AsrStartupEngine.QWEN3_ASR))

    @fixture_processes()
    def test_browser_capture_turn_and_reply_contract(self):
        for mode in ([], ["--asr"], ["--practice"], ["--cached"], ["--practice", "--cached"]):
            with self.subTest(mode=mode):
                result = subprocess.run([cfg.PI_CLIENT.node_cmd, str(Path(__file__).with_name("practice.cjs")), *mode], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sessions_bound_frames_and_preserve_ownership(self):
        turns = Mock()
        turns.push.return_value = [{"type": "speech_start"}]
        turns.poll.return_value = [{"type": "transcript.text.done", "text": "Bonjour"}]
        sessions = live.Sessions()
        try:
            with (
                patch("scripts.launchers.asr.shared.languages.capabilities", return_value={"asr": {"ready_languages": ["en", "fr"]}}),
                patch.object(live, "Turns", return_value=turns),
            ):
                token = sessions.request("/asr/live/start", b'{"language":"fr"}')["session"]
                with self.assertRaisesRegex(ValueError, "Already listening"):
                    sessions.request("/asr/live/start", b"{}")
                with self.assertRaisesRegex(ValueError, "expired"):
                    sessions.request("/asr/live/wrong/stop", b"")
                with self.assertRaisesRegex(ValueError, "complete"):
                    sessions.request(f"/asr/live/{token}/audio", b"x")
                result = sessions.request(f"/asr/live/{token}/audio", bytes(2048))
                self.assertEqual(turns.push.call_count, 2)
                self.assertEqual(result["events"][-1]["text"], "Bonjour")
                sessions.request(f"/asr/live/{token}/stop", b"")
                turns.close.assert_called_once()
        finally:
            sessions.close()
        turns.close.assert_called_once()

    def test_failed_upload_closes_helper(self):
        turns = Mock()
        turns.push.side_effect = RuntimeError("backend died")
        sessions = live.Sessions()
        try:
            with (
                patch("scripts.launchers.asr.shared.languages.capabilities", return_value={"asr": {"ready_languages": ["en"]}}),
                patch.object(live, "Turns", return_value=turns),
            ):
                token = sessions.request("/asr/live/start", b"{}")["session"]
                with self.assertRaisesRegex(RuntimeError, "backend died"):
                    sessions.request(f"/asr/live/{token}/audio", bytes(1024))
            self.assertIsNone(sessions.turns)
            turns.close.assert_called_once()
        finally:
            sessions.close()

    def test_origin_and_payload_limits_precede_native_start(self):
        sessions = live.Sessions()
        try:
            for origin, length, expected in (("http://other.invalid", "2", 403), (None, "32769", 400)):
                headers = Message()
                headers["Host"] = "localhost:9999"
                headers["Content-Length"] = length
                if origin:
                    headers["Origin"] = origin
                handler = SimpleNamespace(headers=headers, rfile=io.BytesIO(b"{}"))
                with patch.object(live, "send_json_error") as error, patch.object(live, "Turns") as create:
                    sessions.route(handler, "POST", "/asr/live/start", cfg.AsrStartupEngine.AUDIOCPP)
                    self.assertEqual(error.call_args.args[1], expected)
                    create.assert_not_called()
        finally:
            sessions.close()

    def test_both_gateways_share_live_routes_and_close_sessions(self):
        def serve(handler, *_args):
            instance = handler.__new__(handler)
            instance.path = "/asr/live/start"
            instance._forward("POST")
        for gateway in (server, kobold_lite):
            sessions = Mock()
            sessions.route.return_value = True
            with patch.object(live, "Sessions", return_value=sessions), patch.object(gateway, "serve_proxy", side_effect=serve):
                if gateway is server:
                    server.run_proxy(cfg.AsrStartupEngine.AUDIOCPP, "127.0.0.1", 9999)
                else:
                    kobold_lite.run_proxy()
            sessions.route.assert_called_once()
            sessions.close.assert_called_once()

    def test_combined_server_skips_separate_kobold_tts(self):
        with patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.AUDIOCPP), patch.object(kobold, "PROXY_SERVICES", [kobold.PROXY_SERVICES[0]]), patch.object(kobold, "launch_module") as launch:
            processes = []
            kobold.start_proxy_services(processes, "shared")
            self.assertEqual(processes, [])
            launch.assert_not_called()
        self.assertIs(selector.backend(cfg.AsrStartupEngine.AUDIOCPP), asr)
        config = asr.speech_config(9999)
        self.assertEqual([model["id"] for model in config["models"]], ["benchmark-asr", cfg.LANGUAGE_PRACTICE.tts_model])
        self.assertFalse(config["lazy_load"])
        self.assertEqual(cfg.ASR_SERVICE.engine, cfg.AsrStartupEngine.AUDIOCPP)


if __name__ == "__main__":
    unittest.main()
