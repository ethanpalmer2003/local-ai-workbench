"""Generate the last-run capability matrix from recorded run evidence.

Only work worth scheduling appears: the live suites and benchmarks that start native services and
take minutes. Each row keeps the numbers the last run recorded, links its evidence, and is marked
stale when the build, weights or corpus it recorded no longer match what is installed. A check that
never ran is listed as never run instead of being hidden.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared import language_corpus, provenance
from scripts.config import project_config as project_cfg

OUTPUT = Path(__file__).resolve().parent.parent / "tests/notes/CAPABILITY-MATRIX.md"
REPORT = "artifacts/report.json"
# - Test evidence roots; benchmark runs use the same report layout under a second root
ROOTS = (project_cfg.TEST_OUTPUT_DIR, project_cfg.SCRIPTS_DIR / "benchmarks/output")
# - Long opt-in work: subject under scripts/tests/output, then the label a reader recognizes
CAPABILITIES = (
    ("shared/live_frameworks", "Live launcher and proxy wiring"),
    ("shared/quick_validation", "Quick validation sweep"),
    ("shared/gemma_runtime_screen", "Gemma runtime screen"),
    ("tts_engines/resident", "Resident speech comparison"),
    ("audiocpp/vad_turns", "Silero VAD turns"),
    ("audiocpp/single_server_speech", "Single AudioCpp server speech"),
    ("audiocpp/audiocpp_streaming", "AudioCpp streaming"),
    ("audiocpp/audiocpp_backend_compare", "AudioCpp backend comparison"),
    ("audiocpp/ming_page_smoke", "Ming page smoke"),
    ("asr/shared/practice_smoke", "Practice gateway smoke"),
    ("asr/asr_resident_compare", "Resident ASR comparison"),
    ("asr/shared/latency", "Paced ASR latency"),
    ("asr/shared/language_practice_whisper", "Practice Whisper recognition"),
    ("asr/whisper_embedded_compare", "Embedded Whisper comparison"),
    ("asr/gemma_audio_compare", "Gemma audio comparison"),
    ("asr/parakeetcpp/smoke", "Parakeet Vulkan smoke"),
    ("koboldcpp/kobold_embedded_compare", "Kobold embedded speech comparison"),
    ("koboldcpp/kobold_audiocpp_modes", "Kobold speech modes"),
    ("koboldcpp/kobold_stack_vram", "Kobold stacked VRAM"),
    ("llamacpp/benchmark_specspeed", "Speculative decoding benchmark"),
    ("llamacpp/benchmark_context_stream", "Context stream benchmark"),
    ("llamacpp/benchmark_speedbench", "Speed benchmark"),
    ("llamacpp/benchmark_ngram", "N-gram benchmark"),
    ("llamacpp/benchmark_backends", "llama.cpp backend benchmark"),
    ("llamacpp/gemma_breeze", "Gemma with Breeze speech"),
    ("probes/hrx_updates", "HRX build"),
    ("shared/drama3_offload", "Drama offload screen"),
    ("shared/framework_compare", "Language practice versus Lemonade"),
)

# - Work parked on purpose: the row stays so the page says why it is not judged, and a rerun is not expected
DEFERRED = {"shared/drama3_offload": "the 15.9 GiB local TTS model is heavier than this setup carries"}


@dataclass(frozen=True)
class Row:
    label: str
    subject: str
    evidence: Path | None
    report: dict[str, Any] | None


def _latest_evidence(root: Path, subject: str) -> Path | None:
    """The newest run of one registered capability, ignoring the wider output history beside it."""
    folder = root / subject
    if not folder.is_dir():
        return None
    newest: Path | None = None
    for outcome in folder.iterdir():
        if not outcome.is_dir():
            continue
        for run in outcome.iterdir():
            report = run / REPORT
            if report.is_file() and (newest is None or run.name > newest.parent.parent.name):
                newest = report
    return newest


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def rows() -> list[Row]:
    """One row per registered capability, with its latest evidence when any exists."""
    result = []
    for subject, label in CAPABILITIES:
        found = [path for root in ROOTS if (path := _latest_evidence(root, subject)) is not None]
        evidence = max(found, key=lambda item: item.stat().st_mtime) if found else None
        result.append(Row(label, subject, evidence, _load(evidence) if evidence else None))
    return result


def _mean(values: list[float]) -> str:
    return f"{sum(values) / len(values):.2f}" if values else "n/a"


def _chat_headline(row: dict[str, Any]) -> str | None:
    chat = (row.get("legs") or {}).get("chat")
    if not chat or chat.get("status") != "measured":
        return None
    first = [item["first_token_seconds"] for item in chat["requests"] if item.get("first_token_seconds")]
    return f"{row.get('backend')} TTFT {_mean(first)} s"


def _headline(report: dict[str, Any] | None) -> str:
    """The numbers a reader should keep seeing, even after the row goes stale."""
    if not report:
        return "-"
    results = report.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        parts = [piece for row in results if isinstance(row, dict) for piece in [_chat_headline(row)] if piece]
        if parts:
            return "; ".join(parts)
    summary = report.get("summary")
    if isinstance(summary, dict) and summary.get("pooled_wer") is not None:
        return f"WER {summary['pooled_wer']:.1%}"
    seconds = report.get("total_seconds")
    return f"{seconds:.0f} s" if isinstance(seconds, int | float) else "-"


def _changed(report_model: dict[str, Any]) -> str | None:
    current = provenance.file_identity(str(report_model.get("label", "model")), Path(str(report_model.get("path"))))
    if not current.get("present"):
        return f"{current['label']} missing"
    if (current.get("bytes"), current.get("modified")) != (report_model.get("bytes"), report_model.get("modified")):
        return f"{current['label']} changed"
    return None


def _framework_moved(report_framework: dict[str, Any]) -> str | None:
    key = str(report_framework.get("key", ""))
    if not key or key not in project_cfg.COMPONENTS:
        return None
    current = provenance.framework_state(key)
    recorded = report_framework.get("commit")
    if recorded and current.get("commit") and recorded != current["commit"]:
        return f"{key} moved"
    return None


def deferred(subject: str) -> str | None:
    """Why a parked capability is not judged; None for work that is expected to run."""
    return DEFERRED.get(subject)


def freshness(report: dict[str, Any] | None) -> str:
    """Whether the recorded build, weights and corpus still describe this workspace."""
    if not report:
        return "never run"
    status = str(report.get("status") or "")
    if status and status not in ("completed", "passed"):
        return f"[WARN] last run {status}"
    state = report.get("provenance")
    if not isinstance(state, dict):
        return "[WARN] unprovenanced"
    reasons = [reason for model in state.get("models") or [] if isinstance(model, dict) and (reason := _changed(model))]
    reasons.extend(
        reason
        for framework in state.get("frameworks") or []
        if isinstance(framework, dict) and (reason := _framework_moved(framework))
    )
    corpus = state.get("corpus")
    if isinstance(corpus, dict):
        current = language_corpus.identity()
        if corpus.get("manifest_sha256") != current["manifest_sha256"]:
            reasons.append("corpus manifest changed")
    return "[WARN] stale: " + ", ".join(reasons) if reasons else "[OK]"


def _when(row: Row, report: dict[str, Any] | None) -> str:
    state = (report or {}).get("provenance") or {}
    recorded = state.get("recorded_at") if isinstance(state, dict) else None
    if isinstance(recorded, str):
        return recorded[:10]
    if row.evidence is None:
        return "-"
    try:
        return datetime.fromtimestamp(int(row.evidence.parent.parent.name) / 1e9, UTC).strftime("%Y-%m-%d")
    except ValueError:
        return "-"


def _evidence_link(row: Row) -> str:
    """Cite the run instead of linking it: output folders are untracked, so a link would rot."""
    if row.evidence is None:
        return "-"
    return f"report ({Path(os.path.relpath(row.evidence, OUTPUT.parent)).as_posix()})"


def _status(report: dict[str, Any] | None) -> str:
    if not report:
        return "-"
    value = report.get("status")
    return str(value) if value else "-"


def render(rows_: list[Row]) -> str:
    lines = [
        "# Capability matrix",
        "",
        "Generated by `python -m scripts.tools.capability_matrix`; do not edit by hand.",
        "Only long opt-in work appears. `[WARN] stale` keeps the recorded numbers and names what changed;",
        "`[defer]` marks work parked on purpose, which is not a rerun candidate.",
        "",
        "| Work | Last run | Status | Result | Freshness | Evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows_:
        mark = "[defer]" if deferred(row.subject) else freshness(row.report)
        lines.append(
            f"| {row.label} | {_when(row, row.report)} | {_status(row.report)} | {_headline(row.report)} | "
            f"{mark} | {_evidence_link(row)} |"
        )
    parked = [f"{row.label} ({deferred(row.subject)})" for row in rows_ if deferred(row.subject)]
    if parked:
        lines += ["", "Deferred, no rerun planned: " + "; ".join(parked) + "."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report stale rows and exit non-zero without writing")
    args = parser.parse_args(argv)
    rows_ = rows()
    text = render(rows_)
    parked = [row.label for row in rows_ if deferred(row.subject)]
    stale = [row.label for row in rows_ if deferred(row.subject) is None and freshness(row.report).startswith("[WARN]")]
    if args.check:
        print(f"{len(rows_)} capabilities, {len(stale)} needing a rerun, {len(parked)} deferred")
        for label in stale:
            print(f"[WARN] {label}")
        return 1 if stale else 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"[OK] {OUTPUT.relative_to(project_cfg.BASE_DIR)}")
    print(
        f"{len(rows_)} capabilities, {len(stale)} stale, {len(parked)} deferred, "
        f"{sum(row.report is None for row in rows_)} never run"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
