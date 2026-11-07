"""Serve the installed Kobold Lite with optional streaming audio playback."""

import argparse
import difflib
import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector as transcription
from scripts.launchers.asr.shared import http_api, live, practice_models
from scripts.launchers.audiocpp import audiocpp_catalog, tts_text_processing
from scripts.launchers.koboldcpp import external_bridge, kokoro
from scripts.launchers.launch_util import backend_unavailable
from scripts.launchers.proxy_util import (
    ProxyHandlerMixin,
    RequestScope,
    build_forward_headers,
    forward_upstream_error,
    read_request_body,
    relay_stream,
    send_bytes,
    send_json_error,
    serve_proxy,
)


def audio_delivery_plan():
    """The practice gateway's TTS plan and model id; Lite's own TTS cannot stream, so streaming needs the AudioCpp path."""
    external = not kokoro.internal() and (
        cfg.KOBOLDCPP_SERVICE.transcription_engine == cfg.AsrStartupEngine.AUDIOCPP or kokoro.selected())
    plan = practice_models.delivery_plan()
    return plan if external else {**plan, 'mode': 'whole', 'supported': ['whole']}


def _patch_local(html: str) -> tuple[str, str]:
    anchor = "\t\t\t\tfetch(sub_endpt, {"
    hook = """if (is_oai_tts && window.koboldAudioStream) {
                    sub_endpt = window.koboldAudioStream.speechEndpoint(sub_endpt);
                    if (window.koboldAudioStream.enabled()) {
                        if (audioTone !== null) {
                            payload._tone_tag = audioTone;
                        }
                        window.koboldAudioStream.speak(sub_endpt, payload, ttsheaders, do_download, do_embed_tts);
                        return;
                    }
                    payload.stream = false;
                    payload.response_format = 'wav';
                }
                """
    if html.count(anchor) != 1 or "function tts_speak_direct(" not in html:
        raise ValueError("Installed Lite's TTS code changed; streaming patch cannot be applied safely")
    html = html.replace(anchor, hook + anchor, 1)
    tone_anchor = "let narrateonlydialog = localsettings.narrate_only_dialog;"
    if html.count(tone_anchor) != 1:
        raise ValueError("Installed Lite's dialogue filter changed; tone patch cannot be applied safely")
    html = html.replace(
        tone_anchor, tone_anchor + "\n const audioTone = window.koboldAudioStream?.toneInstruction(text) ?? null;", 1
    )
    queue_anchor = "if(streamallowed && localsettings.tts_stream && !is_test)"
    if html.count(queue_anchor) != 1:
        raise ValueError("Installed Lite's speech queue changed; streaming patch cannot be applied safely")
    html = html.replace(
        queue_anchor,
        "if(streamallowed && (ssval === OAI_TTS_ID && window.koboldAudioStream?.enabled() ? window.koboldAudioStream.useTextQueue(localsettings.tts_stream) : localsettings.tts_stream) && !is_test)",
        1,
    )
    abort = "function abort_generation() {"
    if html.count(abort) != 1:
        raise ValueError("Installed Lite's abort handler changed; streaming patch cannot be applied safely")
    html = html.replace(abort, abort + "\n window.koboldAudioStream?.stop();", 1)
    split = 'tts_speak_input_queue = text2.split("\\n").map(chunk => chunk.trim()).filter(chunk => chunk.length > 0);'
    if html.count(split) != 1:
        raise ValueError("Installed Lite's narration splitter changed; streaming patch cannot be applied safely")
    html = html.replace(
        split,
        'tts_speak_input_queue = (ssval === OAI_TTS_ID && window.koboldAudioStream?.enabled()) ? window.koboldAudioStream.chunkText(text) : text2.split("\\n").map(chunk => chunk.trim()).filter(chunk => chunk.length > 0);',
        1,
    )
    plan = audio_delivery_plan()
    settings = json.dumps(
        {
            **audiocpp_catalog.streaming_defaults(cfg.AUDIOCPP_SERVICE),
            "streaming_enabled": plan['mode'] == 'streaming',
            "audioProxyPort": cfg.AUDIOCPP_SERVICE.port,
            "tone_tags_supported": not kokoro.selected()
            and cfg.AUDIOCPP_SERVICE.model in cfg.BREEZE_MODELS
            and tts_text_processing.BREEZE_TONES.tags_enabled,
        }
    )
    return html, f"<script>window.koboldAudioSettings={settings};</script>"


def _replace_once(html: str, old: str, new: str) -> str:
    if html.count(old) != 1:
        raise ValueError(f"Installed Lite changed; expected one occurrence of {old!r}")
    return html.replace(old, new, 1)


def _patch_pr(html: str) -> str:
    for old, new in (
        ("tts_stream: false,", "tts_stream: false,\n        tts_stream_audio: false,"),
        (
            'document.getElementById("tts_stream").checked = localsettings.tts_stream;',
            'document.getElementById("tts_stream").checked = localsettings.tts_stream;\n        document.getElementById("tts_stream_audio").checked = localsettings.tts_stream_audio;',
        ),
        (
            'localsettings.tts_stream = (document.getElementById("tts_stream").checked?true:false);',
            'localsettings.tts_stream = (document.getElementById("tts_stream").checked?true:false);\n        localsettings.tts_stream_audio = document.getElementById("tts_stream_audio").checked;',
        ),
    ):
        html = _replace_once(html, old, new)
    checkbox = (
        '<input title="Narration Streaming" type="checkbox" id="tts_stream">\n\t\t\t\t\t\t\t</div>\n\t\t\t\t\t\t</div>'
    )
    row = """
                        <div class="settinglabel" id="streamaudiodiv">
                            <div class="justifyleft" title="Play PCM/WAV or SSE speech while receiving it. Compressed audio waits for completion. OpenAI-compatible TTS only.">Stream audio</div>
                            <div class="push-right">
                                <input title="Stream Audio" type="checkbox" id="tts_stream_audio" onchange="window.koboldAudioPlayback?.stop()">
                            </div>
                        </div>"""
    html = _replace_once(html, checkbox, checkbox + row)
    selected = 'const selectedTTS = document.getElementById("ttsselect").value;'
    html = _replace_once(
        html,
        selected,
        selected
        + "\n document.getElementById('streamaudiodiv').classList.toggle('hidden', selectedTTS != OAI_TTS_ID);",
    )
    anchor = "\t\t\t\tfetch(sub_endpt, {"
    hook = """if (is_oai_tts && (is_test ? document.getElementById('tts_stream_audio').checked : localsettings.tts_stream_audio)) {
                    window.koboldAudioPlayback.speak(sub_endpt, payload, ttsheaders, do_download, do_embed_tts);
                    return;
                }
                """
    return _replace_once(html, anchor, hook + anchor)


def streaming_assets(variant: str) -> tuple[Path, ...]:
    folder = Path(__file__).parent
    shared = (folder.parent / "shared" / "browser" / "pcm_audio.js", folder / "kobold_audio.js")
    return shared + (folder / "kobold_streaming.js",) if variant == "local" else shared


def external_script(endpoint: str, model: str) -> str:
    """Point Lite's OpenAI-compatible provider at our own llama.cpp server on first load."""
    values = {
        "custom_oai_endpoint": endpoint,
        "custom_oai_key": "noop",
        "custom_oai_model": model,
    }
    assignments = "".join(
        f"localStorage.setItem('kaihordewebui_{key}',{json.dumps(value)});" for key, value in values.items()
    )
    return f"<script>try{{{assignments}}}catch(e){{}}</script>"


def patch_lite(html: str, variant: str = "local", external: tuple[str, str] | None = None) -> str:
    if variant not in ("local", "pr"):
        raise ValueError(f"Unknown Lite streaming variant: {variant}")
    if variant == "local":
        html, settings_script = _patch_local(html)
    else:
        html, settings_script = _patch_pr(html), ""
        anchor = "function abort_generation() {"
        html = _replace_once(html, anchor, anchor + "\n window.koboldAudioPlayback?.stop();")
    restart = "function restart_new_game(save = true, keep_memory = false) {"
    html = _replace_once(html, restart, restart + "\n window.koboldAudioPlayback?.stop();")
    scripts = settings_script + "".join(f'<script src="{asset.name}"></script>' for asset in streaming_assets(variant))
    if external is not None:
        scripts = external_script(*external) + scripts
    return _replace_once(html, "</body>", scripts + "</body>")


def _file_diff(original: str, patched: str, source: str, target: str) -> str:
    lines = difflib.unified_diff(original.splitlines(True), patched.splitlines(True), fromfile=source, tofile=target)
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


def export_diff(original: str, variant: str) -> str:
    diff = _file_diff(original, patch_lite(original, variant), "a/index.html", "b/index.html")
    for asset in streaming_assets(variant):
        diff += _file_diff("", asset.read_text(encoding="utf-8"), "/dev/null", f"b/{asset.name}")
    return diff


def preview_html(original: str, variant: str) -> str:
    html = patch_lite(original, variant)
    for asset in streaming_assets(variant):
        code = asset.read_text(encoding="utf-8").replace("</script", "<\\/script")
        html = html.replace(f'<script src="{asset.name}"></script>', f"<script>{code}</script>")
    show = (
        "document.getElementById('kas-panel').hidden = false;"
        if variant == "local"
        else """
        display_settings(); display_settings_tab(3);
        document.getElementById('ttsselect').value = OAI_TTS_ID; toggle_tts_mode();
        document.getElementById('streamaudiodiv').scrollIntoView({block: 'center'});
    """
    )
    return html.replace(
        "</body>",
        f"""<script>
        window.addEventListener('load', () => {{
            document.title = 'Lite streaming preview - {variant}';
            {show}
        }});
    </script></body>""",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech-engine", choices=[engine.value for engine in cfg.KoboldcppSpeechStartupEngine])
    parser.add_argument("--transcription-engine", choices=[engine.value for engine in cfg.AsrStartupEngine])
    parser.add_argument("--export-diff", type=Path, help="export a standalone Lite patch against the installed UI")
    parser.add_argument(
        "--export-html", type=Path, help="export a self-contained UI preview with its streaming controls open"
    )
    parser.add_argument("--source-file", type=Path, help="use a saved unmodified Lite page when exporting")
    parser.add_argument(
        "--variant", choices=("local", "pr"), default="local", help="detailed local panel or single-toggle PR"
    )
    parser.add_argument("--external-endpoint", help="OpenAI-compatible base URL the page should point at")
    parser.add_argument("--external-model", help="model name the page should request from that endpoint")
    args = parser.parse_args()
    if args.speech_engine:
        cfg.KOBOLDCPP_SERVICE.speech_engine = cfg.KoboldcppSpeechStartupEngine(args.speech_engine)
    if args.transcription_engine:
        cfg.KOBOLDCPP_SERVICE.transcription_engine = cfg.AsrStartupEngine(args.transcription_engine)
    upstream = f"http://127.0.0.1:{cfg.KOBOLDCPP_KCPPS_ARGS['port']}"
    if args.export_diff or args.export_html:
        if args.source_file:
            original = args.source_file.read_text(encoding="utf-8")
        else:
            with urllib.request.urlopen(upstream, timeout=10) as response:
                original = response.read().decode("utf-8")
        for target, content in (
            (args.export_diff, export_diff(original, args.variant) if args.export_diff else None),
            (args.export_html, preview_html(original, args.variant) if args.export_html else None),
        ):
            if target and content is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")
                print(target)
        return

    run_proxy(
        args.variant,
        external=(args.external_endpoint, args.external_model)
        if args.external_endpoint and args.external_model
        else None,
    )


def run_proxy(
    variant: str = "local",
    request_scope: RequestScope | None = None,
    on_server=None,
    external: tuple[str, str] | None = None,
) -> None:
    upstream = f"http://127.0.0.1:{cfg.KOBOLDCPP_KCPPS_ARGS['port']}"
    assets = {"/" + asset.name: asset for asset in streaming_assets(variant)}

    sessions = live.Sessions(cfg.KOBOLDCPP_SERVICE.transcription_engine)

    class Handler(ProxyHandlerMixin):
        protocol_version = "HTTP/1.1"

        def _forward(self, method: str) -> None:
            path = urlsplit(self.path).path
            if sessions.route(self, method, path, cfg.KOBOLDCPP_SERVICE.transcription_engine):
                return
            if method == "GET" and http_api.static_get(
                self, path, cfg.KOBOLDCPP_SERVICE.transcription_engine, "KoboldCpp"
            ):
                return
            if method == "GET" and path == "/health":
                send_bytes(self, 200, b'{"status":"ok","service":"kobold-lite-streaming"}', "application/json")
            elif method == "GET" and path in assets:
                send_bytes(self, 200, assets[path].read_bytes(), "text/javascript")
            elif (
                method == "GET"
                and path == "/api/extra/version"
                and transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine)
            ):
                request = urllib.request.Request(upstream + self.path, headers=build_forward_headers(self.headers, b""))
                try:
                    with urllib.request.urlopen(request, timeout=10) as response:
                        capabilities = json.load(response)
                    capabilities["transcribe"] = transcription.backend(
                        cfg.KOBOLDCPP_SERVICE.transcription_engine
                    ).ready()
                    send_bytes(self, 200, json.dumps(capabilities).encode(), "application/json")
                except urllib.error.URLError as error:
                    forward_upstream_error(self, "kobold-lite", error)
            elif method == "GET" and path == "/":
                try:
                    with urllib.request.urlopen(upstream + self.path, timeout=10) as response:
                        html = response.read().decode("utf-8")
                    send_bytes(self, 200, patch_lite(html, variant, external).encode(), "text/html; charset=utf-8")
                except (urllib.error.URLError, ConnectionRefusedError, TimeoutError) as error:
                    if not backend_unavailable(error):
                        raise
                    send_bytes(self, 503, b"KoboldCpp is not ready yet", "text/plain; charset=utf-8")
            else:
                body = read_request_body(self)
                if method == "POST" and external is not None and path in external_bridge.GENERATE_PATHS:
                    # - the embedded page posts here even with an OpenAI provider configured
                    external_bridge.respond(self, external[0], path, body)
                    return
                target = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}" if path == "/v1/audio/speech" else upstream
                if (
                    method == "POST"
                    and path in ("/api/extra/transcribe", "/v1/audio/transcriptions")
                    and transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine)
                ):
                    http_api.transcribe(self, body, cfg.KOBOLDCPP_SERVICE.transcription_engine)
                    return
                if path == "/v1/audio/speech" and cfg.KOBOLDCPP_SERVICE.transcription_engine == cfg.AsrStartupEngine.AUDIOCPP:
                    from scripts.launchers.audiocpp import asr

                    target = asr.url()
                    try:
                        body = kokoro.speech_body(body)
                    except (ValueError, TypeError) as error:
                        send_json_error(self, 400, str(error), "invalid_request_error")
                        return
                elif path == "/v1/audio/speech" and kokoro.selected():
                    target = upstream if kokoro.internal() else f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}"
                    try:
                        body = kokoro.speech_body(body)
                    except (ValueError, TypeError) as error:
                        send_json_error(self, 400, str(error), "invalid_request_error")
                        return
                relay_stream(
                    self, method, target + self.path, build_forward_headers(self.headers, body), body, "kobold-lite"
                )

    Handler.request_scope = request_scope
    try:
        serve_proxy(
            Handler,
            cfg.KOBOLDCPP_SERVICE.streaming_ui_host,
            cfg.KOBOLDCPP_SERVICE.streaming_ui_port,
            upstream,
            "kobold-lite",
            on_server,
        )
    finally:
        sessions.close()


if __name__ == "__main__":
    main()
