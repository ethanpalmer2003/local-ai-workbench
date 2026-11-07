"""Validate native configuration and preview or apply ComfyUI installation copies."""

import argparse
import json
from pathlib import Path

from scripts.config import overlay_inputs as inputs
from scripts.config import paths
from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server
from scripts.config.coding_agents.pi import packages
from scripts.config.comfyui import workflow_overrides
from scripts.file_util import archive_path


def comfyui_files() -> dict[Path, bytes]:
    source = project_cfg.CONFIG_DIR / "comfyui"
    target = project_cfg.COMFYUI_ROCM_DIR
    if not (source / "workflows").is_dir():
        raise FileNotFoundError(f"Tracked workflow folder missing: {source / 'workflows'}")
    files = {
        target / "extra_model_paths.yaml": paths.load_text(source / "extra_model_paths.yaml").encode("utf-8"),
        target / "custom_nodes/ltx-prompt-cache/__init__.py": (source / "ltx_prompt_cache.py").read_bytes(),
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


def sync_comfyui(apply: bool = False) -> list[Path]:  # noqa: C901
    if not project_cfg.COMFYUI_ROCM_DIR.is_dir():
        raise FileNotFoundError(f"ComfyUI installation missing: {project_cfg.COMFYUI_ROCM_DIR}")
    files = {path.resolve(): content for path, content in comfyui_files().items()}
    for path in files:
        path.relative_to(project_cfg.COMFYUI_ROCM_DIR.resolve())
    record = project_cfg.STATE_DIR / "comfyui/workflow-sync.json"
    retired = workflow_retirements(files, record)
    changed = []
    for target, content in files.items():
        if target.is_file() and target.read_bytes() == content:
            continue
        changed.append(target)
        print(f"{'WRITE' if apply else 'WOULD WRITE'} {target}")
        if apply:
            if target.exists():
                archive_path(target, project_cfg.COMFYUI_ROCM_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    for target in retired:
        changed.append(target)
        print(f"{'RETIRE' if apply else 'WOULD RETIRE'} {target}")
        if apply:
            archive_path(target, project_cfg.COMFYUI_ROCM_DIR)
    if apply:
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
        if not record.is_file() or record.read_text(encoding="utf-8") != content:
            record.parent.mkdir(parents=True, exist_ok=True)
            temporary = record.with_suffix(".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(record)
    print(
        f"[OK] ComfyUI: {len(changed)} changed file(s). Existing replacements go to {(project_cfg.BASE_DIR / 'trash')}."
    )
    return changed


def sync_commandcode(apply: bool = False) -> list[Path]:
    """Copy the private Command Code settings and taste profiles back into the working tree."""
    source = inputs.input_dir() / "commandcode"
    target = project_cfg.BASE_DIR / ".commandcode"
    if not source.is_dir():
        raise FileNotFoundError(f"Private Command Code folder missing: {source}")
    changed = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        destination = target / path.relative_to(source)
        content = path.read_bytes()
        if destination.is_file() and destination.read_bytes() == content:
            continue
        changed.append(destination)
        print(f"{'WRITE' if apply else 'WOULD WRITE'} {destination}")
        if apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    print(f"[OK] Command Code: {len(changed)} changed file(s).")
    return changed


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
        if (inputs.input_dir() / "commandcode").is_dir():
            sync_commandcode(args.apply)
        else:
            print("[INFO] Command Code: no private folder in the overlay; the local .commandcode stays as is.")


if __name__ == "__main__":
    main()
