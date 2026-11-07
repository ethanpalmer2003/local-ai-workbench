"""Capability-aware delivery plans; VAD segmentation is not labelled true streaming."""

import json

from scripts.config.shared import speech_delivery
from scripts.launchers.asr.shared import practice_models


def asr_plan(engine):
    return speech_delivery.asr_plan(engine.value)


def tts_plan():
    return practice_models.delivery_plan()


def plans(controls):
    return {
        "asr": asr_plan(controls.engine),
        "llm": speech_delivery.resolve("llm", controls.llm, ["streaming", "whole"]),
        "tts": tts_plan(),
        "overrides": speech_delivery.overrides(),
    }


def route(handler, method, path, controls):
    if path != "/workspace/delivery" or controls is None:
        return False
    from scripts.launchers.proxy_util import read_request_body, send_bytes, send_json_error

    try:
        if method == "POST":
            value = json.loads(read_request_body(handler))
            if not isinstance(value, dict):
                raise ValueError("Delivery selection must be an object")
            kind, model = value.get("stage"), value.get("model")
            rows = controls.catalog().get(kind, []) if kind in ("asr", "llm", "tts") else []
            if not any(row["id"] == model for row in rows):
                raise ValueError("Choose a registered model for the delivery override")
            speech_delivery.save(kind, model, value.get("mode"))
        elif method != "GET":
            raise ValueError("Use GET or POST")
        send_bytes(handler, 200, json.dumps(plans(controls)).encode(), "application/json")
    except (ValueError, TypeError) as error:
        send_json_error(handler, 400, str(error), "invalid_request_error")
    return True
