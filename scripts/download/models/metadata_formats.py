"""Bounded format/sidecar inspection; no tensor payloads, pickle execution or inference."""

import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.config.models.gguf_metadata import inspect_metadata

JSON_LIMIT = 8 * 1024 * 1024


def json_file(path: Path):
    if path.stat().st_size > JSON_LIMIT:
        return {"omitted": "JSON exceeds 8 MiB metadata limit", "bytes": path.stat().st_size}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def safetensors(path: Path, tensor_index=False):
    with path.open("rb") as source:
        length = struct.unpack("<Q", source.read(8))[0]
        if length > 64 * 1024 * 1024 or length + 8 > path.stat().st_size:
            raise ValueError("Invalid/oversized safetensors header")
        header = json.loads(source.read(length))
    tensors = {key: value for key, value in header.items() if key != "__metadata__"}
    types = Counter(value["dtype"] for value in tensors.values())
    elements = sum(math.prod(value["shape"]) for value in tensors.values())
    return {
        "format": "safetensors",
        "metadata": header.get("__metadata__", {}),
        "tensor_summary": {"count": len(tensors), "stored_elements": elements, "dtype_counts": dict(types)},
        "tensor_index": tensors if tensor_index else None,
    }


def varint(source):
    value = 0
    for shift in range(0, 70, 7):
        byte = source.read(1)
        if not byte:
            raise ValueError("Truncated protobuf varint")
        value |= (byte[0] & 127) << shift
        if byte[0] < 128:
            return value
    raise ValueError("Invalid protobuf varint")


def fields(source, end):
    while source.tell() < end:
        key = varint(source)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("Invalid protobuf field")
        if wire == 0:
            yield number, wire, varint(source), source.tell()
            continue
        if wire == 2:
            length = varint(source)
        elif wire in (1, 5):
            length = 8 if wire == 1 else 4
        else:
            raise ValueError("Unsupported protobuf wire type")
        stop = source.tell() + length
        if stop > end:
            raise ValueError("Truncated protobuf field")
        yield number, wire, length, stop
        source.seek(stop)


def text(source, size):
    if size > JSON_LIMIT:
        return {"omitted_bytes": size}
    return source.read(size).decode("utf-8", errors="replace")


def onnx_pair(source, end):
    result = {}
    for number, wire, size, _ in fields(source, end):
        if wire == 2 and number in (1, 2):
            result[str(number)] = text(source, size)
        elif wire == 0 and number == 2:
            result[str(number)] = size
    return result


def onnx_graph(source, end):
    result: dict[str, Any] = {"nodes": 0, "initializers": 0, "inputs": [], "outputs": []}
    for number, wire, size, stop in fields(source, end):
        if number in (1, 5):
            key = "nodes" if number == 1 else "initializers"
            result[key] += 1
        elif number == 2 and wire == 2:
            result["name"] = text(source, size)
        elif number in (11, 12) and wire == 2:
            entry = onnx_pair(source, stop)
            result["inputs" if number == 11 else "outputs"].append({"name": entry.get("1")})
    return result


def onnx(path: Path):
    metadata: dict[str, Any] = {"metadata_props": {}, "opsets": []}
    scalar = {1: "ir_version", 5: "model_version"}
    strings = {2: "producer_name", 3: "producer_version", 4: "domain", 6: "doc_string"}
    with path.open("rb") as source:
        for number, wire, value, stop in fields(source, path.stat().st_size):
            if number in scalar and wire == 0:
                metadata[scalar[number]] = value
            elif number in strings and wire == 2:
                metadata[strings[number]] = text(source, value)
            elif number == 7 and wire == 2:
                metadata["graph"] = onnx_graph(source, stop)
            elif number == 14 and wire == 2:
                pair = onnx_pair(source, stop)
                if isinstance(pair.get("1"), str):
                    metadata["metadata_props"][pair["1"]] = pair.get("2")
            elif number == 8 and wire == 2:
                metadata["opsets"].append(onnx_pair(source, stop))
    return {
        "format": "onnx",
        "metadata": metadata,
        "limits": ["Graph payloads/initializers skipped; input/output names retained, not inferred execution shapes."],
    }


def inspect(path: Path, *, full_arrays=False, tensor_index=False) -> dict[str, Any]:
    with path.open("rb") as source:
        magic = source.read(4)
    if magic == b"GGUF":
        return inspect_metadata(path, array_limit=None if full_arrays else 128, tensor_index=tensor_index)
    if path.suffix.lower() == ".safetensors":
        return safetensors(path, tensor_index)
    if path.suffix.lower() == ".onnx":
        return onnx(path)
    if magic in (b"lmgg", b"ggml"):
        with path.open("rb") as source:
            source.seek(4)
            values = struct.unpack("<11i", source.read(44))
        keys = [
            "vocabulary",
            "audio_context",
            "audio_width",
            "audio_heads",
            "audio_layers",
            "text_context",
            "text_width",
            "text_heads",
            "text_layers",
            "mel_bins",
            "file_type",
        ]
        return {
            "format": "ggml",
            "metadata": dict(zip(keys, values)),
            "limits": ["Legacy GGML header; no inferred language list."],
        }
    return {
        "format": path.suffix.lower().lstrip("."),
        "metadata": {},
        "limits": [
            "Opaque/unrecognized format; pickle and model code are never executed. Use trusted sidecars/source metadata."
        ],
    }


def sidecars(path: Path):
    names = [
        path.name + ".json",
        path.stem + ".json",
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "processor_config.json",
        "preprocessor_config.json",
        "model_index.json",
    ]
    result = []
    for name in dict.fromkeys(names):
        candidate = path.parent / name
        if candidate.is_file():
            try:
                data = json_file(candidate)
                result.append(
                    {
                        "path": str(candidate),
                        "scope": "file" if name.startswith(path.stem) else "directory",
                        "mtime_ns": candidate.stat().st_mtime_ns,
                        "metadata": data,
                    }
                )
            except (OSError, ValueError) as error:
                result.append({"path": str(candidate), "error": str(error)})
    return result
