"""Shared ASR HTTP routes, usable without either chat runtime."""

import json
import os
from dataclasses import replace
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector
from scripts.launchers.asr.shared import languages, practice_models
from scripts.launchers.asr.shared.delivery import tts_plan
from scripts.launchers.asr.shared.streaming import live
from scripts.launchers.audiocpp import audiocpp_catalog, tts_proxy
from scripts.launchers.proxy_util import build_forward_headers, forward_upstream_error, send_bytes, send_json_error


def transcribe(handler, body: bytes, engine: cfg.AsrStartupEngine) -> None:
    try:
        data, content_type = selector.backend(engine).transcribe(
            body, handler.headers.get("Content-Type", ""), build_forward_headers(handler.headers, body)
        )
        send_bytes(handler, 200, data, content_type)
    except (ValueError, TypeError) as error:
        send_json_error(handler, 400, str(error), "invalid_request_error")
    except requests.RequestException as error:
        forward_upstream_error(handler, "asr", error)
    except TimeoutError:
        send_json_error(handler, 504, "ASR request timed out", "backend_timeout")
    except RuntimeError as error:
        send_json_error(handler, 502, str(error), "backend_response_error")


def static_get(
    handler: BaseHTTPRequestHandler,
    path: str,
    engine: cfg.AsrStartupEngine | None,
    chat_runtime: str,
    on_demand: bool = False,
    llm_model: str | None = None,
    chat_ui_url: str | None = None,
    delivery_plan: dict[str, Any] | None = None,
) -> bool:
    if (asset := tts_proxy._test_asset(path)) is not None:
        send_bytes(handler, 200, asset[0], asset[1])
        return True
    if path == "/proxy/config":
        model = parse_qs(urlsplit(handler.path).query).get("model", [None])[0]
        send_bytes(handler, 200, json.dumps(workspace_defaults(model)).encode(), "application/json")
        return True
    if path == "/proxy/comparison-catalog":
        send_bytes(handler, 200, json.dumps(audiocpp_catalog.comparison_catalog()).encode(), "application/json")
        return True
    if path == "/asr/status":
        chat_port = (
            cfg.GEMMA_AUDIO_ASR.port
            if engine == cfg.AsrStartupEngine.GEMMA_AUDIO
            else cfg.LLAMACPP_PRACTICE.internal_port
        )
        status: dict[str, object] = {
            "engine": engine.value if engine is not None else "off",
            "ready": False,
            "chat_runtime": chat_runtime,
            "test_url": "/test/",
            "on_demand": on_demand,
            "llm_model": llm_model or (cfg.GEMMA_AUDIO_ASR.model.name if on_demand else None),
            "chat_ui_url": chat_ui_url or f"http://127.0.0.1:{chat_port}/",
            "automatic_turns": False,
            "delivery": delivery_plan,
            "workspace_pid": os.getpid() if on_demand else None,
            "languages": {},
        }
        if engine is not None:
            status.update(
                ready=on_demand or (selector.backend(engine).ready() if selector.external(engine) else True),
                automatic_turns=live.supported(engine),
                languages=languages.capabilities(engine),
            )
        send_bytes(handler, 200, json.dumps(status).encode(), "application/json")
        return True
    return False


def workspace_defaults(model: str | None = None) -> dict[str, object]:
    """Expose selected weights and the common delivery policy; a named model answers with its own."""

    plan = tts_plan()
    spec = practice_models.tts_spec()
    voice = cfg.TTS_FAMILY_DEFAULT_VOICE.get(str(spec["family"]), cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value)
    selected = model or spec["id"]
    service = replace(cfg.AUDIOCPP_SERVICE, model=selected, voice=voice)
    # - the practice model answers with its own configured spec; another model answers with its config entry
    result = (
        audiocpp_catalog.runtime_defaults(service, specs=[spec])
        if selected == spec["id"]
        else audiocpp_catalog.runtime_defaults(service, model=selected)
    )
    result.update(
        practice_gateway=True,
        practice_url="/practice",
        practice_model=cfg.LANGUAGE_PRACTICE.tts_model,
        models=audiocpp_catalog.configured_models(),
        streaming_enabled=plan["mode"] == "streaming",
        streaming_supported="streaming" in plan["supported"],
        delivery=plan,
        playback_note="",
    )
    return result
