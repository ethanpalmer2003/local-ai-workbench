"""Conservative summaries with independent source claims; absence never proves non-support."""

import json
import re
from pathlib import Path
from typing import Any

LANGUAGE_KEYS = {"language", "languages", "supported_languages", "language_codes", "lang_to_id", "locale"}
NON_LANGUAGES = {"auto", "multilingual", "unknown", "und", "code"}


def language_codes(value, key):
    if key == "lang_to_id" and isinstance(value, dict):
        value = [code.removeprefix("<|").removesuffix("|>") for code in value]
    if isinstance(value, dict):
        value = value.get("code")
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.startswith("[") else value.split(",")
        except ValueError:
            return None
    if not isinstance(value, list) or not all(isinstance(code, str) for code in value):
        return None
    return sorted({code.strip() for code in value if code.strip().lower() not in NON_LANGUAGES}) or None


def claims_from(data, source, scope="model"):
    if not isinstance(data, dict):
        return []
    result = []
    for key, value in data.items():
        leaf = key.lower().split(".")[-1]
        if leaf in LANGUAGE_KEYS:
            codes = language_codes(value, leaf)
            if codes:
                result.append(
                    {
                        "source": source + ":" + key,
                        "scope": scope,
                        "unit": "locale" if any("-" in code or "_" in code for code in codes) else "language",
                        "codes": codes,
                        "count": len(codes),
                        "validated_accuracy": False,
                    }
                )
        if key in ("metadata_props", "language_config", "model") and isinstance(value, dict):
            result += claims_from(value, source + ":" + key, scope)
    return result


def summary(record, language_catalog) -> dict[str, Any]:
    local = record.get("local", {}).get("metadata", {})
    spec = local.get("audiocpp.model_spec.json", "{}")
    try:
        spec = json.loads(spec) if isinstance(spec, str) else {}
    except ValueError:
        spec = {}
    if not isinstance(spec, dict):
        spec = {}
    claims = claims_from(local, "embedded") + claims_from(spec, "embedded:model_spec", "speech runtime")
    curated = [entry for entry in language_catalog["models"] if set(entry["model_ids"]) & set(record["ids"])]
    for entry in curated:
        for field, unit in (("languages", "language"), ("locales", "locale"), ("dialects", "dialect")):
            if entry[field]:
                claims.append(
                    {
                        "source": "reviewed_catalog:" + entry["distribution"],
                        "scope": ",".join(entry["tasks"]),
                        "unit": unit,
                        "codes": entry[field],
                        "count": len(entry[field]),
                        "notes": entry["notes"],
                        "coverage_tiers": entry.get("coverage_tiers"),
                        "validated_accuracy": False,
                    }
                )
    configs = []
    for item in record.get("sidecars", []):
        data = item.get("metadata", {})
        claims += claims_from(
            data, item["path"], "file" if item.get("scope") == "file" else "directory; identity not guaranteed"
        )
        if isinstance(data, dict):
            configs.append((item["path"], data))
    for hub in record.get("hub", []):
        claims += claims_from(hub.get("card", {}), "hub:" + hub.get("repo", ""), "publisher model card")
        for name, data in hub.get("configs", {}).items():
            claims += claims_from(data, "hub:" + hub["repo"] + "/" + name)
            configs.append(("hub:" + hub["repo"] + "/" + name, data))
    claims += claims_from(record.get("native", {}).get("metadata", {}), "native_inspector", "installed runtime")
    fields = {
        key: value
        for key, value in local.items()
        if any(
            word in key.lower()
            for word in (
                "architecture",
                "context_length",
                "block_count",
                "head_count",
                "embedding_length",
                "expert",
                "sliding_window",
                "license",
                "sample_rate",
                "file_type",
                "size_label",
                "parameter_count",
            )
        )
    }
    for source, config in configs:
        for key in (
            "architectures",
            "model_type",
            "max_position_embeddings",
            "hidden_size",
            "num_hidden_layers",
            "num_attention_heads",
            "num_key_value_heads",
            "sliding_window",
            "num_experts",
            "num_experts_per_tok",
            "torch_dtype",
            "dtype",
            "quantization_config",
            "audio",
            "language",
            "num_speakers",
        ):
            if key in config:
                fields[source + ":" + key] = config[key]
    tasks = sorted({task for entry in curated for task in entry["tasks"]} | set(spec.get("tasks", [])))
    if not tasks and any(group in ("llamacpp", "koboldcpp", "strata") for group in record["groups"]):
        tasks = ["llm (registry group; modality support not established)"]
    label = re.search(r"(?:iq|q)\d[^.]*|bf16|f16|fp16|f32", Path(record["path"]).name, re.I)
    templates = [source for source, config in configs if config.get("chat_template")]
    if local.get("tokenizer.chat_template"):
        templates.append("embedded:tokenizer.chat_template")
    language_sets = {
        tuple(sorted(code.lower().replace("_", "-") for code in claim["codes"]))
        for claim in claims
        if claim["unit"] == "language"
    }
    return {
        "tasks": tasks or None,
        "fields": fields,
        "language_claims": claims,
        "language_status": "claims_available"
        if claims
        else "unknown; vocabulary/pretraining scope is not a language-support list",
        "review_flags": ["Language claims differ; compare scopes and incomplete tags, do not union automatically"]
        if len(language_sets) > 1
        else [],
        "chat_template_sources": templates,
        "capabilities": spec.get("capabilities") or None,
        "modes": spec.get("modes") or None,
        "voices": spec.get("ui", {}).get("builtin_voices") or None,
        "quantization_filename_hint": label.group() if label else None,
        "limits": [
            "Claims are not runtime validation; missing fields mean unknown, not unsupported.",
            "Speech language coverage is not inferred from LLM text/pretraining languages or tokenizer vocabulary.",
        ],
    }
