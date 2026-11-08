"""Validate native configuration and preview or apply ComfyUI installation copies."""

import argparse
import json
import subprocess
from pathlib import Path

from scripts.config import overlay_inputs as inputs
from scripts.config import paths
from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server
from scripts.config.coding_agents.pi import packages
from scripts.config.comfyui import workflow_overrides
from scripts.file_util import archive_path

NODE_NAME = "ltx-prompt-cache"
NODE_SOURCE = "ltx_prompt_cache.py"
# - <installation>/custom_nodes/<node>/__init__.py, loaded by ComfyUI at startup
NODE_INSTALL = f"custom_nodes/{NODE_NAME}/__init__.py"


def installed_node() -> Path:
    """Installed node copy that the ComfyUI startup check loads."""
    return project_cfg.COMFYUI_ROCM_DIR / NODE_INSTALL


def comfyui_files() -> dict[Path, bytes]:
    source = project_cfg.CONFIG_DIR / "comfyui"
    target = project_cfg.COMFYUI_ROCM_DIR
    if not (source / "workflows").is_dir():
        raise FileNotFoundError(f"Tracked workflow folder missing: {source / 'workflows'}")
    files = {
        target / "extra_model_paths.yaml": paths.load_text(source / "extra_model_paths.yaml").encode("utf-8"),
        installed_node(): (source / NODE_SOURCE).read_bytes(),
    }
    prompt = inputs.setting("video.prompt", "") or None
    negative = inputs.setting("video.negative", "") or None
    prompt_append = inputs.setting("video.prompt_append", "") or None
    negative_append = inputs.setting("video.negative_append", "") or None
    workflows = {}
    for path in (source / "workflows").glob("*.json"):
        content = path.read_bytes()
        if prompt or negative or prompt_append or negative_append:
            saved = json.loads(content.decode("utf-8"))
            workflow_overrides.patch_prompts(saved, prompt, negative, prompt_append, negative_append)
            content = json.dumps(saved, indent=2, ensure_ascii=False).encode("utf-8")
        workflows[target / "user/default/workflows" / path.name] = content
    files.update(workflows)
    return files


def workflow_retirements(files: dict[Path, bytes], record: Path) -> list[Path]:
    if not record.is_file():
        return []
    data = json.loads(record.read_text(encoding="utf-8"))
    if data.get("installation") != project_cfg.COMFYUI_ROCM_DIR.resolve().as_posix():
        return []
    root = (project_cfg.COMFYUI_ROCM_DIR / "user/default/workflows").resolve()
    root.relative_to(project_cfg.COMFYUI_ROCM_DIR.resolve())
    names = data.get("workflows", [])
    if not isinstance(names, list):
        raise ValueError("Invalid managed ComfyUI workflow record")
    retired = []
    for name in names:
        if not isinstance(name, str) or Path(name).name != name or Path(name).suffix.lower() != ".json":
            raise ValueError(f"Invalid managed ComfyUI workflow name: {name!r}")
        target = root / name
        target.resolve().relative_to(root)
        if target not in files and target.exists():
            if not target.is_file():
                raise ValueError(f"Managed ComfyUI workflow is not a file: {target}")
            retired.append(target)
    return retired


def _sync_workflow_files(files: dict[Path, bytes], apply: bool) -> list[Path]:
    changed = []
    for target, content in files.items():
        if target.is_file() and target.read_bytes() == content:
            continue
        changed.append(target)
        print(f"{'WRITE' if apply else 'WOULD WRITE'} {target}")
        if not apply:
            continue
        if target.exists():
            archive_path(target, project_cfg.COMFYUI_ROCM_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return changed


def _retire_workflows(retired: list[Path], apply: bool) -> list[Path]:
    changed = []
    for target in retired:
        changed.append(target)
        print(f"{'RETIRE' if apply else 'WOULD RETIRE'} {target}")
        if apply:
            archive_path(target, project_cfg.COMFYUI_ROCM_DIR)
    return changed


def _write_manifest(record: Path, files: dict[Path, bytes]) -> None:
    workflow_root = (project_cfg.COMFYUI_ROCM_DIR / "user/default/workflows").resolve()
    content = (
        json.dumps(
            {
                "installation": project_cfg.COMFYUI_ROCM_DIR.resolve().as_posix(),
                "workflows": sorted(path.name for path in files if path.parent == workflow_root),
            },
            indent=2,
        )
        + "\n"
    )
    if record.is_file() and record.read_text(encoding="utf-8") == content:
        return
    record.parent.mkdir(parents=True, exist_ok=True)
    temporary = record.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(record)


def sync_comfyui(apply: bool = False) -> list[Path]:
    if not project_cfg.COMFYUI_ROCM_DIR.is_dir():
        raise FileNotFoundError(f"ComfyUI installation missing: {project_cfg.COMFYUI_ROCM_DIR}")
    files = {path.resolve(): content for path, content in comfyui_files().items()}
    for path in files:
        path.relative_to(project_cfg.COMFYUI_ROCM_DIR.resolve())
    record = project_cfg.STATE_DIR / "comfyui/workflow-sync.json"
    retired = workflow_retirements(files, record)
    changed = [*_sync_workflow_files(files, apply), *_retire_workflows(retired, apply)]
    if apply:
        _write_manifest(record, files)
    print(
        f"[OK] ComfyUI: {len(changed)} changed file(s). Existing replacements go to {(project_cfg.BASE_DIR / 'trash')}."
    )
    return changed


def commandcode_paths() -> tuple[Path, Path]:
    """Where the overlay keeps Command Code settings, and the ignored path the tool reads."""
    return inputs.input_dir() / ".commandcode", project_cfg.BASE_DIR / ".commandcode"


def commandcode_plan(source_exists: bool, linked: bool, real_folder: bool) -> str:
    """What the link step would do; kept pure so the decision can be tested without touching disk."""
    if not source_exists:
        return "absent"
    if linked:
        return "linked"
    return "replace-copy" if real_folder else "link"


def commandcode_state() -> tuple[Path, Path, str]:
    """The overlay folder, the workspace path and what a run would do."""
    source, target = commandcode_paths()
    linked = target.is_junction() and target.resolve() == source.resolve()
    real_folder = target.exists() and not target.is_junction()
    return source, target, commandcode_plan(source.is_dir(), linked, real_folder)


def _link_directory(source: Path, target: Path) -> None:
    """A directory junction needs no elevation on Windows and is transparent to the client."""
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(target), str(source)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Could not link {target} to {source}: {detail}")


def sync_commandcode(apply: bool = False) -> None:
    """One physical copy: the workspace path is a junction to the overlay folder."""
    source, target, plan = commandcode_state()
    if plan == "absent":
        print(f"[INFO] Command Code: no .commandcode folder in the overlay ({source}); nothing to link.")
        return
    if plan == "linked":
        print(f"[OK] Command Code: {target} already points at {source}.")
        return
    if plan == "replace-copy":
        print(f"{'ARCHIVE' if apply else 'WOULD ARCHIVE'} the real folder {target}")
        if apply:
            archive_path(target, project_cfg.BASE_DIR)
    print(f"{'LINK' if apply else 'WOULD LINK'} {target} -> {source}")
    if apply:
        _link_directory(source, target)
        print(f"[OK] Command Code: {target} -> {source}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("pi", "audiocpp", "comfyui", "commandcode"))
    parser.add_argument("--apply", action="store_true", help="Write changes; default is preview only")
    args = parser.parse_args(argv)
    if args.only in (None, "pi"):
        print(f"[OK] Pi extension settings: {packages.MANIFEST}; Lens uses editable config/pi/lens.json.")
    if args.only in (None, "audiocpp"):
        server.read()
        print(f"[OK] AudioCpp editable base: {server.CONFIG_PATH}; no regeneration required.")
    if args.only in (None, "comfyui"):
        sync_comfyui(args.apply)
    if args.only in (None, "commandcode"):
        sync_commandcode(args.apply)


if __name__ == "__main__":
    main()
