import argparse
import json
import os
import shutil
import statistics
import subprocess
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.benchmarks.coding_agents.shared.agent_results import Result, client_sources, save_results
from scripts.benchmarks.coding_agents.shared.benchmark_backends import (
    BenchmarkEndpoint,
    backend_endpoint,
    benchmark_llama_config,
    preflight,
)
from scripts.benchmarks.coding_agents.shared.benchmark_requests import BenchmarkRelay, summarize_requests, warmup
from scripts.benchmarks.coding_agents.shared.framework_tasks import TASKS, CodingTask
from scripts.benchmarks.coding_agents.shared.polyglot_tasks import load_tasks
from scripts.benchmarks.shared import BENCHMARK_SECONDS
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import BENCHMARK_REASONING_EFFORT, report_run
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import coding_clients, llamacpp, llamacpp_coding
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.shared import consent
from scripts.shared.service_identity import endpoint_identity
from scripts.shared.timing import timed

# - Pi is the only coding client this repository benchmarks by default. The other three keep their
#   wiring so a screen can name one with --clients, but a run without that flag measures Pi alone.
CLIENTS = ("pi", "littlecoder", "ohmypi", "nanocoder")
DEFAULT_CLIENTS = ("pi",)
# - launcher profiles plus the benchmark-only ones, so a screen can name `swift15-nospec` directly
PROFILES = {**cfg.LLAMACPP_PROFILES, **cfg.LLAMACPP_BENCHMARK_PROFILES}


def client_command(
    name: str,
    conf: llamacpp.LlamaConfig,
    endpoint: BenchmarkEndpoint | None = None,
    state_dir: Path | None = None,
    pi_extensions: bool = False,
) -> tuple[list[str], dict[str, str]]:
    source = client_sources()[name]
    if name == "pi" and not pi_extensions and state_dir is None:
        raise ValueError("Extension-free Pi benchmarks require isolated state")
    client = isolated_client(source, state_dir) if state_dir else source
    if name == "pi" and not pi_extensions:
        client = replace(client, packages=(), extensions=(), additional_tools=(), cli_args=("--no-extensions",))
    provider = endpoint.provider() if endpoint else None
    provider_name = endpoint.backend if endpoint else "llamacpp"
    if name == "ohmypi":
        cmd, env = (
            coding_clients.prepare_ohmypi(conf, provider, provider_name, client)
            if endpoint
            else coding_clients.prepare_ohmypi(conf)
        )
        return [*cmd, "--no-title", "--auto-approve", "--mode", "json", "-p"], env
    if name == "nanocoder":
        cmd, env = (
            coding_clients.prepare_nanocoder(conf, provider, provider_name, client)
            if endpoint
            else coding_clients.prepare_nanocoder(conf)
        )
        return [*cmd, "--plain", "--json", "--trust-directory", "--mode", "yolo", "run"], env
    env = (
        llamacpp_coding.prepare_pi_env(client, seed_dir=client.agent_dir)
        if state_dir
        else llamacpp_coding.prepare_pi_env(client)
    )
    if name == "pi" and not pi_extensions:
        settings_path = client.agent_dir / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
        settings["packages"] = []
        settings.pop("defaultTools", None)
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    if name == "littlecoder":
        env["LITTLE_CODER_MODELS_FILE"] = str(client.agent_dir / "models.json")
    if endpoint:
        path = client.agent_dir / "models.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        data.setdefault("providers", {})[provider_name] = provider
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        cmd = [
            client.node_cmd,
            str(client.entry),
            *client.cli_args,
            "--provider",
            provider_name,
            "--model",
            endpoint.model,
        ]
    else:
        cmd = llamacpp_coding.pi_command(conf, client)
    if name != "pi":
        cmd.append("--no-update-check")
    return [*cmd, "--mode", "json", "-p"], env


def isolated_client(
    source: cfg.SharedStartupRequestCodingClientSettings, state_dir: Path
) -> cfg.SharedStartupRequestCodingClientSettings:
    state_dir.mkdir(parents=True, exist_ok=True)
    for name in ("settings.json", "keybindings.json", "skills", "extensions"):
        original = source.agent_dir / name
        target = state_dir / name
        if original.is_dir():
            shutil.copytree(original, target, dirs_exist_ok=True)
        elif original.is_file():
            shutil.copy2(original, target)
    return replace(source, agent_dir=state_dir)


def grade(task: CodingTask, workspace: Path, output: Path) -> bool:
    # - verifier source stays outside the agent's working directory
    try:
        result = subprocess.run(
            [str(cfg.VENV_PYTHON), "-X", "utf8", "-c", task.checks],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        output.write_text("Verifier exceeded its 30-second timeout.\n", encoding="utf-8")
        return False
    output.write_text(result.stdout + result.stderr, encoding="utf-8")
    return result.returncode == 0


def _detail_line(usage: dict[str, Any]) -> str:
    """Append whatever native timing the backend reported; never fake a zero."""
    parts = []
    if usage["ttft_seconds"] is not None:
        parts.append(f"ttft {usage['ttft_seconds']:.1f}s")
    if usage["prefill_tokens_per_second"] is not None:
        parts.append(f"prefill {usage['prefill_tokens_per_second']:.0f} tok/s")
    if usage["decode_tokens_per_second"] is not None:
        parts.append(f"decode {usage['decode_tokens_per_second']:.1f} tok/s")
    if usage["draft_acceptance"] is not None:
        parts.append(f"draft {usage['draft_acceptance']:.0%}")
    return "".join(f"; {part}" for part in parts)


def run_task(
    client: str,
    task: CodingTask,
    repeat: int,
    output: RunPaths,
    conf: llamacpp.LlamaConfig,
    timeout: float | None,
    max_turns: int = 12,
    relay: BenchmarkRelay | None = None,
    pi_extensions: bool = False,
) -> Result:
    backend = relay.endpoint.backend if relay else "llamacpp"
    folder = output.artifacts / backend / client / task.name / str(repeat)
    logs = output.logs / backend / client / task.name / str(repeat)
    logs.mkdir(parents=True)
    workspace = folder / "workspace"
    workspace.mkdir(parents=True)
    for name, text in task.files.items():
        (workspace / name).write_text(text, encoding="utf-8", newline="\n")
    (folder / "task-spec.json").write_text(json.dumps(asdict(task), indent=2) + "\n", encoding="utf-8")
    instructions = (
        "# Benchmark Workspace\n\n- Modify only task source files in this directory.\n"
        "- Fix the requested behavior; do not ask for confirmation.\n"
        "- No package installs, network access, or background processes.\n"
        "- Source edits and focused tests here are authorized.\n"
    )
    (workspace / "AGENTS.md").write_text(instructions, encoding="utf-8")
    label = f"{backend}/{client}/{task.name}/{repeat}"
    if relay:
        relay.task = label
        cmd, env = client_command(client, conf, relay.client_endpoint(), folder / "agent-state", pi_extensions)
    else:
        cmd, env = client_command(client, conf, state_dir=folder / "agent-state", pi_extensions=pi_extensions)
    if client == "pi" and not pi_extensions:
        for extension in cfg.PI_CLIENT.extensions:
            cmd.extend(["--extension", str(extension)])
    if client == "nanocoder":
        env["NANOCODER_MAX_TURNS"] = str(max_turns)
    else:
        env["HARNESS_BENCHMARK_MAX_TURNS"] = str(max_turns)
        cmd.extend(["--extension", str(Path(__file__).with_name("turn_budget.mjs"))])
    env["PATH"] = str(cfg.VENV_PYTHON.parent) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(cfg.VENV_PYTHON.parent.parent)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONHOME", None)
    prompt = task.prompt + " Edit the files in the working directory, then stop. Do not merely show a proposed patch."
    if any(name.endswith("_test.py") for name in task.files):
        test_command = f'"{cfg.VENV_PYTHON.as_posix()}" -m unittest discover -p "*_test.py" -v'
        prompt += f" Run the provided tests with: {test_command}. No pytest installation is needed."
    prompt += " Once the tests pass, reply only Done and stop."
    print(f"[RUN] {client}/{task.name}/{repeat}", flush=True)
    started = time.perf_counter()
    timed_out = False
    with (logs / "agent.log").open("wb") as log:
        process = subprocess.Popen(
            [*cmd, prompt], cwd=workspace, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            launch_util.kill_process_tree(process.pid)
            returncode = process.wait(timeout=10)
        finally:
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
                process.wait(timeout=10)
    seconds = time.perf_counter() - started
    if relay:
        relay.cancel_task(label)
    tests_passed = grade(task, workspace, logs / "checks.log")
    passed = tests_passed and returncode == 0 and not timed_out
    records = relay.task_records(label) if relay else []
    (logs / "requests.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    usage = summarize_requests(records)
    tokens = usage["total_tokens"] if usage["usage_complete"] else "unavailable/incomplete"
    print(
        f"[{'OK' if passed else 'FAIL'}] {backend}/{client}/{task.name}: {seconds:.1f}s; tokens: {tokens}"
        f"{_detail_line(usage)}",
        flush=True,
    )
    return Result(
        client,
        task.name,
        repeat,
        passed,
        seconds,
        returncode,
        timed_out,
        str(workspace),
        tests_passed,
        max_turns,
        backend=backend,
        model=relay.endpoint.model if relay else conf.alias,
        pi_extensions=pi_extensions if client == "pi" else False,
        **usage,
    )


def _run_round_tasks(
    args: argparse.Namespace,
    tasks: list[CodingTask],
    conf: llamacpp.LlamaConfig,
    output: RunPaths,
    results: list[Result],
    metadata: list[dict[str, Any]],
    relay: BenchmarkRelay,
    memory: BenchmarkVram,
    repeat: int,
) -> None:
    for task in tasks:
        order = args.clients[(repeat - 1) % len(args.clients) :] + args.clients[: (repeat - 1) % len(args.clients)]
        for client in order:
            memory.stage = f"{client}/{task.name}/{repeat}"
            results.append(
                run_task(
                    client,
                    task,
                    repeat,
                    output,
                    conf,
                    args.timeout,
                    args.max_turns,
                    relay,
                    pi_extensions=getattr(args, "pi_extensions", False),
                )
            )
            save_results(output.artifacts, results, conf, metadata)


def _run_backend_round(
    args: argparse.Namespace,
    tasks: list[CodingTask],
    conf: llamacpp.LlamaConfig,
    output: RunPaths,
    execution_context: dict[str, Any],
    results: list[Result],
    metadata: list[dict[str, Any]],
    settings: dict[str, Any],
    backend: str,
    repeat: int,
) -> None:
    backend_output = RunPaths(output.root / backend / f"round-{repeat}")
    backend_output.create()
    with (
        BenchmarkVram(backend_output, execution_context) as memory,
        backend_endpoint(backend, conf, backend_output, args.strata_config) as endpoint,
    ):
        endpoint.max_tokens = args.max_output_tokens
        if endpoint.context_window != args.context_size:
            raise RuntimeError(
                f"{backend} reports context {endpoint.context_window}, requested {args.context_size}; comparison stopped."
            )
        entry = {
            "backend": backend,
            "model": endpoint.model,
            "repeat": repeat,
            "effective_context": endpoint.context_window,
            "request_settings": settings,
            "max_output_tokens": endpoint.max_tokens,
            "vram_report": str(backend_output.artifacts / "vram.json"),
            **endpoint.metadata,
        }
        metadata.append(entry)
        memory.watch_backend(backend, launch_util.listening_process_ids(urlsplit(endpoint.base_url).port or 80))
        memory.stage = "warmup"
        lifecycle = BenchmarkLifecycle(
            lambda: endpoint_identity(urlsplit(endpoint.base_url).port or 80, endpoint.model)
        )
        lifecycle.adopt_prepared(endpoint.metadata["startup_seconds"])
        lifecycle.warmup(lambda: entry.update(warmup=warmup(endpoint)))
        entry["benchmark"] = lifecycle.record()
        with BenchmarkRelay(endpoint, settings, lifecycle=lifecycle) as relay:
            _run_round_tasks(args, tasks, conf, output, results, metadata, relay, memory, repeat)
        memory.stage = "shutdown"


def run_matrix(
    args: argparse.Namespace,
    tasks: list[CodingTask],
    conf: llamacpp.LlamaConfig,
    output: RunPaths,
    execution_context: dict[str, Any],
) -> list[Result]:
    preflight(conf, args.backends, args.strata_config)
    results: list[Result] = []
    metadata: list[dict[str, Any]] = []
    settings = {
        "temperature": args.temperature,
        "top_p": getattr(args, "top_p", None),
        "top_k": getattr(args, "top_k", None),
        "min_p": getattr(args, "min_p", None),
        "thinking": args.thinking,
        "reasoning_budget": args.reasoning_budget,
        "seed": args.seed,
    }
    try:
        for repeat in range(1, args.repeats + 1):
            offset = (repeat - 1) % len(args.backends)
            for backend in args.backends[offset:] + args.backends[:offset]:
                _run_backend_round(
                    args, tasks, conf, output, execution_context, results, metadata, settings, backend, repeat
                )
    finally:
        save_results(output.artifacts, results, conf, metadata)
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare Strata and llama.cpp models across coding clients on identical tasks."
    )
    parser.add_argument(
        "--clients", nargs="+", choices=CLIENTS, default=list(DEFAULT_CLIENTS), help="coding client to run"
    )
    parser.add_argument(
        "--pi-extensions",
        action="store_true",
        help="Enable configured Pi extensions; default: disable optional extensions on both backends",
    )
    parser.add_argument("--backends", nargs="+", choices=("llamacpp", "strata", "avalon"), default=["llamacpp"])
    parser.add_argument(
        "--strata-config", type=Path, help="Prepared Strata model configuration; default: discover Swift"
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), default="swift15")
    parser.add_argument("--build", choices=sorted(cfg.LLAMACPP_BUILDS))
    parser.add_argument("--context-size", type=int, default=32768)
    parser.add_argument("--max-output-tokens", type=int, default=16384)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--top-p", type=float, default=None, help="Sampling cutoff; omitted leaves the server default")
    parser.add_argument("--top-k", type=int, default=None, help="Sampling cutoff; 0 disables it")
    parser.add_argument("--min-p", type=float, default=None, help="Sampling floor; omitted leaves the server default")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--suite", choices=("polyglot", "local"), default="polyglot")
    parser.add_argument("--tasks", nargs="+")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--thinking", choices=("default", "medium", "low", "off"), default=BENCHMARK_REASONING_EFFORT)
    parser.add_argument("--timeout", type=float, help="Optional wall-clock timeout; disabled by default")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--reasoning-budget", type=int, default=2048, help="Thinking tokens per response")
    parser.add_argument("--server-verbosity", type=int, help="Native server log verbosity; 4 records GPU allocations")
    parser.add_argument("--list", action="store_true", help="list tasks without starting models")
    return parser


def _select_tasks(parser: argparse.ArgumentParser, args: argparse.Namespace) -> list[CodingTask]:
    available = load_tasks() if args.suite == "polyglot" else TASKS
    if args.tasks and set(args.tasks) - {task.name for task in available}:
        parser.error("Unknown task for the selected suite")
    return [task for task in available if not args.tasks or task.name in args.tasks]


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.max_turns < 1:
        parser.error("--max-turns must be positive")
    if args.context_size < 4096 or not 1 <= args.max_output_tokens < args.context_size:
        parser.error("Context must be at least 4096, with a positive output cap smaller than context")
    if args.reasoning_budget < 0 or not 0 <= args.temperature <= 2:
        parser.error("Reasoning budget must be nonnegative; temperature must be 0..2")
    if not 1 <= args.seed <= 2147483647:
        parser.error("Seed must be 1..2147483647 for both backends")
    if args.thinking == "off":
        args.reasoning_budget = 0
    if len(set(args.backends)) != len(args.backends) or len(set(args.clients)) != len(args.clients):
        parser.error("Backends and clients must not contain duplicates")
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")


def _server_overrides(args: argparse.Namespace) -> dict[str, str]:
    overrides: dict[str, str] = (
        {"reasoning": "off", "reasoning-budget": "0"}
        if args.thinking == "off"
        else {"reasoning-effort": args.thinking}
        if args.thinking != "default"
        else {}
    )
    overrides.setdefault("reasoning-budget", str(args.reasoning_budget))
    overrides["ctx-size"] = str(args.context_size)
    overrides["host"] = "127.0.0.1"
    if args.server_verbosity is not None:
        overrides["log-verbosity"] = str(args.server_verbosity)
    return overrides


def _print_client_summary(results: list[Result]) -> None:
    for backend, client in dict.fromkeys((result.backend, result.client) for result in results):
        rows = [result for result in results if result.client == client and result.backend == backend]
        passing = [result.seconds for result in rows if result.passed]
        median = f"{statistics.median(passing):.1f}s" if passing else "n/a"
        print(
            f"{backend}/{client}: {sum(result.passed for result in rows)}/{len(rows)} passed; median passing time {median}"
        )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    tasks = _select_tasks(parser, args)
    if args.list:
        for task in tasks:
            print(f"{task.name}: {task.prompt}")
        return 0
    _validate_args(parser, args)

    context = require_native_execution("Coding model benchmarks")
    print("[CONTEXT] " + json.dumps(context), flush=True)
    conf = benchmark_llama_config(_server_overrides(args), args.profile, args.build)
    output = BenchmarkPaths(__file__).new_run()
    with report_run(
        output,
        "coding_agents/shared/benchmark_agents",
        "coding-agent",
        reasoning=str(cfg.LLAMACPP_SERVER_ARGS["--reasoning-effort"]) if args.thinking == "default" else args.thinking,
        settings={
            "execution_context": context,
            "backends": args.backends,
            "tasks": [task.name for task in tasks],
            "repeats": args.repeats,
            "context_size": args.context_size,
            "temperature": args.temperature,
            "top_p": getattr(args, "top_p", None),
            "top_k": getattr(args, "top_k", None),
            "min_p": getattr(args, "min_p", None),
            "seed": args.seed,
            "max_output_tokens": args.max_output_tokens,
            "max_turns": args.max_turns,
            "timeout": args.timeout,
            "reasoning_budget": args.reasoning_budget,
        },
    ) as run:
        results = run_matrix(args, tasks, conf, output, dict(context))
        failed = any(not result.passed for result in results)
        _print_client_summary(results)
        print(f"[RESULTS] {output.artifacts}")
        if failed:
            run.status = "failed"
        return int(failed)


if __name__ == "__main__":
    consent.require(BENCHMARK_SECONDS)
    with timed("coding_agents/shared/benchmark_agents"):
        raise SystemExit(main())
