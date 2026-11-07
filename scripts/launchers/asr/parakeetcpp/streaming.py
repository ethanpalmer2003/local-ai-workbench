"""Explicitly loaded CPU C API; every stream owns and frees its native session."""

import ctypes as c
import re
from pathlib import Path

from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.native_abi.native_library import NativeLibrary


def clean_transcript(text: str) -> str:
    # This conversion emits its final language token as text; preserve raw output separately.
    return re.sub(r"\s*<[a-z]{2,3}(?:-[A-Za-z0-9]+)*>\s*$", "", text).strip()


class Model:
    def __init__(self, library: Path, model: Path):
        require_native_execution("Parakeet CPU streaming C API")
        self.library = NativeLibrary(library, search_dirs=(library.parent,), prefix="parakeet_capi_")
        bind = self.library.bind
        self.load = bind("load", [c.c_char_p], c.c_void_p)
        self.free = bind("free", [c.c_void_p], None)
        self.error = bind("last_error", [c.c_void_p], c.c_char_p)
        self.begin = bind("stream_begin_lang", [c.c_void_p, c.c_char_p], c.c_void_p)
        self.feed = bind("stream_feed", [c.c_void_p, c.POINTER(c.c_float), c.c_int, c.POINTER(c.c_int)], c.c_void_p)
        self.finalize = bind("stream_finalize", [c.c_void_p], c.c_void_p)
        self.free_stream = bind("stream_free", [c.c_void_p], None)
        self.free_string = bind("free_string", [c.c_void_p], None)
        self.context = self.load(str(model).encode())
        if not self.context:
            self.library.close()
            raise RuntimeError("Parakeet CPU model failed to load")

    def text(self, pointer) -> str:
        if not pointer:
            raise RuntimeError((self.error(self.context) or b"Parakeet streaming failure").decode(errors="replace"))
        try:
            return c.string_at(pointer).decode("utf-8")
        finally:
            self.free_string(pointer)

    def stream(self, language: str):
        return Stream(self, language)

    def close(self):
        if self.context:
            self.free(self.context)
            self.context = None
        self.library.close()


class Stream:
    def __init__(self, model: Model, language: str):
        self.model = model
        self.context = model.begin(model.context, language.encode())
        if not self.context:
            raise RuntimeError((model.error(model.context) or b"Cannot begin stream").decode(errors="replace"))

    def push(self, pcm: bytes) -> str:
        import numpy as np

        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        eou = c.c_int()
        return self.model.text(
            self.model.feed(self.context, samples.ctypes.data_as(c.POINTER(c.c_float)), len(samples), c.byref(eou))
        )

    def finish(self) -> str:
        return self.model.text(self.model.finalize(self.context))

    def close(self):
        if self.context:
            self.model.free_stream(self.context)
            self.context = None
