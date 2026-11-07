"""Persistent Windows PDH dedicated-memory counter; avoids per-sample PowerShell startup."""

import ctypes
from ctypes import wintypes


class _Value(ctypes.Union):
    _fields_ = [("double", ctypes.c_double), ("large", ctypes.c_longlong), ("pointer", ctypes.c_void_p)]


class _Formatted(ctypes.Structure):
    _fields_ = [("status", wintypes.DWORD), ("value", _Value)]


class _Item(ctypes.Structure):
    _fields_ = [("name", wintypes.LPWSTR), ("formatted", _Formatted)]


class WindowsAdapterCounter:
    def __init__(self):
        self.pdh = ctypes.WinDLL("pdh.dll")
        self.query, self.counter = ctypes.c_void_p(), ctypes.c_void_p()
        signatures = {
            "PdhOpenQueryW": [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)],
            "PdhAddEnglishCounterW": [
                ctypes.c_void_p,
                wintypes.LPCWSTR,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_void_p),
            ],
            "PdhCollectQueryData": [ctypes.c_void_p],
            "PdhGetFormattedCounterArrayW": [
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p,
            ],
            "PdhCloseQuery": [ctypes.c_void_p],
        }
        for name, arguments in signatures.items():
            function = getattr(self.pdh, name)
            function.argtypes, function.restype = arguments, wintypes.DWORD
        self.check(self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)))
        try:
            self.check(
                self.pdh.PdhAddEnglishCounterW(
                    self.query, r"\GPU Adapter Memory(*)\Dedicated Usage", 0, ctypes.byref(self.counter)
                )
            )
            self.check(self.pdh.PdhCollectQueryData(self.query))
        except Exception:
            self.pdh.PdhCloseQuery(self.query)
            raise

    @staticmethod
    def check(status):
        if status:
            raise OSError(f"Windows PDH status 0x{status:08x}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.pdh.PdhCloseQuery(self.query)

    def samples(self):
        self.check(self.pdh.PdhCollectQueryData(self.query))
        size, count = wintypes.DWORD(), wintypes.DWORD()
        status = self.pdh.PdhGetFormattedCounterArrayW(
            self.counter, 0x200, ctypes.byref(size), ctypes.byref(count), None
        )
        if status != 0x800007D2:  # PDH_MORE_DATA, required size probe.
            self.check(status)
        if not size.value:
            raise RuntimeError("Windows GPU dedicated-memory counters unavailable")
        buffer = ctypes.create_string_buffer(size.value)
        self.check(
            self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x200, ctypes.byref(size), ctypes.byref(count), buffer)
        )
        items = ctypes.cast(buffer, ctypes.POINTER(_Item))
        return [
            {
                "Path": "\\GPU Adapter Memory(" + items[i].name + ")\\Dedicated Usage",
                "Value": items[i].formatted.value.double,
            }
            for i in range(count.value)
            if items[i].formatted.status in (0, 1)
        ]
