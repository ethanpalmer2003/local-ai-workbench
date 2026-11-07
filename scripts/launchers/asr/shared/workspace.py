"""Shared speech-workspace entry flow; backend adapters supply the chat starter."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import server
from scripts.launchers.asr.shared import practice_models
from scripts.launchers.asr.shared.practice_selection import Selection
from scripts.launchers.runtime.browser import open_browser


def run_session(args, controls, start_chat) -> bool:
    from scripts.launchers.asr.shared.practice_runtime import PracticeRuntime
    from scripts.launchers.runtime.execution_context import execution_context

    runtime = PracticeRuntime(controls, start_chat, execution_context(), args.no_tts)
    try:

        def on_server(_server):
            runtime.persist()
            if not args.no_browser:
                path = {'llama': '/?ui=llama', 'test': '/test/', 'workspace': '/practice'}[args.ui]
                if args.ui == 'test' and args.test_mode != 'all':
                    path += f'?mode={args.test_mode}'
                url = f"http://localhost:{cfg.LLAMACPP_PRACTICE.port}{path}"
                try:
                    open_browser(url)
                except OSError as error:
                    print(f"Could not open the workspace in the default browser: {error}", flush=True)

        return bool(server.run_proxy(
            controls.engine,
            cfg.LLAMACPP_PRACTICE.host,
            cfg.LLAMACPP_PRACTICE.port,
            runtime.chat_url(),
            runtime.speech_url(),
            on_server,
            controls,
            runtime,
        ))
    finally:
        runtime.close()


def main(start_chat) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcription-engine",
        choices=[item.value for item in cfg.AsrStartupEngine if item not in (
            cfg.AsrStartupEngine.EMBEDDED, cfg.AsrStartupEngine.GEMMA_KOBOLD)],
    )
    parser.add_argument("--no-tts", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--ui", choices=('workspace', 'llama', 'test'), default='workspace')
    parser.add_argument("--test-mode", choices=('all', 'asr', 'llm'), default='all',
                        help="Stages enabled on /test/ when --ui test is selected.")
    args = parser.parse_args()
    print(f"Starting speech workspace on port {cfg.LLAMACPP_PRACTICE.port}", flush=True)
    reuse = cfg.LAUNCH.existing_service_policy == cfg.ExistingServicePolicy.REUSE
    if reuse and launch_util.port_listening(cfg.LLAMACPP_PRACTICE.port):
        url = f"http://127.0.0.1:{cfg.LLAMACPP_PRACTICE.port}/proxy/config"
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                is_practice_gateway = json.load(response).get("practice_gateway") is True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            is_practice_gateway = False
        if not is_practice_gateway:
            raise RuntimeError("Practice port is occupied by an unhealthy or unrelated service")
        print(f"Reusing practice service on port {cfg.LLAMACPP_PRACTICE.port}")
        if not args.no_browser:
            path = {'llama': '/?ui=llama', 'test': '/test/', 'workspace': '/practice'}[args.ui]
            if args.ui == 'test' and args.test_mode != 'all':
                path += f'?mode={args.test_mode}'
            open_browser(f"http://localhost:{cfg.LLAMACPP_PRACTICE.port}{path}")
        return
    launch_util.prepare_service_port(cfg.LLAMACPP_PRACTICE.port, "speech workspace")
    state = project_cfg.component("asr/shared").state_dir / "practice_models.json"
    saved = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}
    controls = Selection(
        cfg.AsrStartupEngine(args.transcription_engine or saved.get("asr", cfg.ASR_SERVICE.engine.value)),
        saved.get("tts"),
        saved.get("llm"),
    )
    practice_models.active_tts_id = controls.tts
    try:
        restart = run_session(args, controls, start_chat)
    except KeyboardInterrupt:
        return
    if restart:
        original = getattr(sys, 'orig_argv', [sys.executable, sys.argv[0], *sys.argv[1:]])
        command = list(original[1:])
        if '--no-browser' not in command:
            command.append('--no-browser')
        os.execv(sys.executable, [sys.executable, *command])
