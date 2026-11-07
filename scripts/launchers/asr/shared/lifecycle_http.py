"""Allowlisted workspace lifecycle routes; no arbitrary commands, hosts or paths."""

import json

from scripts.launchers.proxy_util import read_request_body, send_bytes, send_json_error


def route(handler, method, path, runtime, sessions):
    if path not in ("/workspace/lifecycle", "/practice/models"):
        return False
    try:
        if method == "GET":
            value = runtime.snapshot() if path == "/workspace/lifecycle" else runtime.controls.catalog()
        elif method == "POST":
            if int(handler.headers.get("Content-Length", "0")) > 4096:
                raise ValueError("Lifecycle payload exceeds 4096 bytes")
            body = json.loads(read_request_body(handler))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            value = change(path, body, runtime, sessions)
        else:
            send_json_error(handler, 405, "Use GET or POST", "invalid_request_error")
            return True
        send_bytes(handler, 200, json.dumps(value).encode(), "application/json")
    except (ValueError, TypeError) as error:
        send_json_error(handler, 400, str(error), "invalid_request_error")
    except (RuntimeError, OSError, TimeoutError) as error:
        send_json_error(handler, 409, str(error), "lifecycle_error")
    return True


def change(path, body, runtime, sessions):
    if path == "/practice/models":
        value = runtime.select(body, lambda: sessions.reset(runtime.controls.engine))
        sessions.engine = runtime.controls.engine
        return value
    stage, action = body.get("stage"), body.get("action")
    if stage not in ("asr", "tts", "llm", "all") or action not in ("load", "unload"):
        raise ValueError("Choose an ASR/LLM/TTS stage and load/unload action")
    stages = ("asr", "tts", "llm") if stage == "all" else (stage,)
    if action == "unload" and stage in ("asr", "all"):
        sessions.reset(runtime.controls.engine)
    for selected in stages:
        if action == "load":
            runtime.load(selected)
        else:
            runtime.lifecycle.release(selected)
    return runtime.snapshot()
