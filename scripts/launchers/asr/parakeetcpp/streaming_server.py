"""Task-owned CPU streaming HTTP adapter over the pinned Parakeet C API."""

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from scripts.config import models as model_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import requests
from scripts.launchers.asr.parakeetcpp.streaming import Model, clean_transcript
from scripts.launchers.shared.media.audio import decode_audio, mono_resample
from scripts.launchers.shared.transport.http_input import chunks
from scripts.launchers.proxy_util import ExclusiveThreadingHTTPServer, send_bytes, read_request_body


def serve(port: int):
    os.environ["PARAKEET_DEVICE"] = "cpu"
    model = Model(cfg.PARAKEETCPP_STREAM_LIBRARY, model_cfg.path("asr/parakeetcpp/nemotron-3.5-streaming-q8_0"))
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            send_bytes(self, 200 if self.path == "/health" else 404, b'{"backend":"cpu","threads":8}', "application/json")

        def do_POST(self):
            self.connection.settimeout(20)
            self.close_connection = True
            if not lock.acquire(blocking=False):
                send_bytes(self, 429, b'{"error":"An ASR stream is active"}', "application/json")
                return
            stream, live, begun = None, urlsplit(self.path).path.endswith("/live"), False
            try:
                query = parse_qs(urlsplit(self.path).query)
                if live:
                    if query.get("sample_rate", ["16000"])[0] != "16000":
                        raise ValueError("Expected 16 kHz PCM16")
                    stream = model.stream(query.get("language", ["auto"])[0])
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    begun = True
                    inputs = chunks(self)
                else:
                    if urlsplit(self.path).path != "/v1/audio/transcriptions":
                        raise ValueError("Unknown ASR endpoint")
                    if not 0 < int(self.headers.get("Content-Length", "0")) <= 4000000:
                        raise ValueError("WAV upload limit exceeded")
                    request = requests.parse(read_request_body(self), self.headers.get("Content-Type", ""))
                    audio, rate = decode_audio(request.audio)
                    pcm = (mono_resample(audio, rate).clip(-1, 1) * 32767).astype("<i2").tobytes()
                    if not pcm or len(pcm) > 16000 * 2 * 32:
                        raise ValueError("ASR audio limit exceeded")
                    stream = model.stream(request.language)
                    inputs = (pcm[offset:offset + 4096] for offset in range(0, len(pcm), 4096))
                text = ""
                for frame in inputs:
                    delta = stream.push(frame)
                    text += delta
                    if live and delta:
                        self.event({"type": "transcript.text.delta", "delta": delta})
                text += stream.finish()
                if live:
                    self.event({"type": "transcript.text.done", "text": clean_transcript(text), "raw_text": text})
                else:
                    send_bytes(self, 200, json.dumps({"text": clean_transcript(text), "raw_text": text}).encode(), "application/json")
            except (ValueError, RuntimeError, OSError) as error:
                if begun:
                    self.event({"type": "error", "error": str(error)})
                else:
                    send_bytes(self, 400, json.dumps({"error": str(error)}).encode(), "application/json")
            finally:
                if stream:
                    stream.close()
                lock.release()

        def event(self, value):
            self.wfile.write(b"data: " + json.dumps(value).encode() + b"\n\n")
            self.wfile.flush()

    try:
        with ExclusiveThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
            server.serve_forever()
    finally:
        model.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    serve(parser.parse_args().port)
