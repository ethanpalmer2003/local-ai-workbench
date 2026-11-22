"""The documents a coding-agent run writes: its result record, summary rows and comparison.

A runner collects `Result` objects as it goes and calls `save_results` after every task, so the
evidence is readable while the run is still going. The records here describe those files.
"""

import csv
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypedDict

from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import llamacpp

ResultMetadata = dict[str, Any]


@dataclass
class Result:
    client: str
    task: str
    repeat: int
    passed: bool
    seconds: float
    returncode: int | None
    timed_out: bool
    workspace: str
    tests_passed: bool
    max_turns: int
    backend: str = "llamacpp"
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    api_requests: int = 0
    requests_with_usage: int = 0
    usage_complete: bool = False
    api_seconds: float = 0
    api_timing_scope: str = "unclassified_fixture_or_legacy"
    ttft_seconds: float | None = None
    prefilled_tokens: int | None = None
    prefill_seconds: float | None = None
    prefill_tokens_per_second: float | None = None
    decode_tokens_per_second: float | None = None
    draft_acceptance: float | None = None
    pi_extensions: bool = False


class ResultRow(TypedDict):
    """One summary row: the numbers a reader compares, rounded where they are percentages or seconds."""

    client: str
    backend: str
    model: str
    task: str
    passed: bool
    tests_passed: bool
    seconds: float
    max_turns: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cached_tokens: int | None
    prefilled_tokens: int | None
    usage_complete: bool
    api_seconds: float
    ttft_seconds: float | None
    prefill_seconds: float | None
    prefill_tokens_per_second: float | None
    decode_tokens_per_second: float | None
    draft_acceptance: float | None


class ClientPackage(TypedDict):
    """A package the client harness loads, with the version its own manifest declares."""

    name: str
    path: str
    version: str | None


class ClientExtension(TypedDict):
    """A local extension file and its digest, so a changed extension is visible in the record."""

    path: str
    sha256: str | None


class ClientConfiguration(TypedDict):
    """How one client harness ran: extension mode, arguments, packages and local extensions."""

    pi_extensions: bool | None
    cli_args: list[str]
    packages: list[ClientPackage]
    local_extensions: list[ClientExtension]


class ResultsPayload(TypedDict):
    """`results.json`: what produced the numbers, next to every result row."""

    python_executable: str
    python_version: str
    model: str | None
    configured_build: str | None
    server_overrides: dict[str, str]
    reasoning_budget: str
    reasoning_effort: str
    client_versions: dict[str, str]
    client_configuration: dict[str, ClientConfiguration]
    backends: list[dict[str, Any]]
    results: list[dict[str, Any]]


class SummaryPayload(TypedDict):
    """`summary.json`: the same comparison rows without the per-request detail."""

    client_configuration: dict[str, ClientConfiguration]
    reasoning_effort: str
    reasoning_budget: str
    results: list[ResultRow]


def client_sources() -> dict[str, cfg.SharedStartupRequestCodingClientSettings]:
    return {
        "pi": cfg.PI_CLIENT,
        "littlecoder": cfg.LITTLECODER_CLIENT,
        "ohmypi": cfg.OHMYPI_CLIENT,
        "nanocoder": cfg.NANOCODER_CLIENT,
    }


def result_row(result: Result) -> ResultRow:
    """The compact row a reader compares; only the values quoted as medians are rounded."""
    return {
        "client": result.client,
        "backend": result.backend,
        "model": result.model,
        "task": result.task,
        "passed": result.passed,
        "tests_passed": result.tests_passed,
        "seconds": round(result.seconds, 1),
        "max_turns": result.max_turns,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "cached_tokens": result.cached_tokens,
        "prefilled_tokens": result.prefilled_tokens,
        "usage_complete": result.usage_complete,
        "api_seconds": round(result.api_seconds, 3),
        "ttft_seconds": result.ttft_seconds,
        "prefill_seconds": result.prefill_seconds,
        "prefill_tokens_per_second": result.prefill_tokens_per_second,
        "decode_tokens_per_second": result.decode_tokens_per_second,
        "draft_acceptance": result.draft_acceptance,
    }


def save_results(
    root: Path, results: list[Result], conf: llamacpp.LlamaConfig, metadata: list[ResultMetadata] | None = None
) -> None:
    for memory_report in root.parent.glob("*/round-*/logs/llamacpp/*.memory.json"):
        backend, round_name = memory_report.relative_to(root.parent).parts[:2]
        shutil.copyfile(memory_report, root / f"gpu-memory-{backend}-{round_name}.json")
    clients = client_sources()
    versions = {}
    for name in dict.fromkeys(result.client for result in results):
        entry = clients[name].entry
        if name == "ohmypi":
            versions[name] = subprocess.check_output(
                [str(entry), "--version"], text=True, encoding="utf-8", timeout=10
            ).strip()
        else:
            versions[name] = json.loads((entry.parent.parent / "package.json").read_text(encoding="utf-8"))["version"]
    payload: ResultsPayload = {
        "python_executable": str(cfg.VENV_PYTHON),
        "python_version": sys.version.split()[0],
        "model": results[0].model if results and len({result.model for result in results}) == 1 else None,
        "configured_build": str(conf.build_dir) if any(result.backend == "llamacpp" for result in results) else None,
        "server_overrides": conf.ini_overrides,
        "reasoning_budget": conf.ini_overrides.get("reasoning-budget", "server default"),
        "reasoning_effort": conf.ini_overrides.get(
            "reasoning-effort", str(cfg.LLAMACPP_SERVER_ARGS["--reasoning-effort"])
        ),
        "client_versions": versions,
        "client_configuration": {
            name: ClientConfiguration(
                pi_extensions=any(row.pi_extensions for row in results if row.client == name) if name == "pi" else None,
                cli_args=list(clients[name].cli_args)
                if name != "pi" or any(row.pi_extensions for row in results if row.client == name)
                else ["--no-extensions"],
                packages=[
                    ClientPackage(
                        name=path.name,
                        path=str(path),
                        version=json.loads((path / "package.json").read_text(encoding="utf-8")).get("version")
                        if (path / "package.json").is_file()
                        else None,
                    )
                    for path in (
                        clients[name].packages
                        if name != "pi" or any(row.pi_extensions for row in results if row.client == name)
                        else ()
                    )
                ],
                local_extensions=[
                    ClientExtension(
                        path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                    )
                    for path in (
                        *clients[name].extensions,
                        *((Path(__file__).with_name("turn_budget.mjs"),) if name != "nanocoder" else ()),
                    )
                ],
            )
            for name in versions
        },
        "backends": metadata or [],
        "results": [asdict(result) for result in results],
    }
    (root / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    summary: SummaryPayload = {
        "client_configuration": payload["client_configuration"],
        "reasoning_effort": payload["reasoning_effort"],
        "reasoning_budget": payload["reasoning_budget"],
        "results": [result_row(result) for result in results],
    }
    (root / "summary.json").write_text(json.dumps(summary, separators=(",", ":")) + "\n", encoding="utf-8")
    with (root / "results.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(Result.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)
    save_comparison(root, results)


def save_comparison(root: Path, results: list[Result]) -> None:
    def median(values: list[float | None], digits: int = 1) -> str:
        present = [value for value in values if value is not None]
        return f"{statistics.median(present):,.{digits}f}" if present else "n/a"

    lines = [
        "# Coding comparison",
        "",
        "| Backend / model / harness | Solved / trials | Median task seconds | Median total tokens "
        "| Median TTFT | Median prefill tok/s | Median decode tok/s |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key in dict.fromkeys((row.backend, row.model, row.client) for row in results):
        rows = [row for row in results if (row.backend, row.model, row.client) == key]
        tokens = [row.total_tokens for row in rows if row.total_tokens is not None]
        median_tokens = f"{statistics.median(tokens):,.0f}" if len(tokens) == len(rows) else "unavailable/incomplete"
        lines.append(
            f"| {' / '.join(key)} | {sum(row.passed for row in rows)}/{len(rows)} | "
            f"{statistics.median(row.seconds for row in rows):.1f} | {median_tokens} | "
            f"{median([row.ttft_seconds for row in rows])} | "
            f"{median([row.prefill_tokens_per_second for row in rows], 0)} | "
            f"{median([row.decode_tokens_per_second for row in rows])} |"
        )
    lines += [
        "",
        "Task time includes harness startup, model calls and tools; grading and backend startup are separate.",
        "Tokens are server-reported API totals across all turns, including repeated input. Cached tokens are a subset "
        "of input.",
        "TTFT, prefill and decode are medians of server-reported native timings per API request, so harness overhead "
        "is excluded.",
        "Prefill counts only tokens the server actually prefilled, so prefix-cache reuse lowers it without lowering "
        "prompt tokens.",
        "Missing usage is unavailable, not zero. Tokenizers, quants, chat templates and inference backends differ "
        "between "
        "models.",
        "Only compare runs with the same tasks, repetitions, context, sampling and thinking limits.",
    ]
    (root / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
