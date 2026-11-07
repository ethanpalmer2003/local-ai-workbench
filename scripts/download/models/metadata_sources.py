"""Optional public Hub metadata and allow-listed native inspection commands."""

import json
import subprocess
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from scripts.config import project_config as project_cfg
from scripts.download.models.sources import parse_url
from scripts.launchers.runtime.execution_context import require_native_execution

LIMIT = 8 * 1024 * 1024


def hub_source(url):
    try:
        return parse_url(url) if url else None
    except ValueError:
        return None


def hub_metadata(source):
    from huggingface_hub import HfApi

    info = HfApi(token=False).model_info(source.repo_id, revision=source.revision)
    result: dict[str, Any] = {
        "repo": source.repo_id,
        "requested_revision": source.revision,
        "resolved_revision": info.sha,
        "card": info.card_data.to_dict() if info.card_data else {},
        "pipeline_tag": info.pipeline_tag,
        "tags": info.tags,
        "configs": {},
        "errors": [],
    }
    files = {item.rfilename for item in info.siblings or []}
    parent = source.filename.rsplit("/", 1)[0] + "/" if "/" in source.filename else ""
    for name in ("config.json", "generation_config.json", "tokenizer_config.json", "processor_config.json"):
        relative = parent + name if parent + name in files else name
        if relative not in files:
            continue
        url = f"https://huggingface.co/{source.repo_id}/resolve/{quote(info.sha or source.revision, safe='')}/{quote(relative)}"
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                data = response.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise ValueError("Config exceeds 8 MiB metadata limit")
            result["configs"][relative] = json.loads(data)
        except (OSError, ValueError) as error:
            result["errors"].append({"file": relative, "error": str(error)})
    return result


def native_metadata(path, groups):
    if "silero" in path.name.lower() or path.name == "Kokoro_no_espeak_Q4.gguf":
        return {
            "status": "not_available",
            "reason": "No verified inspector for this auxiliary or Kobold-specific format",
        }
    command = None
    if any(group in ("audiocpp", "asr/audiocpp") for group in groups) and path.suffix == ".gguf":
        command = [
            str(project_cfg.AUDIOCPP_SERVER_EXE.with_name("audiocpp_cli.exe")),
            "--model",
            str(path),
            "--inspect",
        ]
    for group, relative, args in (
        ("asr/speechcpp", "vulkan/speech.exe", ["info", str(path), "--json"]),
        ("asr/nemo-speechcpp", "vulkan/bin/nemo-speech.exe", ["model", "info", str(path)]),
        ("asr/parakeetcpp", "cpu/parakeet-cli.exe", ["info", str(path)]),
    ):
        if group in groups and path.suffix == ".gguf":
            command = [str(project_cfg.component(group).framework_dir / relative), *args]
    if command is None:
        return {"status": "not_available", "reason": "No verified metadata-only native inspector for this file/runtime"}
    context = require_native_execution("Model metadata inspector")
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    output = result.stdout[:524288]
    parsed = {}
    try:
        parsed = json.loads(output)
    except ValueError:
        parsed = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return {
        "status": "ok" if result.returncode == 0 else "error",
        "command": command,
        "returncode": result.returncode,
        "metadata": parsed,
        "stdout": output,
        "stderr": result.stderr[:32768],
        "truncated": len(result.stdout) > len(output),
        "execution_context": context,
    }
