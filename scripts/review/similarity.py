"""Opt-in duplicate check over the maintained sources: needs the embedding server.

Documents mode embeds every bullet or sentence and reports section pairs that share at least
two units (or one long unit). Code mode embeds one function per chunk and reports the pairs
above a higher threshold. A finding is a pair to review; it never edits a file and does not
gate. Run it as `python -m scripts.review.similarity [--code]`, not in the gate.
"""

import argparse
import ast
import json
import re
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from scripts.benchmarks.shared import provenance
from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.launchers.embeddings import server
from scripts.review.sources import maintained_files

LABEL = "embeddings/embeddinggemma-2-Q8_0"
DEFAULT_THRESHOLD = 0.90
CODE_THRESHOLD = 0.95
CODE_MIN_LINES = 3
CODE_MIN_CHARS = 60
CODE_TEXT_LIMIT = 6000
MIN_WORDS = 8
LONG_UNIT_WORDS = 25
BATCH = 24
NEIGHBOURS = 15

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BOILERPLATE = re.compile(
    r"appcontainer\s+false|administrator\s+false|approved\s+(?:outside-sandbox\s+|normal\s+)?(?:execution|token)"
    r"|evidence\s+from\s+\d{4}-\d{2}-\d{2}|draft report, not posted|^evidence:|this machine\.",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    text = LINK.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def usable(text: str) -> bool:
    """A unit worth comparing: real prose, not a repeated procedural line."""
    return len(text.split()) >= MIN_WORDS and not BOILERPLATE.search(text)


def _classify(line: str) -> tuple[str, int, str]:
    """Heading depth and text, bullet text, table marker, or plain prose."""
    heading = HEADING.match(line)
    if heading:
        return "heading", len(heading.group(1)), heading.group(2)
    bullet = BULLET.match(line)
    if bullet:
        return "bullet", 0, bullet.group(1)
    if line.lstrip().startswith("|"):
        return "table", 0, ""
    return "prose", 0, line


class _Units:
    """Collects the units of one Markdown document, one line at a time."""

    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.found: list[dict[str, Any]] = []
        self.stack: list[str] = []
        self.fenced = False
        self.paragraph: list[str] = []

    def _emit(self, text: str, kind: str, line: int | None = None) -> None:
        if usable(text):
            self.found.append(
                {"doc": self.relative, "heading": " / ".join(self.stack), "text": text, "kind": kind, "line": line}
            )

    def _flush(self) -> None:
        text = clean(" ".join(self.paragraph))
        self.paragraph.clear()
        for sentence in SENTENCE.split(text) if text else ():
            self._emit(sentence.strip(), "prose")

    def feed(self, line: str, number: int) -> None:
        if line.startswith(("```", "~~~")):
            self.fenced = not self.fenced
            self._flush()
            return
        if self.fenced or not line.strip():
            self._flush()
            return
        kind, depth, text = _classify(line)
        if kind == "prose":
            self.paragraph.append(text)
            return
        self._flush()
        if kind == "heading":
            self.stack = self.stack[: depth - 1] + [clean(text)]
        elif kind == "bullet":
            self._emit(clean(text), "bullet", number)

    def finish(self) -> list[dict[str, Any]]:
        self._flush()
        return self.found


def units(path: Path, relative: str) -> list[dict[str, Any]]:
    """One unit per bullet or sentence, carrying the document and its heading path."""
    collector = _Units(relative)
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), start=1):
        collector.feed(raw.rstrip(), number)
    return collector.finish()


def embed(texts: list[str], base: str, batch: int = BATCH) -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch):
        body = json.dumps({"input": texts[start : start + batch]}).encode()
        request = urllib.request.Request(
            base + "/v1/embeddings", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.loads(response.read())
        rows = sorted(payload["data"], key=lambda row: row["index"])
        vectors.extend(row["embedding"] for row in rows)
    matrix = np.asarray(vectors, dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def neighbours(vectors: np.ndarray, threshold: float, top: int = NEIGHBOURS) -> list[tuple[float, int, int]]:
    """Cosine pairs above the threshold, each pair once, as (score, lower, higher)."""
    pairs: list[tuple[float, int, int]] = []
    for start in range(0, len(vectors), 512):
        scores = vectors[start : start + 512] @ vectors.T
        rows = np.arange(scores.shape[0])
        scores[rows, np.arange(start, start + rows.size)] = -1.0
        for offset in range(scores.shape[0]):
            index = start + offset
            for other in np.argpartition(scores[offset], -top)[-top:]:
                score = float(scores[offset, other])
                if score >= threshold:
                    pairs.append((score, min(index, int(other)), max(index, int(other))))
    return pairs


def findings(
    pairs: list[tuple[float, int, int]], units_: list[dict[str, Any]], require_two: bool = True
) -> list[dict[str, Any]]:
    """Group unit pairs into section pairs; one lucky sentence is not a finding."""
    grouped: dict[tuple[str, str], list[tuple[float, int, int]]] = defaultdict(list)
    for score, left, right in pairs:
        first, second = units_[left], units_[right]
        left_key = f"{first['doc']} :: {first['heading']}"
        right_key = f"{second['doc']} :: {second['heading']}"
        key = (left_key, right_key) if left_key <= right_key else (right_key, left_key)
        grouped[key].append((score, left, right))
    reported = []
    for key, items in grouped.items():
        longest = max(len(units_[item[1]]["text"].split()) for item in items)
        if not require_two or len(items) >= 2 or longest >= LONG_UNIT_WORDS:
            score, left, right = max(items, key=lambda item: item[0])
            reported.append(
                {
                    "matches": len(items),
                    "best": round(score, 4),
                    "a": key[0],
                    "b": key[1],
                    "a_text": units_[left]["text"],
                    "b_text": units_[right]["text"],
                }
            )
    return sorted(reported, key=lambda row: (-row["matches"], -row["best"]))


def functions(path: Path, relative: str) -> list[dict[str, Any]]:
    """One unit per function or method: the body is embedded verbatim, decorators dropped."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.end_lineno is None:
            continue
        if node.end_lineno - node.lineno + 1 < CODE_MIN_LINES:
            continue
        segment = ast.get_source_segment(text, node) or ""
        if len(segment) < CODE_MIN_CHARS:
            continue
        found.append({"doc": relative, "heading": node.name, "text": segment[:CODE_TEXT_LIMIT], "kind": "function"})
    return found


def changed_sources(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    """Documents whose content differs from the previous report, or that are new."""
    return provenance.changed_files(previous, current)


def latest_report(mode: str) -> dict[str, Any] | None:
    """The most recent report of the same mode, so a run can say what moved since then."""
    runs = sorted((project_cfg.GENERATED_DIR / "shared/similarity" / mode).glob("*/report.json"))
    if not runs:
        return None
    try:
        value = json.loads(runs[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", action="store_true", help="compare functions instead of Markdown prose")
    parser.add_argument("--include-tests", action="store_true", help="with --code: also compare test modules")
    parser.add_argument("--threshold", type=float, default=None, help="default 0.90 for prose, 0.95 for code")
    parser.add_argument("--top", type=int, default=20, help="findings to print")
    parser.add_argument("--strict", action="store_true", help="exit 1 when there is any finding")
    parser.add_argument("--no-server", action="store_true", help="use an already running embedding server")
    args = parser.parse_args(argv)

    mode = "code" if args.code else "documents"
    threshold = args.threshold if args.threshold is not None else (CODE_THRESHOLD if args.code else DEFAULT_THRESHOLD)
    model = model_cfg.path(LABEL)
    if not model.is_file():
        print(f"[FAIL] Embedding model missing: {model}. Download it with the model tooling.")
        return 1
    expected = next((row.sha256 for row in model_cfg.MODELS if row.label == LABEL), None)
    digest = provenance.content_digest(model)
    if expected and digest != expected:
        print(f"[FAIL] {LABEL} differs from the cataloged sha256; refusing to report.")
        return 1

    if args.code:
        paths = [
            item
            for item in maintained_files()
            if item.suffix.lower() == ".py" and (args.include_tests or "/tests/" not in item.as_posix())
        ]
    else:
        paths = [item for item in maintained_files() if item.suffix.lower() == ".md"]
    chunker = functions if args.code else units
    sources = provenance.source_manifest(paths, project_cfg.BASE_DIR)
    previous = latest_report(mode) or {}
    recorded = previous.get("sources")
    changed = changed_sources(recorded or {}, sources)
    note = "no previous source record" if recorded is None else f"{len(changed)} file(s) changed since the last report"

    process = None
    if not args.no_server and not server.ready():
        process = server.start()
    try:
        base = server.url()
        started = time.perf_counter()
        parsed: list[dict[str, Any]] = []
        for path in paths:
            parsed.extend(chunker(path, path.relative_to(project_cfg.BASE_DIR).as_posix()))
        vectors = embed([str(unit["text"]) for unit in parsed], base)
        found = findings(neighbours(vectors, threshold), parsed, require_two=not args.code)
        payload = {
            "model": LABEL,
            "sha256": digest,
            "mode": mode,
            "dimensions": int(vectors.shape[1]),
            "threshold": threshold,
            "units": len(parsed),
            "documents": len(paths),
            "seconds": round(time.perf_counter() - started, 1),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "sources": sources,
            "changed_since_last": changed,
            "findings": found,
        }
        folder = project_cfg.GENERATED_DIR / "shared/similarity" / mode / str(time.time_ns())
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        label = "functions" if args.code else "units"
        print(f"[OK] {payload['documents']} files, {payload['units']} {label}, {len(found)} pairs")
        print(f"[INFO] {note}")
        for row in found[: args.top]:
            print(f"  {row['best']:.3f} matches={row['matches']} {row['a']} <-> {row['b']}")
        print(f"Report: {folder / 'report.json'}")
        return 1 if args.strict and found else 0
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=30)


if __name__ == "__main__":
    raise SystemExit(main())
