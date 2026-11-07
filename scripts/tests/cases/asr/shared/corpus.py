"""Shared saved-audio corpus preparation for ASR comparisons."""

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.tests.shared.paths import RunPaths


def default_corpus() -> list[dict[str, str]]:
    roots = (
        project_cfg.TEST_OUTPUT_DIR / "koboldcpp/kobold_embedded_compare/unreviewed",
        project_cfg.TEST_OUTPUT_DIR / "shared/kobold_embedded_compare/unreviewed",
        project_cfg.TEST_OUTPUT_DIR / "probes/kobold_embedded_compare/unreviewed",
    )
    directories = sorted((d for r in roots if r.is_dir() for d in r.iterdir()), key=lambda d: d.name, reverse=True)
    if not directories:
        raise FileNotFoundError("Run the Kokoro comparison to create audio samples first, or pass --corpus")
    for directory in directories[:30]:
        report = directory / "artifacts/report.json"
        if not report.is_file():
            continue
        value = json.loads(report.read_text(encoding="utf-8"))
        settings = value.get("settings", {})
        if value.get("status") != "completed" or settings.get("kind") != "tts" or settings.get("with_chat"):
            continue
        clips = []
        for engine in ("internal", "external"):
            result = directory / engine / "artifacts/results.json"
            if not result.is_file():
                break
            samples = json.loads(result.read_text(encoding="utf-8"))["samples"]
            if len(samples) < 2:
                break
            clips.extend(
                {"id": f"{engine}-{index}", "file": row["file"], "reference": row["request"]["input"]}
                for index, row in enumerate(samples[:2])
            )
        if len(clips) == 4:
            return clips
    raise FileNotFoundError(
        "No completed two-engine Kokoro corpus; run kobold_embedded_compare --kind tts first, or pass --corpus"
    )


def prepare_corpus(run: RunPaths, manifest: Path | None) -> list[dict[str, Any]]:
    from scripts.launchers.shared.media.audio import decode_audio, mono_resample, pcm_wav

    clips = json.loads(manifest.read_text(encoding="utf-8")) if manifest else default_corpus()
    if not isinstance(clips, list) or not clips:
        raise ValueError("Corpus must be a nonempty JSON list of file/reference entries")
    prepared = []
    for index, clip in enumerate(clips):
        source = Path(clip["file"])
        if manifest and not source.is_absolute():
            source = manifest.parent / source
        audio, rate = decode_audio(source)
        if not len(audio):
            raise ValueError(f"Empty source recording: {source}")
        audio = mono_resample(audio, rate)
        destination = run.artifacts / f"clip-{index}.wav"
        destination.write_bytes(pcm_wav(audio))
        prepared.append(
            {
                "id": clip.get("id", str(index)),
                "source": str(source),
                "file": str(destination),
                "reference": clip["reference"],
                "language": clip.get("language", "auto"),
                "duration_seconds": len(audio) / 16000,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            }
        )
    (run.artifacts / "corpus.json").write_text(json.dumps(prepared, indent=2), encoding="utf-8")
    return prepared
