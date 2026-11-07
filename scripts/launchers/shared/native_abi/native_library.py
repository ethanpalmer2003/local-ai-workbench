"""Owned native-library search paths and typed symbol binding; loading is explicit."""

import ctypes
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any


class NativeLibrary:
    def __init__(self, path: Path, *, search_dirs: tuple[Path, ...] = (), prefix: str = "") -> None:
        self.resources = ExitStack()
        self.prefix = prefix
        try:
            for directory in search_dirs:
                self.resources.enter_context(os.add_dll_directory(str(directory)))
            self.dll = ctypes.CDLL(str(path))
        except BaseException:
            self.close()
            raise

    def bind(self, name: str, arguments: list[Any], result: Any) -> Any:
        try:
            function = getattr(self.dll, self.prefix + name)
            function.argtypes, function.restype = arguments, result
            return function
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self.resources.close()
