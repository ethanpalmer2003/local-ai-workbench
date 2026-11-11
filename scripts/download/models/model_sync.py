"""Compare installed model weights with maintained runtime configuration and download sources."""

import argparse
import json
import os
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.config.audiocpp import server as audio_cfg
from scripts.download.models import download_catalog as download
from scripts.launchers import launcher_config as cfg

MODEL_SUFFIXES = {".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".bin"}
# Catalog destinations own audit coverage, including split/shared model storage.
MODEL_ROOTS = {row.group: project_cfg.component(row.group).models_dir for row in model_cfg.MODELS}
MODEL_ROOTS.update(
    {key: project_cfg.component(key).models_dir / subdir for key, subdir in project_cfg.MODEL_DISCOVERY_SUBDIRS.items()}
)
SOURCE_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".ini", ".kcpps", ".jinja", ".jinja2"}
EXCLUDED_PARTS = {".cache", ".git", ".venv", "__pycache__", "old", "retired", "state", "tests"}


@dataclass(frozen=True)
class ModelReference:
    path: Path
    source: str
    required: bool = True


@dataclass
class ModelSyncReport:
    roots: dict[str, str]
    installed_count: int
    missing: dict[str, list[str]]
    unreferenced: list[str]
    catalog_only: list[str]
    unavailable_roots: list[str]

    @property
    def in_sync(self) -> bool:
        return not (self.missing or self.unreferenced or self.unavailable_roots)


def source_files() -> list[Path]:
    files = []
    for folder, directories, names in os.walk(project_cfg.SCRIPTS_DIR):
        directories[:] = [
            name for name in directories if name not in EXCLUDED_PARTS and not name.startswith("videogen-config-")
        ]
        files.extend(Path(folder) / name for name in names if Path(name).suffix.lower() in SOURCE_SUFFIXES)
    return sorted(files)


def workflow_references() -> list[ModelReference]:
    categories = {"vae": "vae", "clip": "clip", "unet": "unet", "lora": "lora", "upscale": "latent_upscale_models"}
    references = []
    for file in sorted((project_cfg.CONFIG_DIR / "comfyui" / "workflows").glob("*.json")):
        workflow = json.loads(file.read_text(encoding="utf-8"))
        for node in workflow.get("nodes", []):
            category = next((folder for word, folder in categories.items() if word in node["type"].lower()), None)
            if not category:
                continue
            for value in node.get("widgets_values", []):
                if isinstance(value, str) and Path(value).suffix.lower() in MODEL_SUFFIXES:
                    path = project_cfg.COMFYUI_MODELS_DIR / category / value.replace("\\", "/")
                    references.append(
                        ModelReference(path, f"{file.relative_to(project_cfg.BASE_DIR)}:node {node['id']}")
                    )
    return references


def runtime_references() -> list[ModelReference]:
    references = [ModelReference(path, f"KOBOLDCPP_MODELS[{name}]") for name, path in cfg.KOBOLDCPP_MODELS.items()]
    references += [
        ModelReference(model_cfg.path(label), f"ASR_FILE_PROFILES[{name}]:{label}")
        for name, profile in ASR_FILE_PROFILES.items()
        for label in profile.models
    ]
    references.append(
        ModelReference(Path(str(cfg.KOBOLDCPP_KCPPS_ARGS["whispermodel"])), "KOBOLDCPP_KCPPS_ARGS[whispermodel]")
    )
    references += [
        ModelReference(cfg.KOKORO_TTS.koboldcpp_model, "KOKORO_TTS.koboldcpp_model"),
        ModelReference(cfg.KOKORO_TTS.audiocpp_model, "KOKORO_TTS.audiocpp_model"),
        ModelReference(cfg.QWEN3_ASR.model, "QWEN3_ASR.model"),
        ModelReference(cfg.QWEN3_ASR.mmproj, "QWEN3_ASR.mmproj"),
        ModelReference(cfg.GEMMA_AUDIO_ASR.mmproj, "GEMMA_AUDIO_ASR.mmproj"),
        ModelReference(cfg.PARAKEETCPP_ASR.model, "PARAKEETCPP_ASR.model"),
        ModelReference(cfg.PARAKEETCPP_ASR.vad_model, "PARAKEETCPP_ASR.vad_model"),
    ]
    references += [ModelReference(Path(path), f"SDCPP_MODELS[{name}]") for name, path in cfg.SDCPP_MODELS.items()]
    references += [
        ModelReference(project_cfg.LLMS_CODING_MODELS_DIR / profile.model, f"LLAMACPP_PROFILES[{name}]")
        for name, profile in cfg.LLAMACPP_PROFILES.items()
    ]
    source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
    for model in audio_cfg.read(source)["models"]:
        path = Path(model["path"])
        references.append(
            ModelReference(path if path.is_absolute() else source.parent / path, f"{source.name}:{model['id']}")
        )
    references += workflow_references()
    return references


def catalog_references() -> list[ModelReference]:
    return [ModelReference(model.path, f"download catalog:{model.label}", model.in_use) for model in download.MODELS]


def strata_references() -> list[ModelReference]:
    from scripts.launchers.strata.strata_pi import saved_connections

    try:
        connections = saved_connections()
    except FileNotFoundError:
        return []
    references = []
    # The app's live copy can retain old paths; the installed configuration owns the library.
    for connection in connections:
        if connection.config_path.parent.name == "native-instances":
            continue
        args = connection.config.get("args", [])
        paths = [value for value in args if Path(str(value)).suffix.lower() in MODEL_SUFFIXES]
        reader = (connection.config.get("vision") or {}).get("mmproj")
        if reader:
            paths.append(reader)
        for value in paths:
            path = Path(value)
            split = re.fullmatch(r"(.+)-00001-of-(\d{5})\.gguf", path.name, re.IGNORECASE)
            parts = [path]
            if split and 1 < int(split[2]) <= 256:
                parts = [
                    path.with_name(f"{split[1]}-{index:05d}-of-{split[2]}.gguf")
                    for index in range(1, int(split[2]) + 1)
                ]
            references += [ModelReference(part, f"Strata:{connection.config_path.name}") for part in parts]
    return references


def installed_model_files(roots: Mapping[str, Path]) -> set[Path]:
    """Canonical installed-weight scan shared by audit and metadata analysis."""
    return {
        path.resolve()
        for root in roots.values()
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in MODEL_SUFFIXES
        and not EXCLUDED_PARTS.intersection(path.relative_to(root).parts)
    }


def audit_models(
    roots: Mapping[str, Path], references: Iterable[ModelReference], sources: Iterable[Path]
) -> ModelSyncReport:
    roots = {group: path.resolve() for group, path in roots.items()}

    def in_roots(path: Path) -> bool:
        return any(path.is_relative_to(root) for root in roots.values())

    expected: dict[Path, list[str]] = defaultdict(list)
    cataloged = set()
    runtime = set()
    for reference in references:
        path = reference.path.resolve()
        if not in_roots(path):
            continue
        cataloged.add(path)
        if not reference.source.startswith("download catalog:"):
            runtime.add(path)
        if reference.required:
            expected[path].append(reference.source)
    installed = installed_model_files(roots)
    text = "\n".join(file.read_text(encoding="utf-8-sig").lower() for file in sources)
    tokens = re.findall(r"[^\s\"'<>:=,;{}\[\]()]+\.(?:gguf|safetensors|ckpt|pt|pth|onnx|bin)(?![\w.-])", text)
    names = {Path(token.replace("\\", "/")).name for token in tokens}
    unreferenced = sorted(str(path) for path in installed - cataloged if path.name.lower() not in names)
    return ModelSyncReport(
        roots={group: str(path) for group, path in roots.items()},
        installed_count=len(installed),
        missing={str(path): sorted(set(owners)) for path, owners in sorted(expected.items()) if not path.is_file()},
        unreferenced=unreferenced,
        catalog_only=sorted(str(path) for path in (installed & cataloged) - runtime),
        unavailable_roots=[str(path) for path in roots.values() if not path.is_dir()],
    )


def check_model_sync(groups: Sequence[str] | None = None) -> ModelSyncReport:
    roots = {
        name: path
        for name, path in MODEL_ROOTS.items()
        if not groups or any(name == group or name.startswith(group + "/") for group in groups)
    }
    references = [*runtime_references(), *catalog_references()]
    if "strata" in roots:
        references += strata_references()
    return audit_models(roots, references, source_files())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    groups = set(MODEL_ROOTS) | {name.split("/")[0] for name in MODEL_ROOTS}
    parser.add_argument("--group", nargs="+", choices=sorted(groups), help="Limit model folders")
    parser.add_argument("--json", action="store_true", help="Print the complete machine-readable report")
    parser.add_argument(
        "--catalog-only", action="store_true", help="Also list installed files with no runtime registration"
    )
    args = parser.parse_args(argv)
    report = check_model_sync(args.group)
    if args.json:
        print(json.dumps({**asdict(report), "in_sync": report.in_sync}, indent=2))
    else:
        print(
            f"[{'OK' if report.in_sync else 'WARN'}] {report.installed_count} model files checked; "
            f"{len(report.missing)} missing, {len(report.unreferenced)} unreferenced, "
            f"{len(report.catalog_only)} cataloged without a runtime registration."
        )
        for path in report.unavailable_roots:
            print(f"[WARN] Model folder unavailable: {path}")
        for path, owners in report.missing.items():
            print(f"[FAIL] Missing: {path}\n  Referenced by: {', '.join(owners)}")
        for path in report.unreferenced:
            print(f"[WARN] Unreferenced: {path}")
        if args.catalog_only:
            for path in report.catalog_only:
                print(f"[OK] Cataloged, no runtime registration: {path}")
    raise SystemExit(0 if report.in_sync else 1)


if __name__ == "__main__":
    main()
