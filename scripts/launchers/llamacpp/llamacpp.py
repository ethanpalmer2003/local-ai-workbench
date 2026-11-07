"""llama.cpp server launcher:
- base INI settings plus profile overrides
"""

import argparse
import configparser
import re
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.launch_util import (
    build_cli_args,
    kill_process_tree,
    launch_process,
    print_ready,
    trigger_preload,
    wait_for_backend,
    wait_for_exit,
)
from scripts.launchers.launcher_config import ConsoleTerminalLaunchMode
from scripts.launchers.llamacpp import llamacpp_profiles as profiles

# - what --dry-run prints for --log-file; a real launch picks a timestamped path
#   under the same tree. Never a temporary directory: these launchers also run
#   from the harness terminal, whose sandbox only permits writes in the project
DRY_RUN_LOG_FILE = project_cfg.component("llamacpp").logs_dir / "llama_server.log"


def _merge_profile(profile: profiles.LLMProfile, overrides: dict[str, str] | None) -> profiles.LLMProfile:
    """Apply supported CLI profile overrides:
    - without weakening the profile type
    """
    for key in overrides or {}:
        if key not in {"model", "ini"}:
            raise ValueError(f"Unsupported profile override: {key}")
    return replace(profile, **(overrides or {}))


class LlamaConfig:
    def __init__(
        self,
        profile_name: str | None = None,
        build_name: str | None = None,
        build_dir: str | Path | None = None,
        prof_overrides: dict[str, str] | None = None,
        ini_overrides: dict[str, str] | None = None,
        skip_ini: bool = False,
        profiles: dict[str, profiles.LLMProfile] | None = None,
        port: int | None = None,
    ) -> None:
        build = self._resolve_build(build_name, build_dir)
        self.name: str = profile_name or build.default_profile or cfg.LLAMACPP_ACTIVE_CODING_AGENT_PROFILE
        profiles = profiles if profiles is not None else cfg.LLAMACPP_PROFILES

        if self.name not in profiles:
            raise ValueError(f"Unknown profile: {self.name}")

        self.profile = _merge_profile(profiles[self.name], prof_overrides)
        self.build_dir: Path
        self.build_extra: dict[str, str]
        self.build_dir, self.build_extra = Path(build.bin_dir), dict(build.extra_args)
        self.build_env = dict(build.env)
        self.unsupported_server_args = build.unsupported_server_args
        self.model: Path = project_cfg.LLMS_CODING_MODELS_DIR / self.profile.model
        self.exe: Path = self.build_dir / "llama-server.exe"
        self.ini_path: Path = cfg.LLAMACPP_INI_DIR / self.profile.ini
        self.skip_ini: bool = skip_ini
        self.ini_overrides: dict[str, str] = ini_overrides or {}
        self.port: int = cfg.LLAMACPP_SERVICE.port if port is None else port

    def _resolve_build(self, name: str | None, dir_path: str | Path | None) -> cfg.LlamacppStartupBuild:
        builds = cfg.LLAMACPP_BUILDS

        if name:
            if name not in builds:
                raise ValueError(f"Unknown build: {name}")
            build = builds[name]
            return build

        if dir_path:
            dp = Path(dir_path).resolve()
            for build in builds.values():
                if Path(build.bin_dir).resolve() == dp:
                    return build
            return cfg.LlamacppStartupBuild(bin_dir=dp)

        build = builds[cfg.LLAMACPP_ACTIVE_BUILD]
        return build

    @property
    def alias(self) -> str:
        """The model id llama-server reports and every client must request"""
        return Path(self.profile.model).stem

    def get_ini(self) -> dict[str, str]:
        if self.skip_ini:
            return {}

        parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
        with self.ini_path.open(encoding="utf-8") as ini_file:
            parser.read_file(ini_file)
        return {**dict(parser.defaults()), **self.ini_overrides}

    def build_cmd(self, log_file: Path) -> list[str]:
        args = ["-m", str(self.model), "--alias", self.alias]
        args += build_cli_args(
            {
                **{
                    key: value
                    for key, value in cfg.LLAMACPP_SERVER_ARGS.items()
                    if key.lstrip("-") not in self.unsupported_server_args
                },
                "--host": cfg.LLAMACPP_SERVICE.listen_ip,
                "--port": self.port,
                "-lv": cfg.LLAMACPP_SERVICE.verbosity,
            }
        )

        if self.build_extra:
            args += build_cli_args(self.build_extra)

        args += ["--log-file", str(log_file)]

        for key, value in self.get_ini().items():
            if key == "model":
                continue
            if key == "jinja":
                if value.lower() in ("on", "true", "1"):
                    args.append("--jinja")
                continue
            args += build_cli_args({key: value})

        # - profiles override shared INI defaults, including MTP and context settings
        profile_extra = self.profile.extra_args
        if profile_extra:
            args += build_cli_args(profile_extra)

        return [str(self.exe)] + args


def _parse_kv_list(pairs: list[str]) -> dict[str, str]:
    """--ini-set/--ini-profile-set entries as a dict"""
    out = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"expected KEY=VALUE, got: {pair!r}")
        key, _, value = pair.partition("=")
        out[key.strip()] = value.strip()
    return out


def add_config_args(parser: argparse.ArgumentParser) -> None:
    """The server-config CLI every llama.cpp client launcher accepts"""
    parser.add_argument("--llama-cpp-dir", default=None, help="Raw override for the llama.cpp build dir.")
    parser.add_argument("--llama-cpp-build", default=None, help="Select a named build from cfg.LLAMACPP_BUILDS.")
    parser.add_argument("--ini-profile", default=None, help="Override cfg.ACTIVE_LLAMACPP_CODING_AGENT_PROFILE.")
    parser.add_argument("--ini-skip", action="store_true", help="Skip parsing the profile's base INI entirely.")
    parser.add_argument("--ini-set", action="append", default=[], metavar="KEY=VALUE", help="Override any INI key.")
    parser.add_argument(
        "--ini-profile-set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override profile identity fields (e.g. ini=other.ini, model=other.gguf).",
    )


def config_from_args(args: argparse.Namespace, port: int | None = None) -> LlamaConfig:
    """The server configuration an add_config_args CLI describes"""
    return LlamaConfig(
        profile_name=args.ini_profile,
        build_name=args.llama_cpp_build,
        build_dir=args.llama_cpp_dir,
        prof_overrides=_parse_kv_list(args.ini_profile_set),
        ini_overrides=_parse_kv_list(args.ini_set),
        skip_ini=args.ini_skip,
        port=port,
    )


def config_argv(args: argparse.Namespace) -> list[str]:
    """The add_config_args flags to hand on to another launcher"""
    argv: list[str] = []

    for flag, value in (
        ("--llama-cpp-dir", args.llama_cpp_dir),
        ("--llama-cpp-build", args.llama_cpp_build),
        ("--ini-profile", args.ini_profile),
    ):
        if value:
            argv += [flag, value]

    if args.ini_skip:
        argv.append("--ini-skip")

    for value in args.ini_set:
        argv += ["--ini-set", value]

    for value in args.ini_profile_set:
        argv += ["--ini-profile-set", value]

    return argv


def config_given(args: argparse.Namespace) -> bool:
    """True when the caller configured a server an already-running one cannot honour"""
    return bool(config_argv(args))


@dataclass
class LlamaAllocationReport:
    projected_mb: float | None = None
    available_before_mb: float | None = None
    offloaded_layers: int | None = None
    total_layers: int | None = None
    buffer_lines: list[str] = field(default_factory=list)


class LlamaMonitor:
    def __init__(self, log_file: Path) -> None:
        self.log_file: Path = log_file

    def wait_ready(self, port: int) -> bool:
        print("[llm] waiting for llama-server...")

        # - readiness comes from /health, never from the log: "all slots are
        #   idle" is trace level, so any lowered --verbosity would hide it and
        #   this would report a timeout against a server that was serving
        return wait_for_backend(port, cfg.LLAMACPP_SERVICE.ready_timeout_s)

    def allocation_report(self) -> LlamaAllocationReport:
        report = LlamaAllocationReport()
        if not self.log_file.is_file():
            return report
        for line in self.log_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if m := re.search(r"projected to use\s+([\d.]+).*vs\.\s+([\d.]+)", line):
                report.projected_mb, report.available_before_mb = float(m.group(1)), float(m.group(2))
            if m := re.search(r"offloaded (\d+)/(\d+) layers to GPU", line):
                report.offloaded_layers, report.total_layers = int(m.group(1)), int(m.group(2))
            if m := re.search(r"(\S+\s+(?:model|KV|compute) buffer size\s*=\s*[\d.]+\s*MiB)", line):
                buffer = m.group(1)
                if buffer not in report.buffer_lines:
                    report.buffer_lines.append(buffer)
        return report

    def print_summary(self) -> None:
        report = self.allocation_report()
        if report.projected_mb is None and not report.buffer_lines and report.offloaded_layers is None:
            print("[llm] native allocation details unavailable; use --log-verbosity 4")
            return
        print("[llm] native allocation report:")
        if report.offloaded_layers is not None:
            print(f"  > GPU layers: {report.offloaded_layers}/{report.total_layers}")
        if report.projected_mb is not None and report.available_before_mb is not None:
            print(f"  > Estimated VRAM use: {report.projected_mb / 1024:.1f} GiB")
            print(f"  > Available before load: {report.available_before_mb / 1024:.1f} GiB")
            print(f"  > Estimated remaining: {(report.available_before_mb - report.projected_mb) / 1024:.1f} GiB")
        for line in report.buffer_lines:
            print(f"  > Native buffer: {line}")


def warmup(conf: LlamaConfig) -> None:
    if cfg.LLAMACPP_SERVICE.warmup:
        print("[llm] warming up with a one-token request...")
    trigger_preload(
        enabled=cfg.LLAMACPP_SERVICE.warmup,
        tag="llm",
        url=f"{cfg.llama_base_url(conf.port)}/chat/completions",
        payload={
            "model": conf.alias,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1,
            "stream": False,
        },
        on_success=lambda: print("[llm] warmup complete"),
        # - finish before short-lived launchers exit and discard a daemon thread
        background=False,
    )


def launch(
    extra_args: list[str] | None = None,
    conf: LlamaConfig | None = None,
    mode: ConsoleTerminalLaunchMode | None = None,
    log_dir: Path | None = None,
    clear_port: bool = True,
):
    conf = conf or LlamaConfig()
    monitor_log = (log_dir or project_cfg.component("llamacpp").logs_dir) / f"llama_server_{time.time_ns()}.log"
    monitor_log.parent.mkdir(parents=True, exist_ok=True)
    monitor = LlamaMonitor(monitor_log)

    print(f"[llm] profile: {conf.name} | model: {conf.model.name}")
    build_args = f" (args: {conf.build_extra})" if conf.build_extra else ""
    print(f"[llm] build:   {conf.build_dir}{build_args}")

    ini_display = "skipped (--no-ini)" if conf.skip_ini else f"{conf.ini_path.name} [DEFAULT]"
    print(f"[llm] ini:     {ini_display}")

    profile_extra = conf.profile.extra_args
    if profile_extra:
        print(f"[llm] profile args: {profile_extra}")

    cmd = [*conf.build_cmd(monitor.log_file), *(extra_args or [])]
    port = conf.port
    startup_marker = monitor.log_file.with_suffix(".ready")
    terminal_cmd = [
        sys.executable,
        "-m",
        "scripts.launchers.llamacpp.llamacpp_terminal",
        "--cwd",
        str(conf.build_dir),
        "--startup-marker",
        str(startup_marker),
        "--log-file",
        str(monitor.log_file),
        "--",
        *cmd,
    ]

    proc = launch_process(
        terminal_cmd,
        title="LlamaCpp Server",
        cwd=str(project_cfg.BASE_DIR),
        kill_ports=port if clear_port else None,
        mode=mode,
        env=conf.build_env,
    )

    try:
        if not monitor.wait_ready(port):
            print("\n[llm] server timed out waiting for ready.")

            if monitor.log_file.is_file():
                print("\n".join(monitor.log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]))

            raise TimeoutError(f"llama-server did not become ready on port {port}; see {monitor.log_file}")

        warmup(conf)
        print_ready("llm", port=port, args=cmd, profile=conf.name, model=conf.profile.model)
        startup_marker.touch()
    except BaseException:
        kill_process_tree(proc.pid)
        proc.wait(timeout=10)
        raise
    return proc


def main() -> None:
    proc = launch(extra_args=sys.argv[1:], mode=ConsoleTerminalLaunchMode.MERGE)
    wait_for_exit(proc)


if __name__ == "__main__":
    main()
