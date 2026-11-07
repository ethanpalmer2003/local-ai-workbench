"""Amalgamate every llama.cpp benchmark summary into one combined table.

- Scans all `llama-benchmark-summary-*.txt` in the summaries dir (and the
  `old/` dir for pre-deleted-profile runs)
- Handles both summary formats:
    - old:  header `profile  prompt  tokens  avg_seconds  tokens_per_second`
             (no "Builds:" line)
    - new:  header `build/profile  prompt  tokens  ctx_depth  avg_s  tok/s`
             (has a "Builds:" line)
- Uses recorded CSV metadata when available; legacy unknown metadata stays blank
- Writes one combined CSV plus a human-readable table, so you can review
  which build/profile performs best at a glance

Run from C:/AI:
    python -m scripts.benchmarks.amalgamate_benchmarks
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path

from scripts.benchmarks.shared.paths import BenchmarkPaths
from scripts.benchmarks.shared.timing import timed
from scripts.config import project_config as project_cfg

SOURCE_DIRS = (
    BenchmarkPaths(str(project_cfg.SCRIPTS_DIR / "benchmarks/llamacpp/benchmark_llamacpp_profiles.py")).output,
    project_cfg.TEST_OUTPUT_DIR / "llamacpp/benchmark_llamacpp_profiles",
)


@dataclass
class Row:
    timestamp: str
    build: str
    profile: str
    model: str
    ini: str
    params: str
    prompt: str
    tokens: str
    ctx_depth: str
    avg_s: str
    tok_s: str


def parse_summary(path: Path) -> list[Row]:
    """Parse one summary txt into normalized rows (both formats)."""
    recorded = path.with_name(path.name.replace("summary-", "csv-")).with_suffix(".csv")
    if recorded.is_file():
        with recorded.open(encoding="utf-8", newline="") as handle:
            return [
                Row(**{field.name: row.get(field.name, "") for field in fields(Row)}) for row in csv.DictReader(handle)
            ]
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    timestamp = ""
    for line in lines:
        if line.startswith("Benchmark started:"):
            timestamp = line.split(":", 1)[1].strip()
            break

    rows: list[Row] = []
    for line in lines:
        if not line.strip() or "\t" not in line:
            continue
        parts = [p.strip() for p in line.split("\t")]
        # skip the header row and any non-data line
        if parts[0] in ("build/profile", "profile"):
            continue
        if parts[1] == "ERROR":
            continue

        # new format: build/profile  prompt  tokens  ctx_depth  avg_s  tok_s
        # old format: profile  prompt  tokens  avg_seconds  tokens_per_second
        if len(parts) == 6:
            run_label, prompt, tokens, ctx_depth, avg_s, tok_s = parts
        elif len(parts) == 5:
            run_label, prompt, tokens, avg_s, tok_s = parts
            ctx_depth = ""
        else:
            continue

        build, profile = _split_run_label(run_label)
        rows.append(
            Row(
                timestamp=timestamp,
                build=build,
                profile=profile,
                model="",
                ini="",
                params="",
                prompt=prompt,
                tokens=tokens,
                ctx_depth=ctx_depth,
                avg_s=avg_s,
                tok_s=tok_s,
            )
        )
    return rows


def _split_run_label(run_label: str) -> tuple[str, str]:
    """Split `build/profile` into (build, profile); old format has no slash."""
    if "/" in run_label:
        build, profile = run_label.split("/", 1)
        return build, profile
    return "", run_label


def collect_rows() -> list[Row]:
    rows: list[Row] = []
    for source_dir in SOURCE_DIRS:
        for path in sorted(source_dir.rglob("llama-benchmark-summary-*.txt")):
            rows.extend(parse_summary(path))
    return rows


def mean_tok_s(rows: list[Row]) -> float:
    values = []
    for row in rows:
        m = re.match(r"([\d.]+)", row.tok_s)
        if m:
            values.append(float(m.group(1)))
    return sum(values) / len(values) if values else 0.0


def write_outputs(rows: list[Row]) -> tuple[Path, Path]:
    output = BenchmarkPaths(__file__).new_run()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    fieldnames = [field.name for field in fields(Row)]
    csv_file = output.artifacts / f"llama-benchmark-amalgamated-{stamp}.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)

    # human-readable table, one row per run, sorted by mean tok/s (desc)
    table_file = output.artifacts / f"llama-benchmark-amalgamated-{stamp}.txt"
    by_run: dict[tuple[str, str, str, str, str], list[Row]] = {}
    for row in rows:
        by_run.setdefault((row.build, row.profile, row.model, row.ini, row.params), []).append(row)

    lines = [
        "Amalgamated llama.cpp benchmark table",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Runs: {len(by_run)} | source summaries: {len(rows)} rows",
        "",
        "build/profile  model  ini  params  mean_tok/s  (code / prose / overall)",
        "------------------------------------------------------------",
    ]
    for (build, profile, model, ini, params), run_rows in sorted(
        by_run.items(), key=lambda item: mean_tok_s(item[1]), reverse=True
    ):
        per_prompt = {r.prompt: r.tok_s for r in run_rows}
        detail = " / ".join(f"{p}={per_prompt.get(p, '-')}" for p in ("code", "prose", "overall"))
        lines.append(f"{build}/{profile}  {model}  {ini}  {params}  {mean_tok_s(run_rows):.1f}  ({detail})")
    table_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return csv_file, table_file


def main() -> None:
    rows = collect_rows()
    if not rows:
        print("No benchmark summaries found.")
        return
    csv_file, table_file = write_outputs(rows)
    print(f"Amalgamated {len(rows)} rows from all summaries.")
    print(f"CSV:  {csv_file}")
    print(f"Table: {table_file}")


if __name__ == "__main__":
    with timed("shared/reports/amalgamate_benchmarks"):
        main()
