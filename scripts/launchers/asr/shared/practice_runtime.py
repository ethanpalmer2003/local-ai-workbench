"""Speech workspace policy on the generic owned-service lifecycle."""

import json
import time
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector
from scripts.launchers.asr.shared import practice_models
from scripts.launchers.audiocpp import asr, model_management
from scripts.launchers.llamacpp import chat_models
from scripts.launchers.shared.services.service_lifecycle import Service, ServiceLifecycle


class PracticeRuntime:
    def __init__(self, controls, start_chat, context, no_tts=False):
        self.controls, self.start_chat, self.context = controls, start_chat, context
        self.no_tts = no_tts
        folder = project_cfg.component("asr/shared").logs_dir
        folder.mkdir(parents=True, exist_ok=True)
        self.log = folder / f"practice-lifecycle-{time.time_ns()}.jsonl"
        self.lifecycle = self.build()

    def save(self, event):
        with self.log.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    {
                        **event,
                        "execution_context": self.context,
                        "asr_model": self.controls.engine.value,
                        "tts_model": self.controls.tts,
                        "llm_model": str(self.llm_path()),
                    }
                )
                + "\n"
            )

    def audio_service(self, shared: bool):
        config: dict[str, Any] = (
            asr.speech_config(cfg.AUDIOCPP_VAD.server_port, self.controls.engine.value)
            if shared
            else {"backend": "vulkan", "threads": cfg.KOKORO_TTS.threads, "models": [practice_models.tts_spec()]}
        )
        port = cfg.AUDIOCPP_VAD.server_port if shared else cfg.AUDIOCPP_SERVICE.internal_port
        specs = {"asr": config["models"][0], "tts": config["models"][-1]}
        url = f"http://127.0.0.1:{port}"
        return Service(
            lambda: model_management.start(config, port),
            lambda stage: model_management.post(url, "load", specs[stage]),
            lambda stage: model_management.post(url, "unload", {"id": specs[stage]["id"]}),
        )

    def build(self):
        engine = self.controls.engine
        shared = engine in cfg.AUDIOCPP_ASR_ENGINES
        gemma = self.shares_gemma()
        services = {
            "audio": self.audio_service(shared),
            "asr": Service(lambda: selector.backend(engine).start()),
            "llm": Service(lambda: self.start_chat(self.controls.llm)),
        }
        groups = {"asr": "audio" if shared else "asr", "tts": "audio", "llm": "asr" if gemma else "llm"}
        return ServiceLifecycle(
            services,
            groups,
            self.save,
            {"asr": selector.model(engine).name, "tts": self.controls.tts, "llm": self.llm_path().name},
        )

    def stage_for(self, method, path):
        if method != "POST":
            return None
        if path in ("/v1/audio/transcriptions", "/api/extra/transcribe", "/asr/live/start"):
            return "asr"
        if path == "/v1/audio/speech":
            if self.no_tts:
                raise RuntimeError("TTS is disabled by --no-tts")
            return "tts"
        if path in ("/v1/chat/completions", "/completion", "/v1/completions"):
            return "llm"
        return None

    def load(self, stage):
        if stage == "tts" and self.no_tts:
            raise ValueError("TTS is disabled by --no-tts")
        self.lifecycle.ensure(stage)

    def speech_url(self):
        return (
            asr.url()
            if self.controls.engine in cfg.AUDIOCPP_ASR_ENGINES
            else f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}"
        )

    def llm_path(self):
        return chat_models.path(self.controls.llm)

    def shares_gemma(self):
        return self.controls.engine == cfg.AsrStartupEngine.GEMMA_AUDIO and self.llm_path() == cfg.GEMMA_AUDIO_ASR.model

    def chat_url(self):
        return (
            selector.backend(self.controls.engine).url()
            if self.shares_gemma()
            else f"http://127.0.0.1:{cfg.LLAMACPP_PRACTICE.internal_port}"
        )

    def snapshot(self):
        return {**self.lifecycle.snapshot(), "log": str(self.log), "on_demand": True}

    def select(self, value, before_change=lambda: None):
        selected = self.controls.select(value)
        try:
            with self.lifecycle.lock:
                if self.lifecycle.active:
                    raise RuntimeError("Wait for model requests before switching")
                before_change()
                self.lifecycle.close()
                self.controls.engine = cfg.AsrStartupEngine(selected["asr"])
                self.controls.tts = selected["tts"]
                self.controls.llm = selected.get("llm", self.controls.llm)
                practice_models.active_tts_id = self.controls.tts
                self.lifecycle = self.build()
                self.controls.error = None
                self.persist()
        finally:
            self.controls.pending = None
        return self.controls.catalog()

    def persist(self):
        state = project_cfg.component("asr/shared").state_dir / "practice_models.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            json.dumps({"asr": self.controls.engine.value, "tts": self.controls.tts, "llm": self.controls.llm}),
            encoding="utf-8",
        )

    def close(self):
        self.lifecycle.close()
