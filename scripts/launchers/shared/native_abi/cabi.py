"""Construct selected plain ctypes structures from an installed C API header."""

import ctypes as c
import re
from collections.abc import Callable
from typing import Any


def structures(header: str, include: Callable[[str], bool]) -> dict[str, Any]:
    header = re.sub(r"/\*.*?\*/", "", header, flags=re.S)
    types: dict[str, Any] = {
        "const char *": c.c_char_p,
        "int32_t": c.c_int32,
        "float": c.c_float,
        "const float *": c.POINTER(c.c_float),
    }
    for name, body in re.findall(r"typedef struct (\w+)\s*\{(.*?)\}", header, re.S):
        if not include(name):
            continue
        fields = []
        for field in body.split(";"):
            field = field.strip()
            if not field:
                continue
            match = re.fullmatch(r"(.+?\*?)\s*(\w+)", field)
            if not match or match[1].strip() not in types:
                raise ValueError(f"Unsupported installed C ABI: {name}: {field}")
            fields.append((match[2], types[match[1].strip()]))
        types[name] = type(name, (c.Structure,), {"_fields_": fields})
    return types
