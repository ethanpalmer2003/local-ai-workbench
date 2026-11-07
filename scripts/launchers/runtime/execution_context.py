"""Observe the Windows process token without claiming to detect every sandbox policy."""

import ctypes
import json
import os
import sys
from ctypes import wintypes
from typing import TypedDict


class WindowsTokenInfo(TypedDict):
    app_container: bool
    administrator_elevated: bool


class ExecutionContext(TypedDict):
    platform: str
    process_id: int
    windows_token: WindowsTokenInfo | None
    policy_note: str


def execution_context() -> ExecutionContext:
    context: ExecutionContext = {
        "platform": sys.platform,
        "process_id": os.getpid(),
        "windows_token": None,
        "policy_note": "Token flags do not describe all filesystem or network restrictions; consult the active tool policy.",
    }
    if os.name != "nt":
        return context
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        flags = {}
        for name, info_class in (("app_container", 29), ("administrator_elevated", 20)):
            value = wintypes.DWORD()
            returned = wintypes.DWORD()
            if not security.GetTokenInformation(
                token, info_class, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(returned)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            flags[name] = bool(value.value)
        context["windows_token"] = {
            "app_container": flags["app_container"],
            "administrator_elevated": flags["administrator_elevated"],
        }
    finally:
        kernel.CloseHandle(token)
    return context


def require_native_execution(application: str) -> ExecutionContext:
    context = execution_context()
    token = context["windows_token"]
    if token and token["app_container"]:
        message = f"{application} startup is unsupported in the Windows AppContainer sandbox for this workflow. "
        raise RuntimeError(message + "Run in a normal terminal or through approved execution outside the sandbox.")
    return context


if __name__ == "__main__":
    print(json.dumps(execution_context(), indent=2))
