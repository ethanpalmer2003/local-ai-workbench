"""One bundle a heavier model reads instead of the whole repository.

The gate already settles what a light model can fix itself: formatting, lint, spelling, duplicate blocks and
folder caps all fail there, so this bundle carries only what needs judgment: the shape of the tree, the
rules that decide quality, and the exact places where no check looks. A reader starts at `HANDOFF.md`, opens
the ranked files in full, and answers the questions the bundle names; nothing else in the repository is
needed to judge those files.

The measurements here are prompts, never findings: a silent `except` may be deliberate, and a long function
may be one switch. They exist so a reader spends its time on the few places that deserve it.
"""

import argparse
import ast
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import TypedDict, cast

from scripts.config import project_config as project_cfg
from scripts.review.checks.inventory_code import maintained_python
from scripts.review.lists.sources import maintained_files
from scripts.shared import staleness
from scripts.tests import validate
from scripts.tools import cleanup, stage_runner

# - a function past this many lines carries more than one idea, which a reader has to judge rather than fix
LONG_FUNCTION = 60
# - "too many entry points" is a shape question, not a count: a module past this needs a second look
WIDE_SURFACE = 12
SILENT = (ast.Pass, ast.Continue, ast.Return)
BUNDLE_NAME = "HANDOFF.md"
REQUEST_NAME = "REVIEW-REQUEST.md"
# - a screen older than this, or one that predates this many changed files, no longer describes the tree
STALE_DAYS = 7
# - the current bundle and the one it replaced; anything older describes a tree nobody reads
HANDOFF_KEEP = 2
STALE_CHANGES = 25
DUPLICATE_BASELINE = project_cfg.SCRIPTS_DIR / "review" / "lists" / "duplicate-baseline.json"
SIMILARITY_ROOT = project_cfg.GENERATED_DIR / "shared" / "similarity" / "code"
# - the stage runner titles its full-validation run, and its summary is the only record of that verdict
VALIDATION_TITLE = "validate"


class FunctionRecord(TypedDict):
    """One public module-level function, with the shape a reader needs to judge it."""

    name: str
    line: int
    span: int
    signature: str
    documented: bool


class FileRecord(TypedDict):
    """One module: its call shapes and the places where no check looks."""

    path: str
    lines: int
    functions: list[FunctionRecord]
    classes: list[str]
    silent_excepts: list[int]
    broad_excepts: list[int]
    undocumented: list[int]


class SimilarityFinding(TypedDict):
    """One semantic pair, named by file and function, with the score that put it in the report."""

    a: str
    b: str
    best: float


@dataclass(frozen=True)
class SimilarityEvidence:
    """What the last code-similarity run found, so the brief never starts the embedding model itself."""

    created: str
    threshold: float
    changed: int
    findings: list[SimilarityFinding]
    dropped: int = 0


@dataclass(frozen=True)
class FullRun:
    """The last recorded full validation: when it ran, what each stage returned, and what it read."""

    created: str
    total_seconds: float
    stages: list[tuple[str, str, float]]
    fingerprints: dict[str, str] = field(default_factory=dict)


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The call shape a reader needs, without the body: arguments, return annotation and span."""
    arguments = [ast.unparse(argument) for argument in node.args.args]
    returns = ast.unparse(node.returns) if node.returns else "-"
    return f"({', '.join(arguments)}) -> {returns}"


def silent_except(node: ast.ExceptHandler) -> bool:
    """Whether a handler does nothing at all, which is where a real failure disappears."""
    if len(node.body) != 1:
        return False
    statement = node.body[0]
    if isinstance(statement, ast.Return):
        if statement.value is None:
            return True
        # - identity, not equality: `0 == False` would make a real return value look like a swallow
        return isinstance(statement.value, ast.Constant) and (
            statement.value.value is None or statement.value.value is False or statement.value.value == ""
        )
    return isinstance(statement, SILENT)


def broad_except(node: ast.ExceptHandler) -> bool:
    """Whether a handler catches everything, bare or as `Exception`, rather than what it expects."""
    kind = node.type
    if kind is None:
        return True
    return isinstance(kind, ast.Name) and kind.id in {"Exception", "BaseException"}


def file_record(path: Path, workspace: Path) -> FileRecord:
    """Everything the bundle says about one module, from a single parse."""
    source = path.read_text(encoding="utf-8-sig", errors="replace")
    tree = ast.parse(source)
    functions: list[FunctionRecord] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name.startswith("_"):
            continue
        functions.append(
            {
                "name": node.name,
                "line": node.lineno,
                "span": (node.end_lineno or node.lineno) - node.lineno + 1,
                "signature": signature(node),
                "documented": bool(ast.get_docstring(node)),
            }
        )
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    return {
        "path": path.relative_to(workspace).as_posix(),
        "lines": len(source.splitlines()),
        "functions": functions,
        "classes": [node.name for node in tree.body if isinstance(node, ast.ClassDef)],
        "silent_excepts": [node.lineno for node in handlers if silent_except(node)],
        "broad_excepts": [node.lineno for node in handlers if broad_except(node)],
        "undocumented": [item["line"] for item in functions if not item["documented"]],
    }


def weight(record: FileRecord) -> int:
    """How much a file asks of a reader: a silent handler and a long function cost the most."""
    long_functions = sum(1 for item in record["functions"] if int(item["span"]) > LONG_FUNCTION)
    return (
        3 * len(record["silent_excepts"])
        + len(record["broad_excepts"])
        + 2 * long_functions
        + (1 if len(record["functions"]) > WIDE_SURFACE else 0)
    )


def index(workspace: Path, scope: Path | None = None) -> list[FileRecord]:
    """One record per maintained Python file under `scope` (a subtree of `scripts`), heaviest first."""
    records = []
    for path in maintained_python(scope or workspace / "scripts"):
        try:
            records.append(file_record(path, workspace))
        except (OSError, SyntaxError):
            continue
    return sorted(records, key=lambda record: (-weight(record), -int(record["lines"])))


def area(record: FileRecord) -> str:
    """The folder a file reports under, so a reader sees where the weight sits before the files."""
    parts = Path(record["path"]).parts
    return "/".join(parts[:3]) if len(parts) > 3 else "/".join(parts[:-1])


def areas(records: list[FileRecord], shown: int = 8) -> list[tuple[str, int, int]]:
    """(area, files, weight) for the heaviest folders, so one crowded area is visible as one line."""
    totals: dict[str, list[int]] = {}
    for record in records:
        bucket = totals.setdefault(area(record), [0, 0])
        bucket[0] += 1
        bucket[1] += weight(record)
    ordered = sorted(totals.items(), key=lambda item: (-item[1][1], item[0]))
    return [(name, counts[0], counts[1]) for name, counts in ordered[:shown]]


def duplicate_pairs(limit: int = 10) -> list[tuple[str, int]]:
    """The verbatim pairs the baseline already accepts, heaviest first, straight from its reviewed list."""
    try:
        payload = json.loads(DUPLICATE_BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pairs = payload.get("pairs") or {}
    ordered = sorted(((pair, int(count)) for pair, count in pairs.items()), key=lambda item: (-item[1], item[0]))
    return ordered[:limit]


def similarity_evidence(limit: int = 10, root: Path | None = None) -> SimilarityEvidence | None:
    """What the newest code-similarity run still describes, or None when no run wrote a report.

    The check needs the embedding model, so this reads whatever the last opt-in run wrote and starts
    nothing itself. The newest run is the answer even when it found no pair, because that is what a clean
    screen reports; a pair whose file or symbol the tree no longer has is dropped rather than shown, since a
    reader would otherwise hunt for a function renamed in the commit after the run.
    """
    directory = root or project_cfg.BASE_DIR
    reports = sorted(SIMILARITY_ROOT.glob("*/report.json")) if SIMILARITY_ROOT.is_dir() else []
    for report in reversed(reports):
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        findings = cast(list[SimilarityFinding], payload.get("findings") or [])
        live = [row for row in findings if pair_exists(row["a"], directory) and pair_exists(row["b"], directory)]
        return SimilarityEvidence(
            created=str(payload.get("created") or "unknown"),
            threshold=float(payload.get("threshold") or 0.0),
            changed=changed_since_report(payload.get("sources")),
            findings=live[:limit],
            dropped=len(findings) - len(live),
        )
    return None


@cache
def symbols(path: Path) -> frozenset[str]:
    """Every function and class name one file holds, at any depth, so a named symbol can be looked up."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return frozenset()
    return frozenset(
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    )


def pair_exists(label: str, root: Path) -> bool:
    """Whether the tree still has the file a pair names, and the symbol when the label names one."""
    relative, _, symbol = label.partition(" :: ")
    # - a code pair names the line as `name:line`, so a same-named method still resolves to its name
    symbol = symbol.split(":")[0]
    path = root / relative
    if not path.is_file():
        return False
    return not symbol or symbol in symbols(path)


def changed_since_report(recorded: object) -> int:
    """How many of the files that report recorded have changed since it ran.

    The report's own `changed_since_last` counts what moved before that run, so reading it would describe
    the wrong interval. The stored manifest covers a narrower path set than the tree (the code mode skips
    tests), so only its own keys are compared instead of counting every file the tree gained since.
    """
    if not isinstance(recorded, dict) or not recorded:
        return 0
    current = staleness.manifest(maintained_files(), project_cfg.BASE_DIR)
    return sum(1 for relative, digest in recorded.items() if current.get(relative) != digest)


def stale_note(evidence: SimilarityEvidence) -> str | None:
    """Why a similarity screen no longer describes the tree, or None when it still does.

    A reader judges what the report shows, so a screen older than the working tree answers the wrong
    question: a pair naming a removed symbol proves the tree moved, the manifest count measures how far,
    and age catches a tree that moved in ways the report could not count.
    """
    if evidence.dropped:
        return (
            f"[WARN] {evidence.dropped} pair(s) name a file or symbol the tree no longer has; rerun "
            "`python -m scripts.review.checks.similarity --code` before trusting the rest"
        )
    if evidence.changed >= STALE_CHANGES:
        return (
            f"[WARN] the similarity screen predates {evidence.changed} changed file(s); rerun "
            "`python -m scripts.review.checks.similarity --code` before trusting its pairs"
        )
    try:
        created = datetime.fromisoformat(evidence.created)
    except ValueError:
        return None
    age = (datetime.now() - created).days
    if age > STALE_DAYS:
        return (
            f"[WARN] the similarity screen is {age} days old, which predates the tree it describes; rerun "
            "`python -m scripts.review.checks.similarity --code`"
        )
    return None


def review_request(records: list[FileRecord], ranked: int = 12) -> list[str]:
    """The instruction a heavier model is given: review for quality, and do not do these things."""
    lines = [
        "# Review request",
        "",
        "Paste this and attach the bundle folder; `HANDOFF.md` beside it describes the tree.",
        "",
        "## What to do",
        "",
        "1. Read `HANDOFF.md`.",
        "2. Read these files in full. The paths are relative to the repository root, so a reviewer holding the",
        "   checkout opens them there; one without it needs their contents pasted in before the review starts:",
        "",
    ]
    lines.extend(f"- {record['path']}" for record in records[:ranked])
    lines.extend(
        (
            "",
            "3. Review them the way you would review any codebase, from your own knowledge of design, naming,",
            "   error handling, data flow and testability. The ranking and metrics in the brief say where the weight",
            "   sits, not what to look for.",
            "4. Where a judgment needs this project's own conventions and you have the repository, they are in",
            "   `.agents/CODE.md`, document budgets in `.agents/NOTES-CONVENTIONS.md` and folder contracts in",
            "   `.agents/FOLDERS.md`. Apply them; they are not the review's scope. Without the repository, judge by",
            "   what the code itself shows and say when a convention is what you lack.",
            "5. `.agents/skills/code-review/SKILL.md` offers a reviewer role and an answer shape. Take it into",
            "   account rather than treat it as the whole rubric; your own judgment decides what matters.",
            "",
            "## What not to spend the review on",
            "",
            "These exclude what a deterministic rule already settles and keep the effort focused. They do not bound",
            "what you may propose: a different design, a new abstraction, a library this repository does not have,",
            "a missing test or a rule it should adopt are all fair findings.",
            "",
            "1. Do not report what a deterministic check already fails on: formatting, lint, spelling, ASCII",
            "   punctuation, duplicate blocks, line and file length, folder caps, dead code, type errors. If one of",
            "   those rules is itself wrong, say so once.",
            "2. Do not restate the brief, and keep strengths to the ones a decision depends on.",
            "3. Do not hedge. A finding names a file, a line and a concrete change, or it is not a finding.",
            "4. Do not write patches or diffs. Name the change; the light model applies it.",
            "5. Do not read past the listed files unless one of them proves the answer needs another; name that file",
            "   and why.",
            "6. Do not report a deliberate trade-off as a defect. A silent handler or a long function that is",
            "   commented as intended is deliberate: say so, and mark any rule you propose that has no precedent here.",
            "",
            "## How to answer",
            "",
            "Take the answer shape from `.agents/skills/code-review/SKILL.md` where it fits: strengths first, then",
            "issues by severity (Critical, Important, Minor) with file and line, then a verdict of ready to merge or",
            "not. Say per finding whether it is a defect or deliberate, and where the shape does not fit, answer in",
            "your own way.",
        )
    )
    return lines


def last_full_run(directory: Path | None = None) -> FullRun | None:
    """The newest recorded validation run, or None when none left a summary behind.

    The logs hold each child's output but not its verdict, so the runner writes one summary beside them;
    this reads that instead of guessing from a log tail.
    """
    folder = directory or stage_runner.runs_dir(VALIDATION_TITLE)
    summaries = sorted(folder.glob("*/summary.json")) if folder.is_dir() else []
    for path in reversed(summaries):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = payload.get("stages") or []
        return FullRun(
            created=str(payload.get("created") or "unknown"),
            total_seconds=float(payload.get("total_seconds") or 0.0),
            stages=[
                (str(row.get("key") or "?"), str(row.get("status") or "?"), float(row.get("seconds") or 0.0))
                for row in rows
            ],
            fingerprints={str(row.get("key")): str(row.get("fingerprint") or "") for row in rows},
        )
    return None


def full_run_issues(run: FullRun | None, current: dict[str, str] | None = None) -> list[str]:
    """Why this bundle may not be handed off yet: no run, a failed stage, or a stage whose inputs moved.

    Comparison is by content, not by clock: a stage whose recorded fingerprint still matches what it reads is
    covered even when a later commit touched a document the stage does not read, which is what the cache is
    for. The gate reads every maintained file, so a documentation change shows up there and only there.
    """
    if run is None:
        return ["No recorded full validation; run `bat/checks/test_full.bat` before handing off"]
    if not run.stages:
        return ["The last full validation recorded no stage; rerun `bat/checks/test_full.bat`"]
    failed = [key for key, status, _ in run.stages if status == "failed"]
    if failed:
        return [f"The last full validation failed at {', '.join(failed)}; fix it before handing off"]
    fingerprints = validate.stage_fingerprints() if current is None else current
    stale = [
        key
        for key, status, _ in run.stages
        if status != "failed" and run.fingerprints.get(key) != fingerprints.get(key)
    ]
    if stale:
        return [
            f"The inputs of {', '.join(stale)} changed after the last full validation; rerun "
            "`bat/checks/test_full.bat` (unchanged stages are skipped)"
        ]
    return []


def full_run_report(run: FullRun | None) -> list[str]:
    """The block at the top of the brief: when the full test ran and what every stage returned."""
    lines = ["## The full test behind this bundle", ""]
    if run is None:
        lines.append("No recorded run. `bat/checks/test_full.bat` records one and this bundle needs it.")
        return lines
    stages = ", ".join(f"{key} {status}" for key, status, _ in run.stages)
    if all(status == "cached" for _, status, _ in run.stages):
        lines.append(
            f"No stage needed rerunning: the last pass still covers this tree, checked {run.created} ({stages})."
        )
    else:
        lines.append(
            f"`python -m scripts.tests.validate` ran {run.created} and finished {len(run.stages)} stage(s) "
            f"in {run.total_seconds:.0f} s: {stages}."
        )
    if any(status == "skipped" for _, status, _ in run.stages):
        lines.append("")
        lines.append("A skipped live stage had no changed source or install to re-test, which is a pass.")
    return lines


def brief(records: list[FileRecord], ranked: int = 12) -> list[str]:
    """The markdown a heavier model reads first, and the only thing it needs before opening files."""
    total_functions = sum(len(record["functions"]) for record in records)
    silent = sum(len(record["silent_excepts"]) for record in records)
    broad = sum(len(record["broad_excepts"]) for record in records)
    wide = sum(1 for record in records if len(record["functions"]) > WIDE_SURFACE)
    lines = [
        "# Handoff brief",
        "",
        "Read this, then the files under **Where to look first**. The rest of the repository does not have to",
        "be read to judge them: the mechanical findings are already the gate's job, and this bundle omits them.",
        "",
        *full_run_report(last_full_run()),
        "",
        "## What this is",
        "",
        "A Windows-only workspace that drives local models: launchers, catalog updaters, benchmarks, a test",
        "suite and the review gate that guards them. Rules live in `.agents/CODE.md`; the gate's sections and",
        "their levels in `.agents/CHECKS.md`. A change lands through `python -m scripts.review` and",
        "`python -m scripts.tests.run`, both scoped to the change and both taking `--all`.",
        "",
        "## The rules that decide quality",
        "",
        "- One owner per fact: a literal, a rule or a path is spelled once, and every other mention imports it.",
        "- A name states its object: `selection`, not `scoping`; a folder that holds one thing names it.",
        "- No unnecessary logic: the presence of something (a field, a file, a flag) carries the decision.",
        "- Smaller pieces with clear branches beat clever economy; a helper nothing exercises is complexity.",
        "- A failure is raised and named, never swallowed: a silent `except` is the smell this bundle ranks.",
        "- A dependency is preferred to a hand-written traversal; the standard library is checked first.",
        "",
        "## The shape",
        "",
        f"- {len(records)} maintained Python files, {total_functions} public module-level functions.",
        f"- {silent} silent handler(s) and {broad} broad handler(s) across the tree.",
        f"- {wide} module(s) expose more than {WIDE_SURFACE} public functions.",
        "",
        "## Where the weight sits",
        "",
        "| Area | Files | Weight |",
        "| --- | ---: | ---: |",
    ]
    lines.extend(f"| {name} | {files} | {total} |" for name, files, total in areas(records))
    lines.extend(
        (
            "",
            "## Where to look first",
            "",
            "Ranked by how much judgment a file asks for, not by how long it is.",
            "",
            "| File | Lines | Public functions | Silent handlers | Broad handlers | Long functions |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        )
    )
    for record in records[:ranked]:
        long_functions = sum(1 for item in record["functions"] if int(item["span"]) > LONG_FUNCTION)
        lines.append(
            f"| {record['path']} | {record['lines']} | {len(record['functions'])} | "
            f"{len(record['silent_excepts'])} | {len(record['broad_excepts'])} | {long_functions} |"
        )
    lines.extend(evidence_report())
    lines.extend(
        (
            "",
            "## The instruction",
            "",
            "`REVIEW-REQUEST.md` beside this file is what the reviewer is handed: a general quality review from its",
            "own knowledge, the list of what not to do, and the answer shape. Those rules live only there.",
            "",
            "`ast_map.json` beside this file holds every file's public functions, signatures and span, for a",
            "reader that wants the shape without opening a single file.",
        )
    )
    return lines


def evidence_report(root: Path | None = None) -> list[str]:
    """What the opt-in checks already found, read from their last run rather than re-run here."""
    lines = [
        "",
        "## Evidence the opt-in checks already hold",
        "",
        "Verbatim duplicate blocks the baseline accepts, so they are expected rather than new:",
        "",
    ]
    pairs = duplicate_pairs()
    if pairs:
        lines.extend(
            (
                "| Pair | Blocks |",
                "| --- | ---: |",
                *(f"| {pair.replace('|', ' <-> ')} | {blocks} |" for pair, blocks in pairs),
            )
        )
    else:
        lines.append("None recorded; `bat/checks/review_duplicates.bat` writes the list.")
    evidence = similarity_evidence(root=root)
    lines.extend(("", "Semantic code pairs from the last `--code` similarity run:", ""))
    if evidence is None:
        lines.append(
            "None available. That check needs the embedding model, so it is opt-in: "
            "[similarity](SIMILARITY.md) names the command."
        )
    else:
        lines.extend(
            (
                f"Report created {evidence.created} at threshold {evidence.threshold}, "
                f"{evidence.changed} file(s) changed since.",
            )
        )
        note = stale_note(evidence)
        if note:
            lines.append(note)
        if evidence.findings:
            lines.extend(
                (
                    "",
                    "| Function A | Function B | Best |",
                    "| --- | --- | ---: |",
                    *(f"| {item['a']} | {item['b']} | {item['best']} |" for item in evidence.findings),
                )
            )
        else:
            lines.append(
                "Every pair it recorded names a file or symbol the tree has since changed."
                if evidence.dropped
                else "No pair cleared the threshold in that run."
            )
    return lines


def prune_superseded(destination: Path) -> list[Path]:
    """Move every bundle but the newest two to trash: a handoff is superseded by the next one.

    The folder grows once a day at most, so two cover the current review and the one it replaced; anything
    older describes a tree nobody is reading.
    """
    bundles = sorted(
        (path for path in destination.parent.iterdir() if path.is_dir()), key=lambda path: path.name, reverse=True
    )
    stale = cleanup.superseded(bundles, cited=set(), keep=HANDOFF_KEEP, older_days=-1)
    if stale:
        cleanup.move_to_trash(stale, datetime.now().strftime("%Y-%m-%d"), dry_run=False)
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranked", type=int, default=12, help="how many files the brief names first")
    parser.add_argument("--path", help="limit the index to a subtree, for example scripts/launchers")
    parser.add_argument("--out", help="folder for the bundle (default: the generated handoff tree)")
    args = parser.parse_args(argv)
    scope = project_cfg.BASE_DIR / args.path if args.path else None
    if scope is not None and not scope.is_dir():
        print(f"[FAIL] No such folder: {args.path}")
        return 1
    issues = full_run_issues(last_full_run())
    if issues:
        for issue in issues:
            print(f"[FAIL] {issue}")
        return 1
    records = index(project_cfg.BASE_DIR, scope)
    destination = (
        Path(args.out) if args.out else project_cfg.component("shared").generated_dir / "handoff" / str(time.time_ns())
    )
    destination.mkdir(parents=True, exist_ok=False)
    (destination / BUNDLE_NAME).write_text("\n".join(brief(records, args.ranked)) + "\n", encoding="utf-8")
    (destination / REQUEST_NAME).write_text("\n".join(review_request(records, args.ranked)) + "\n", encoding="utf-8")
    (destination / "ast_map.json").write_text(json.dumps({"files": records}, indent=2) + "\n", encoding="utf-8")
    silent = sum(len(record["silent_excepts"]) for record in records)
    for stale in prune_superseded(destination):
        print(f"[PRUNE] superseded bundle moved to trash: {stale.name}")
    print(f"[OK] Handoff: {len(records)} files, {silent} silent handler(s)")
    print(f"[OK] Bundle: {destination / BUNDLE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
