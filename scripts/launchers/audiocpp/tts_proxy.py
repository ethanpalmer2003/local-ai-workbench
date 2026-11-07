"""TTS HTTP relay: shared text preparation, streamed audio or complete response bytes."""

import contextlib
import json
import time
import traceback
import urllib.error
import urllib.request
import uuid
import wave
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPResponse
from io import BytesIO
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlsplit

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp_catalog
from scripts.launchers.proxy_restart import ProxyRestartController
from scripts.launchers.proxy_util import (
    ProxyHandlerMixin,
    RequestScope,
    build_forward_headers,
    forward_upstream_error,
    read_request_body,
    relay_response_headers,
    relay_stream,
    send_bytes,
    send_json_error,
    serve_proxy,
    streamed_speech_response_headers,
)

Payload = dict[str, object]


def _test_asset(path: str) -> tuple[bytes, str] | None:
    ui_root = project_cfg.TESTS_DIR / "ui"
    page = ui_root / "speech.html"
    comparison = ui_root / "audiocpp_comparison.js"
    practice = project_cfg.component("asr/shared").launcher_dir
    assets = {
        "/practice": (page, "text/html; charset=utf-8"),
        "/practice.js": (practice / "practice.js", "text/javascript"),
        "/practice-worklet.js": (practice / "practice-worklet.js", "text/javascript"),
        "/test": (page, "text/html; charset=utf-8"),
        "/test/": (page, "text/html; charset=utf-8"),
        "/test/comparison.js": (comparison, "text/javascript"),
        "/comparison.js": (comparison, "text/javascript"),
        "/tests/ui/audiocpp_comparison.js": (comparison, "text/javascript"),
        "/launchers/audiocpp/pcm_audio.js": (
            project_cfg.component("shared").launcher_dir / "browser/pcm_audio.js",
            "text/javascript",
        ),
        "/launchers/shared/browser/pcm_audio.js": (
            project_cfg.component("shared").launcher_dir / "browser/pcm_audio.js",
            "text/javascript",
        ),
        "/launchers/shared/browser/workspace_lifecycle.js": (
            project_cfg.component("shared").launcher_dir / "browser/workspace_lifecycle.js",
            "text/javascript",
        ),
        "/launchers/shared/browser/speech_tools.js": (
            project_cfg.component("shared").launcher_dir / "browser/speech_tools.js",
            "text/javascript",
        ),
        "/launchers/shared/browser/speech_client.js": (
            project_cfg.component("shared").launcher_dir / "browser/speech_client.js",
            "text/javascript",
        ),
    }
    asset = assets.get(path)
    return (asset[0].read_bytes(), asset[1]) if asset else None


def is_streaming_request(payload: Payload) -> bool:
    """
    - Single definition of "this request wants streamed audio", shared with the
      proxy's transform so the two cannot drift apart
    """
    return payload.get("stream") is True or payload.get("stream_format") in ("audio", "sse")


def _single_line(text: str | None) -> str:
    """
    - Log-friendly single-line form (full text, never truncated)
    """
    return (text or "").replace("\n", " ").strip()


def _log_tts_request(
    tag: str, rid: str, raw_input: str | None, payload: Payload, fallback_from: str | None = None
) -> None:
    instruction = payload.get("instruction")
    voice = payload.get("voice")
    clone_ref = bool(payload.get("voice_ref"))
    transcript_chars = len(str(payload.get("reference_text", "")))
    print(f"[{tag}] [{rid}] Request:")
    print(f"  -> Raw Input: {ascii(_single_line(raw_input))}")
    print(
        "  -> Model: "
        f"{payload.get('model')} | Voice: {voice} (clone={clone_ref}, "
        f"transcript_chars={transcript_chars})"
        + (f" (fallback from {fallback_from!r})" if fallback_from else "")
        + (f" | Instruction: {instruction!r}" if instruction is not None else "")
    )


def _fmt_seconds(v: float) -> str:
    """Seconds with up to 2 decimals, trailing zeros trimmed:
    - absolute 0 -> "0s"
    - tiny value -> "0.03s" (never rounds into a fake "0s")"""
    return f"{v:.2f}".rstrip("0").rstrip(".") + "s"


def _log_tts_response(
    tag: str,
    rid: str,
    spoken_text: str | None,
    generation_time: float,
    transfer: float,
    audio_duration: float,
    total: float,
    transform_ms: float,
    instruction: str | None = None,
    guidance_scale: float | None = None,
) -> None:
    print(f"[{tag}] [{rid}] Response:")
    spoken = f"  -> Spoken: {ascii(_single_line(spoken_text))}"
    if instruction:
        spoken += f" (instruction: {instruction}"
        if guidance_scale is not None:
            spoken += f" gs: {guidance_scale:g}"
        spoken += ")"
    print(spoken)
    line = (
        f"  -> Timing: total={_fmt_seconds(total)} gen={_fmt_seconds(generation_time)}"
        f" transform={_fmt_seconds(transform_ms / 1000)} dur={_fmt_seconds(audio_duration)}"
        + f" transfer={_fmt_seconds(transfer)}"
    )
    print(line)


def _log_tts_skip(tag: str, rid: str, raw_input: str | None) -> None:
    print(f"[{tag}] [{rid}] Skip: {ascii(_single_line(raw_input))}")


def _log_tts_error(tag: str, rid: str, raw_input: str | None, error: Exception) -> None:
    print(f'[{tag}] [{rid}] Error: "{_single_line(raw_input)}" {error}')


def _log_stream_stats(tag: str, rid: str, stats: dict[str, float], model: str | None = None) -> None:
    """
    - rtf = generation time after first audio / audio duration; under 1.0 means
      faster than real time
    - dur assumes 16-bit mono PCM at the configured rate
    """
    rate = audiocpp_catalog.streaming_defaults(cfg.AUDIOCPP_SERVICE, model)["pcm_sample_rate"]
    line = f"[{tag}] [{rid}] Stream: ttfb={_fmt_seconds(stats['ttfb'])} total={_fmt_seconds(stats['total'])}"
    dur = stats["audio_bytes"] / (rate * 2) if isinstance(rate, (int, float)) and rate > 0 else 0.0
    if dur > 0:
        gen = stats["total"] - stats["ttfb"]
        line += f" dur={_fmt_seconds(dur)} rtf={gen / dur:.2f}"
    if stats["disconnected"]:
        line += " (client disconnected)"
    print(line)


def _request_options(payload: Payload) -> tuple[str | None, float | None]:
    """
    - (instruction, guidance_scale) from payload["options"], for the response log
    """
    options = payload.get("options")
    if not isinstance(options, dict):
        return None, None
    return options.get("instruction"), options.get("guidance_scale")


@dataclass
class _Prepared:
    payload: Payload
    body: bytes
    fallback: object
    transform_ms: float
    raw_input: str | None


def _wav_duration(data: bytes) -> float:
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return 0.0
    with wave.open(BytesIO(data), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def run_tts_json_proxy(
    service: cfg.GenericStartupServiceSettings,
    upstream_url: str,
    transform: Callable[[Payload], Payload | None] | None = None,
    tag: str = "audiocpp-proxy",
    restart_controller: ProxyRestartController | None = None,
    request_scope: RequestScope | None = None,
    on_server=None,
    test_page_redirect: str | None = None,
):
    """Relay TTS requests; serialize stateful text preparation, leaving playback to clients."""
    transform_lock = Lock()
    audio_service = service if isinstance(service, cfg.AudiocppStartupRequestServiceSettings) else None

    class TTSProxyHandler(ProxyHandlerMixin):
        protocol_version = "HTTP/1.1"

        def _call_upstream(self, method: str, body: bytes):
            """
            - POST/GET to the upstream server
            - Returns (resp, resp_body, total_time, ttfb)
            - ttfb is time-to-first-byte, i.e. how long the server spent before
              it started responding (generation/model load) versus how long the
              audio transfer took
            """
            req = urllib.request.Request(
                upstream_url + self.path,
                data=body if body else None,
                method=method,
                headers=build_forward_headers(self.headers, body),
            )
            upstream_start = time.perf_counter()
            with urllib.request.urlopen(req) as resp:
                ttfb = time.perf_counter() - upstream_start
                resp_body = resp.read()
            return resp, resp_body, time.perf_counter() - upstream_start, ttfb

        def _send_audio(self, resp: HTTPResponse, resp_body: bytes):
            self.send_response(resp.status)
            relay_response_headers(self, resp.getheaders(), len(resp_body))
            self.end_headers()
            self.wfile.write(resp_body)
            self.wfile.flush()

        # ----------------------------------------------------------
        # Request handling

        def _forward(self, method: str):
            if method == "GET":
                self._forward_get(method)
                return

            if urlsplit(self.path).path != "/v1/audio/speech":
                body = read_request_body(self)
                relay_stream(
                    self, method, upstream_url + self.path, build_forward_headers(self.headers, body), body, tag
                )
                return

            rid = uuid.uuid4().hex[:6]
            raw_input = None
            request_start = time.perf_counter()
            try:
                prepared = self._prepare(rid)
                if prepared is None:
                    return
                raw_input = prepared.raw_input
                fallback = prepared.fallback
                _log_tts_request(
                    tag, rid, raw_input, prepared.payload, fallback_from=str(fallback) if fallback is not None else None
                )
                if is_streaming_request(prepared.payload):
                    self._stream(method, prepared, rid)
                else:
                    self._complete(method, prepared, rid, request_start)
            except audiocpp_catalog.ComparisonSelectionError as error:
                send_json_error(self, 400, str(error), "invalid_comparison_selection")
            except (json.JSONDecodeError, UnicodeDecodeError):
                send_json_error(self, 400, "invalid JSON", "invalid_request")
            except urllib.error.URLError as e:
                _log_tts_error(tag, rid, raw_input, e)
                forward_upstream_error(self, tag, e)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass
            except Exception:
                traceback.print_exc()
                with contextlib.suppress(Exception):
                    send_json_error(self, 500, "proxy error", "proxy_error")

        def _forward_get(self, method: str):
            if test_page_redirect and urlsplit(self.path).path in ("/test", "/test/"):
                self.send_response(307)
                self.send_header("Location", test_page_redirect)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if audio_service is not None and (asset := _test_asset(urlsplit(self.path).path)) is not None:
                send_bytes(self, 200, asset[0], asset[1])
                return
            if self.path == "/proxy/comparison-catalog" and audio_service is not None:
                body = json.dumps(audiocpp_catalog.comparison_catalog()).encode("utf-8")
                send_bytes(self, 200, body, "application/json")
                return
            if urlsplit(self.path).path == "/proxy/config" and audio_service is not None:
                model = parse_qs(urlsplit(self.path).query).get("model", [None])[0]
                body = json.dumps(audiocpp_catalog.runtime_defaults(audio_service, model)).encode("utf-8")
                send_bytes(self, 200, body, "application/json")
                return
            try:
                try:
                    response, body, _, _ = self._call_upstream(method, read_request_body(self))
                    self._send_audio(response, body)
                except urllib.error.URLError as error:
                    forward_upstream_error(self, tag, error)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                print(f"[{tag}] client disconnected mid-response")

        def _prepare(self, rid: str) -> _Prepared | None:
            """
            - Read and transform the request while holding the transform turn
            - Returns None when the transform skipped the request (204 already sent)
            """
            with transform_lock:
                body = read_request_body(self)
                transform_start = time.perf_counter()
                payload: Payload = json.loads(body)
                raw = payload.get("input")
                raw_input = raw if isinstance(raw, str) else None
                fallback = None
                if transform:
                    result = transform(payload)
                    if result is None:
                        send_bytes(self, 204, b"")
                        _log_tts_skip(tag, rid, raw_input)
                        return None
                    payload = result
                    fallback = payload.pop("_voice_fallback", None)
                    body = json.dumps(payload).encode("utf-8")
                transform_ms = (time.perf_counter() - transform_start) * 1000 if transform else 0.0
            return _Prepared(payload, body, fallback, transform_ms, raw_input)

        def _stream(self, method: str, prepared: _Prepared, rid: str):
            # - Once headers are sent, errors must close the stream, not append JSON.
            try:
                stats = relay_stream(
                    self,
                    method,
                    upstream_url + self.path,
                    build_forward_headers(self.headers, prepared.body),
                    prepared.body,
                    tag,
                    response_headers=streamed_speech_response_headers(prepared.payload),
                )
                if stats:
                    _log_stream_stats(tag, rid, stats, str(prepared.payload.get("model") or "") or None)
            except Exception:
                traceback.print_exc()
            finally:
                self.close_connection = True

        def _complete(self, method: str, prepared: _Prepared, rid: str, request_start: float):
            payload = prepared.payload
            resp, resp_body, generation_time, ttfb = self._call_upstream(method, prepared.body)
            audio_duration = _wav_duration(resp_body)
            self._send_audio(resp, resp_body)
            total = time.perf_counter() - request_start
            spoken = payload.get("input")
            instruction, guidance_scale = _request_options(payload)
            _log_tts_response(
                tag,
                rid,
                spoken if isinstance(spoken, str) else None,
                generation_time,
                generation_time - ttfb,
                audio_duration,
                total,
                transform_ms=prepared.transform_ms,
                instruction=instruction,
                guidance_scale=guidance_scale,
            )

        def log_message(self, format: str, *args: Any) -> None:
            pass  # per-request summary is printed in _forward instead

    print(f"[{tag}] service: {service}")
    TTSProxyHandler.restart_controller = restart_controller
    TTSProxyHandler.request_scope = request_scope
    serve_proxy(TTSProxyHandler, service.listen_ip, service.port, upstream_url, tag, on_server)
