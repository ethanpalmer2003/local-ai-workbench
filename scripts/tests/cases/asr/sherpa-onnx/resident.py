"""Persistent Sherpa online recognizer using the installed Windows C API."""

import ctypes as c
import hashlib
import json
import os
import time
from typing import Any

from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle, summarize_requests
from scripts.config import models
from scripts.config import project_config as cfg
from scripts.launchers.shared.native_abi.cabi import structures
from scripts.tests.cases.asr.shared.metrics import unicode_errors


class Recognizer:
    def __init__(self):
        root = cfg.component("asr/sherpa-onnx").framework_dir
        header = (root / "include/sherpa-onnx/c-api/c-api.h").read_text(encoding="utf-8")
        suffixes = (
            "OnlineTransducerModelConfig",
            "OnlineParaformerModelConfig",
            "OnlineZipformer2CtcModelConfig",
            "OnlineNemoCtcModelConfig",
            "OnlineToneCtcModelConfig",
            "OnlineModelConfig",
            "FeatureConfig",
            "OnlineCtcFstDecoderConfig",
            "HomophoneReplacerConfig",
            "OnlineRecognizerConfig",
        )
        selected = {"SherpaOnnx" + suffix for suffix in suffixes}
        types = structures(header, lambda name: name in selected)
        from scripts.launchers.shared.native_abi.native_library import NativeLibrary

        self.library = NativeLibrary(
            root / "lib/sherpa-onnx-c-api.dll", search_dirs=(root / "lib",), prefix="SherpaOnnx"
        )
        self.lib = self.library.dll
        config_type = types["SherpaOnnxOnlineRecognizerConfig"]
        config = config_type()
        config.feat_config.sample_rate = 16000
        config.feat_config.feature_dim = 80
        for field in ("encoder", "decoder", "joiner"):
            setattr(
                config.model_config.transducer,
                field,
                str(models.path("asr/sherpa-onnx/zipformer-en/" + field)).encode(),
            )
        config.model_config.tokens = str(models.path("asr/sherpa-onnx/zipformer-en/tokens")).encode()
        config.model_config.num_threads = 4
        config.model_config.provider = b"cpu"
        config.decoding_method = b"greedy_search"
        config.max_active_paths = 4
        self.library.bind("CreateOnlineRecognizer", [c.POINTER(config_type)], c.c_void_p)
        self.library.bind("DestroyOnlineRecognizer", [c.c_void_p], None)
        self.library.bind("CreateOnlineStream", [c.c_void_p], c.c_void_p)
        self.library.bind("DestroyOnlineStream", [c.c_void_p], None)
        self.library.bind("OnlineStreamAcceptWaveform", [c.c_void_p, c.c_int32, c.POINTER(c.c_float), c.c_int32], None)
        self.library.bind("OnlineStreamInputFinished", [c.c_void_p], None)
        self.library.bind("IsOnlineStreamReady", [c.c_void_p, c.c_void_p], c.c_int32)
        self.library.bind("DecodeOnlineStream", [c.c_void_p, c.c_void_p], None)
        self.library.bind("GetOnlineStreamResultAsJson", [c.c_void_p, c.c_void_p], c.c_void_p)
        self.library.bind("DestroyOnlineStreamResultJson", [c.c_void_p], None)
        self.handle = self.lib.SherpaOnnxCreateOnlineRecognizer(c.byref(config))
        if not self.handle:
            self.library.close()
            raise RuntimeError("Sherpa recognizer load failed")

    def transcribe(self, audio, rate, deadline):
        stream = self.lib.SherpaOnnxCreateOnlineStream(self.handle)
        if not stream:
            raise RuntimeError("Sherpa stream creation failed")
        try:
            self.lib.SherpaOnnxOnlineStreamAcceptWaveform(
                stream, rate, audio.ctypes.data_as(c.POINTER(c.c_float)), len(audio)
            )
            self.lib.SherpaOnnxOnlineStreamInputFinished(stream)
            while self.lib.SherpaOnnxIsOnlineStreamReady(self.handle, stream):
                if time.monotonic() > deadline:
                    raise TimeoutError("Sherpa inference budget exhausted")
                self.lib.SherpaOnnxDecodeOnlineStream(self.handle, stream)
            pointer = self.lib.SherpaOnnxGetOnlineStreamResultAsJson(self.handle, stream)
            if not pointer:
                raise RuntimeError("Sherpa returned no result")
            try:
                return json.loads(c.string_at(pointer))["text"].strip()
            finally:
                self.lib.SherpaOnnxDestroyOnlineStreamResultJson(pointer)
        finally:
            self.lib.SherpaOnnxDestroyOnlineStream(stream)

    def close(self):
        self.lib.SherpaOnnxDestroyOnlineRecognizer(self.handle)
        self.library.close()


def run_engine(clips, samples, deadline):
    import numpy as np
    import soundfile as sf

    recognizer: Any = None
    rows = []

    def load():
        nonlocal recognizer
        recognizer = Recognizer()

    timer = BenchmarkLifecycle(
        lambda: f"{os.getpid()}:{recognizer.handle}" if recognizer else "",
        lambda: recognizer.close() if recognizer else None,
    )
    result: dict[str, Any] = {
        "engine": "sherpa-onnx",
        "status": "running",
        "samples": rows,
        "mode": "online model; whole recorded clip, unpaced, 0.66s tail padding",
        "model_sha256": {},
    }
    for part in ("encoder", "decoder", "joiner", "tokens"):
        path = models.path("asr/sherpa-onnx/zipformer-en/" + part)
        with path.open("rb") as source:
            result["model_sha256"][str(path)] = hashlib.file_digest(source, "sha256").hexdigest()
    try:
        with timer:
            timer.prepare(lambda: None, load, reused=True)
            inputs = []
            for clip in clips:
                audio, rate = sf.read(clip["file"], dtype="float32")
                inputs.append((np.ascontiguousarray(np.pad(audio, (0, int(rate * 0.66)))), rate))
            timer.warmup(lambda: recognizer.transcribe(*inputs[0], deadline))
            for repetition in range(samples):
                for index, clip in enumerate(clips):
                    text, timing = timer.measure(lambda: recognizer.transcribe(*inputs[index], deadline))
                    if not text:
                        raise ValueError("Empty Sherpa transcript")
                    rows.append(
                        {
                            **timing,
                            "clip": clip["id"],
                            "text": text,
                            "repetition": repetition,
                            "rtf": timing["request_seconds"] / clip["duration_seconds"],
                            **unicode_errors(clip["reference"], text),
                        }
                    )
            result["status"] = "completed"
    except Exception as error:
        result.update(status="failed", error=str(error))
    result.update(benchmark=timer.record(), summary=summarize_requests(rows))
    return result
