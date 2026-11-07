"""Install the portable Handy desktop app from its downloaded installer."""

import subprocess

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg


def app_missing() -> bool:
    """True while the portable app has not been installed yet."""
    return not (project_cfg.HANDY_APP_DIR / "handy.exe").is_file()


def prepare_model() -> None:
    source = model_cfg.path("asr/whispercpp/large-v3-turbo-q5_0")
    if not source.is_file():
        return
    target = project_cfg.component("asr/handy").models_dir / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.samefile(source):
            raise RuntimeError(f"Existing Handy model preserved: {target}")
        return
    target.hardlink_to(source)


def install_app() -> None:
    """Run the portable setup only when the app is missing; preserve an installed copy."""
    app = project_cfg.HANDY_APP_DIR
    if not app_missing():
        print("[OK] Existing Handy app preserved")
        prepare_model()
        return
    installer = project_cfg.component("asr/handy").framework_dir / "installer/Handy-setup.exe"
    if not installer.is_file():
        raise RuntimeError("Handy installer missing; update the installer first")
    app.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(installer), "/S", "/PORTABLE", f"/D={app}"], check=True)
    if not (app / "handy.exe").is_file():
        raise RuntimeError("Handy portable setup did not create handy.exe")
    prepare_model()
