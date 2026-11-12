"""Resident same-voice Piper/Sherpa benchmark; no packages are installed or changed."""

import argparse
import ctypes as c
import hashlib
import importlib
import json
import os
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle, summarize_requests
from scripts.benchmarks.shared.paths import BenchmarkPaths
from scripts.benchmarks.tts_engines.fixtures import TEXT, voice_assets
from scripts.config import models as model_cfg
from scripts.config import project_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution


def sherpa_types(root):
    from scripts.launchers.shared.native_abi.cabi import structures

    header = (root / "include/sherpa-onnx/c-api/c-api.h").read_text(encoding="utf-8")
    return structures(
        header, lambda name: name.startswith("SherpaOnnxOfflineTts") or name == "SherpaOnnxGeneratedAudio"
    )


class SherpaVoice:
    def __init__(self, profile="lessac-medium"):
        import numpy as np

        self.np = np
        root = cfg.component("tts/sherpa-onnx").framework_dir
        from scripts.launchers.shared.native_abi.native_library import NativeLibrary

        self.types = sherpa_types(root)
        self.library = NativeLibrary(
            root / "lib/sherpa-onnx-c-api.dll", search_dirs=(root / "lib",), prefix="SherpaOnnx"
        )
        self.lib = self.library.dll
        config_type = self.types["SherpaOnnxOfflineTtsConfig"]
        config = config_type()
        model, tokens, lexicon = voice_assets(profile)
        self.sid = 0
        if profile == "kokoro-v1.0-int8":
            config.model.kokoro.model = str(model).encode()
            config.model.kokoro.tokens = str(tokens).encode()
            config.model.kokoro.lexicon = str(lexicon).encode()
            config.model.kokoro.voices = str(model_cfg.path("tts/sherpa-onnx/kokoro-v1.0-int8/voices")).encode()
            config.model.kokoro.length_scale = 1
            self.sid = 3  # af_heart in pinned v1.0 table; verify against ONNX metadata before a new revision.
        else:
            config.model.vits.model = str(model).encode()
            config.model.vits.tokens = str(tokens).encode()
            config.model.vits.lexicon = str(lexicon).encode()
            config.model.vits.noise_scale = 0.667
            config.model.vits.noise_scale_w = 0.8
            config.model.vits.length_scale = 1
        config.model.num_threads = 5 if profile == "kokoro-v1.0-int8" else 4
        config.model.provider = b"cpu"
        config.max_num_sentences = 1
        config.silence_scale = 0.2
        self.library.bind("CreateOfflineTts", [c.POINTER(config_type)], c.c_void_p)
        self.library.bind(
            "OfflineTtsGenerate",
            [c.c_void_p, c.c_char_p, c.c_int32, c.c_float],
            c.POINTER(self.types["SherpaOnnxGeneratedAudio"]),
        )
        self.library.bind("DestroyOfflineTtsGeneratedAudio", [c.POINTER(self.types["SherpaOnnxGeneratedAudio"])], None)
        self.library.bind("DestroyOfflineTts", [c.c_void_p], None)
        self.voice = self.lib.SherpaOnnxCreateOfflineTts(c.byref(config))
        if not self.voice:
            self.library.close()
            raise RuntimeError("Sherpa could not load the configured voice")

    def generate(self, text):
        audio = self.lib.SherpaOnnxOfflineTtsGenerate(self.voice, text.encode(), self.sid, 1)
        if not audio:
            raise RuntimeError("Sherpa returned no audio")
        try:
            value = audio.contents
            return self.np.ctypeslib.as_array(value.samples, shape=(value.n,)).copy(), value.sample_rate
        finally:
            self.lib.SherpaOnnxDestroyOfflineTtsGeneratedAudio(audio)

    def close(self):
        self.lib.SherpaOnnxDestroyOfflineTts(self.voice)
        self.library.close()


def worker(engine, samples, run, texts=None, profile="lessac-medium"):
    import numpy as np

    context = dict(require_native_execution("Resident TTS benchmark"))
    voice: Any = None
    model, _, _ = voice_assets(profile)

    def load():
        nonlocal voice
        if engine == "sherpa-onnx":
            voice = SherpaVoice(profile)
        else:
            sys.path.insert(0, str(cfg.component("tts/piper").framework_dir))
            voice = importlib.import_module("piper.voice").PiperVoice.load(str(model))

    texts = texts or [TEXT]

    def infer(text=TEXT):
        if engine == "sherpa-onnx":
            return voice.generate(text)
        chunks = list(voice.synthesize(text))
        return np.concatenate([chunk.audio_float_array for chunk in chunks]), chunks[0].sample_rate

    def cleanup():
        if engine == "sherpa-onnx" and voice is not None:
            voice.close()

    rows = []
    timer = BenchmarkLifecycle(lambda: f"{os.getpid()}:{id(voice)}" if voice is not None else "", cleanup)
    try:
        with timer:
            timer.prepare(lambda: None, load, reused=True)
            timer.warmup(lambda: infer(texts[0]))
            for index in range(samples):
                text = texts[index % len(texts)]
                (audio, rate), timing = timer.measure(lambda: infer(text))
                if len(audio) == 0:
                    raise ValueError("Empty generated waveform")
                output = run.artifacts / f"{engine}-{index}.wav"
                with wave.open(str(output), "wb") as wav:
                    wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                    wav.writeframes((np.clip(audio, -1, 1) * 32767).astype("int16").tobytes())
                rows.append(
                    {
                        **timing,
                        "text": text,
                        "audio_seconds": len(audio) / rate,
                        "rtf": timing["request_seconds"] / (len(audio) / rate),
                        "wav": str(output),
                    }
                )
    finally:
        payload = {
            "engine": engine,
            "execution_context": context,
            "profile": profile,
            "model": str(model),
            "texts": texts,
            "threads": (5 if profile == "kokoro-v1.0-int8" else 4) if engine == "sherpa-onnx" else "runtime default",
            "speaker": "af_heart" if profile == "kokoro-v1.0-int8" else "lessac",
            "request_boundary": "phonemization, synthesis and float waveform collection; excludes WAV conversion/saving",
            "startup_observability": "Interpreter/import startup not instrumented; model_load includes runtime imports",
            "benchmark": timer.record(),
            "samples": rows,
            "summary": summarize_requests(rows),
        }
        with model.open("rb") as source:
            payload["model_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
        (run.artifacts / f"{engine}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("piper", "sherpa-onnx"))
    parser.add_argument("--samples", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--texts", nargs="+", help="Explicit matching inputs for cross-framework screens")
    parser.add_argument(
        "--profile", choices=("lessac-medium", "lessac-high", "kokoro-v1.0-int8"), default="lessac-medium"
    )
    args = parser.parse_args()
    if args.profile == "lessac-high" and args.engine != "piper":
        parser.error("Lessac-high currently requires --engine piper")
    if args.profile == "kokoro-v1.0-int8" and args.engine != "sherpa-onnx":
        parser.error("Kokoro requires --engine sherpa-onnx")
    from scripts.benchmarks.shared.paths import RunPaths

    run = RunPaths(args.root) if args.root else BenchmarkPaths(__file__).new_run()
    run.create()
    if args.engine:
        worker(args.engine, args.samples, run, args.texts, args.profile)
        return 0
    context = dict(require_native_execution("Resident Piper/Sherpa comparison"))
    failures = []
    for engine in ("piper", "sherpa-onnx"):
        command = [
            sys.executable,
            "-m",
            "scripts.benchmarks.tts_engines.resident",
            "--engine",
            engine,
            "--samples",
            str(args.samples),
            "--root",
            str(run.root),
        ]
        if args.texts:
            command.extend(["--texts", *args.texts])
        with (run.logs / f"{engine}.log").open("wb") as log:
            try:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=100)
                if result.returncode:
                    failures.append(engine)
            except subprocess.TimeoutExpired:
                failures.append(engine)
    (run.artifacts / "context.json").write_text(json.dumps(context, indent=2), encoding="utf-8")
    # - The aggregate starts both workers without --profile, so both read the default lessac-medium voice.
    report_path = run.artifacts / "report.json"
    if report_path.is_file():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        # - the outcome folder says unreviewed; the matrix judges the recorded status instead
        payload["status"] = "failed" if failures else "completed"
        payload["provenance"] = provenance.block(
            subject=str(payload.get("name", "tts_engines/resident")),
            config={"profile": "lessac-medium", "samples": args.samples, "execution_context": context},
            frameworks=[provenance.framework_state("tts/piper"), provenance.framework_state("tts/sherpa-onnx")],
            models=[provenance.file_identity("voice", voice_assets("lessac-medium")[0])],
        )
        report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[OUTPUT] {run.root}; failures={failures}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
