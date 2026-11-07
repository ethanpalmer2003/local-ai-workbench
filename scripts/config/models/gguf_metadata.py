"""Read scalar/string GGUF metadata without loading model tensors; arrays are skipped."""

import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO

GGUF_MAGIC = b"GGUF"
SCALAR_FMT = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
TYPE_STRING = 8
TYPE_ARRAY = 9


def _read_str(f: BinaryIO) -> str:
    (n,) = struct.unpack("<Q", f.read(8))
    if n > 64 * 1024 * 1024:
        raise ValueError("GGUF metadata string exceeds safety limit")
    value = f.read(n)
    if len(value) != n:
        raise ValueError("Truncated GGUF metadata string")
    return value.decode("utf-8", errors="replace")


def _skip_value(f: BinaryIO, vtype: int) -> None:
    if vtype in SCALAR_FMT:
        f.read(struct.calcsize(SCALAR_FMT[vtype]))
    elif vtype == TYPE_STRING:
        (length,) = struct.unpack("<Q", f.read(8))
        f.seek(length, 1)
    elif vtype == TYPE_ARRAY:
        elem_type, count = struct.unpack("<IQ", f.read(12))
        if elem_type in SCALAR_FMT:
            f.seek(struct.calcsize(SCALAR_FMT[elem_type]) * count, 1)
        else:
            for _ in range(count):
                _skip_value(f, elem_type)
    else:
        raise ValueError(f"unknown gguf metadata type {vtype}")


def read_metadata(path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    with open(path, "rb") as f:
        if f.read(4) != GGUF_MAGIC:
            raise ValueError("not a GGUF file")
        version, _tensors, kv_count = struct.unpack("<IQQ", f.read(20))
        if version < 2:
            raise ValueError(f"gguf v{version} not supported")
        for _ in range(kv_count):
            key = _read_str(f)
            (vtype,) = struct.unpack("<I", f.read(4))
            if vtype in SCALAR_FMT:
                (value,) = struct.unpack(SCALAR_FMT[vtype], f.read(struct.calcsize(SCALAR_FMT[vtype])))
                meta[key] = value
            elif vtype == TYPE_STRING:
                meta[key] = _read_str(f)
            else:
                _skip_value(f, vtype)
    return meta


def _value(f: BinaryIO, kind: int, array_limit: int | None):
    if kind in SCALAR_FMT:
        return struct.unpack(SCALAR_FMT[kind], f.read(struct.calcsize(SCALAR_FMT[kind])))[0]
    if kind == TYPE_STRING:
        return _read_str(f)
    if kind != TYPE_ARRAY:
        raise ValueError(f"Unknown GGUF metadata type {kind}")
    element, count = struct.unpack("<IQ", f.read(12))
    if count > 10000000 and (element not in SCALAR_FMT or array_limit is None):
        raise ValueError("GGUF metadata array exceeds inspection limit")
    retained = count if array_limit is None else min(count, array_limit)
    values = [_value(f, element, array_limit) for _ in range(retained)]
    if retained == count:
        return values
    if element in SCALAR_FMT:
        f.seek(struct.calcsize(SCALAR_FMT[element]) * (count - retained), 1)
    else:
        for _ in range(count - retained):
            _skip_value(f, element)
    return {"count": count, "element_type": element, "preview": values, "omitted": count - retained}


def inspect_metadata(path: Path, *, array_limit: int | None = 128, tensor_index: bool = False,
                     full_array_keys: frozenset[str] = frozenset()) -> dict[str, Any]:
    """All header keys and tensor statistics; seek over payloads, never instantiate weights."""
    metadata, tensors, dtypes = {}, [], Counter()
    elements = 0
    with path.open("rb") as stream:
        if stream.read(4) != GGUF_MAGIC:
            raise ValueError("Not GGUF")
        version, tensor_count, metadata_count = struct.unpack("<IQQ", stream.read(20))
        if version not in (2, 3) or max(tensor_count, metadata_count) > 1000000:
            raise ValueError("Unsupported GGUF header/version")
        for _ in range(metadata_count):
            key = _read_str(stream)
            kind = struct.unpack("<I", stream.read(4))[0]
            metadata[key] = _value(stream, kind, None if key in full_array_keys else array_limit)
        for _ in range(tensor_count):
            name = _read_str(stream)
            dimensions = struct.unpack("<I", stream.read(4))[0]
            if not 1 <= dimensions <= 8:
                raise ValueError("Invalid GGUF tensor rank")
            shape = struct.unpack("<" + "Q" * dimensions, stream.read(8 * dimensions))
            dtype, offset = struct.unpack("<IQ", stream.read(12))
            elements += math.prod(shape)
            dtypes[str(dtype)] += 1
            if tensor_index:
                tensors.append({"name": name, "shape": shape, "ggml_type": dtype, "offset": offset})
    return {"format": "gguf", "version": version, "metadata": metadata,
            "tensor_summary": {"count": tensor_count, "stored_elements": elements, "ggml_type_counts": dict(dtypes)},
            "tensor_index": tensors if tensor_index else None,
            "limits": ["Large arrays are previews unless --full-arrays; stored elements are not active/trained parameter counts."]}
