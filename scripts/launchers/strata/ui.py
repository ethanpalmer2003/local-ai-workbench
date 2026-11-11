"""Start the Strata desktop app with its WebView2 profile under the workspace state folder.

WebView2's default profile path fails to create on this machine (`0x800700AA`), so the app is
launched with an explicit profile it can write. Reuse an already running app.
"""

import os
import subprocess

from scripts.config import project_config as project_cfg


def profile_dir():
    folder = project_cfg.STATE_DIR / "strata/webview"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def main() -> int:
    exe = project_cfg.component("strata").framework_dir / "strata-desktop.exe"
    if not exe.is_file():
        print(f"[FAIL] Strata desktop is not installed: {exe}")
        return 1
    environment = {**os.environ, "WEBVIEW2_USER_DATA_FOLDER": str(profile_dir())}
    subprocess.Popen(
        [str(exe)],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"[OK] Strata desktop started with its webview profile at {profile_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
