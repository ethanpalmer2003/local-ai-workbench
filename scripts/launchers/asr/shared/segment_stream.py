"""Bounded completed-turn transport for the shared Silero controller.

Offline recognizers keep their models resident. Only decoding waits for speech
end; buffering and endpointing use the same controller as incremental Nemotron.
"""

import io
import json
import queue
import threading
import time
import wave

from scripts.launchers.shared.transport.multipart import audio_upload

_DECODERS = threading.BoundedSemaphore(2)


class SegmentStream:
    def __init__(self, backend, language: str):
        self.backend, self.language = backend, language
        self.pcm = bytearray()
        self.events = queue.Queue()
        self.done = threading.Event()
        self.cancelled = threading.Event()
        self.worker = None

    def start(self):
        pass

    def send(self, frame: bytes):
        if len(self.pcm) + len(frame) > 16000 * 2 * 32:
            raise RuntimeError("ASR turn buffer limit exceeded")
        self.pcm.extend(frame)

    def finish(self):
        if not _DECODERS.acquire(blocking=False):
            raise RuntimeError("Previous ASR requests are still completing; retry shortly")
        def decode():
            started = time.perf_counter()
            try:
                output = io.BytesIO()
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(bytes(self.pcm))
                body, content_type = audio_upload(output.getvalue(), {"language": self.language, "response_format": "json"})
                data, _ = self.backend.transcribe(body, content_type)
                text = json.loads(data).get("text")
                if not isinstance(text, str) or not text.strip():
                    raise RuntimeError("Recognizer returned no transcription text")
                if not self.cancelled.is_set():
                    self.events.put({"type": "transcript.text.done", "text": text.strip(),
                                     "decode_seconds": time.perf_counter() - started})
            except Exception as error:
                if not self.cancelled.is_set():
                    self.events.put({"type": "error", "error": str(error)})
            finally:
                self.done.set()
                _DECODERS.release()

        self.worker = threading.Thread(target=decode, daemon=True)
        self.worker.start()

    def close(self):
        self.cancelled.set()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=1)
