"""Service settings every launcher shares: modes, generic startup, llama.cpp builds and clients."""

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from scripts.config import paths as config_paths
from scripts.config import project_config as project_cfg
from scripts.config.coding_agents.pi import packages as pi_packages

# - deliberate re-export: consumers read it as cfg.LLAMACPP_PROFILES
from scripts.launchers.llamacpp.llamacpp_profiles import LLAMACPP_BENCHMARK_PROFILES as LLAMACPP_BENCHMARK_PROFILES
from scripts.launchers.llamacpp.llamacpp_profiles import LLAMACPP_PROFILES as LLAMACPP_PROFILES

# --- GENERIC PATHS AND LAUNCH SETTINGS ---


VENV_PYTHON = project_cfg.VENV_DIR / "Scripts" / "python.exe"


class ServiceMode(str, Enum):
    SERVER = "server"
    PROXY = "proxy"


class ConsoleTerminalLaunchMode(str, Enum):
    SPLIT_INDEPENDENT = "split-independent"
    SPLIT_DEPENDENT = "split-dependent"
    MERGE = "merge"


class ExistingServicePolicy(str, Enum):
    KILL = "kill"
    REUSE = "reuse"
    ERROR = "error"


@dataclass
class GenericStartupWarmupSettings:
    attempts: int = 60
    request_timeout_s: float = 15
    retry_interval_s: float = 1


@dataclass
class GenericStartupLaunchSettings:
    console_terminal_mode: ConsoleTerminalLaunchMode = ConsoleTerminalLaunchMode.SPLIT_INDEPENDENT
    existing_service_policy: ExistingServicePolicy = ExistingServicePolicy.KILL
    temp_dir: Path = project_cfg.component("shared").cache_dir / "launch"
    warmup_policy: GenericStartupWarmupSettings = field(default_factory=GenericStartupWarmupSettings)


def _existing_service_policy() -> ExistingServicePolicy:
    """Let a parent process hand a safer policy to launcher workers it spawns."""
    value = os.environ.get("AI_EXISTING_SERVICE_POLICY", ExistingServicePolicy.KILL.value).strip().lower()
    try:
        return ExistingServicePolicy(value)
    except ValueError:
        return ExistingServicePolicy.KILL


LAUNCH = GenericStartupLaunchSettings(existing_service_policy=_existing_service_policy())


@dataclass(kw_only=True)
class GenericStartupServiceSettings:
    mode: ServiceMode
    listen_ip: str
    port: int
    internal_port: int
    enabled: bool = True
    warmup: bool = True


# --- LLAMACPP SETTINGS ---


@dataclass
class LlamacppStartupBuild:
    bin_dir: Path
    extra_args: dict[str, str] = field(default_factory=dict)
    env: dict[str, str | None] = field(default_factory=dict)
    default_profile: str | None = None
    unsupported_server_args: tuple[str, ...] = ()


# - Named llama.cpp builds; selecting one (--llama-cpp-build or
#   ACTIVE_LLAMACPP_BUILD) resolves its dir plus build-specific server args
#   (e.g. spec-decoding flags only the custom build supports)
# - A raw --llama-cpp-dir bypasses extra_args unless it matches one of these dirs
LLAMACPP_BUILDS: dict[str, LlamacppStartupBuild] = {
    "hrx": LlamacppStartupBuild(
        bin_dir=project_cfg.LLAMACPP_FRAMEWORK_DIR / "additions/hrx/runtime",
        extra_args={"device": "HRX0"},
        env={
            "ROCR_VISIBLE_DEVICES": "1",
            "ROCR_USE_PM4": "1",
            "HSA_OVERRIDE_GFX_VERSION": None,
            "IREE_HAL_AMDGPU_LIBHSA_PATH": str(
                project_cfg.LLAMACPP_FRAMEWORK_DIR / "additions/hrx/runtime/hsa-runtime64.dll"
            ),
        },
        default_profile="swift15-hrx",
        unsupported_server_args=("reasoning-effort",),
    ),
    # - v1.0.0 release pin (nightly b12359), kept for A/B against the rolling vulkan build
    "vulkan-1.0.0": LlamacppStartupBuild(bin_dir=project_cfg.LLAMACPP_FRAMEWORK_DIR / "vulkan-1.0.0", extra_args={}),
    "vulkan": LlamacppStartupBuild(bin_dir=project_cfg.LLAMACPP_FRAMEWORK_DIR / "vulkan", extra_args={}),
    "rocm-lemonade": LlamacppStartupBuild(
        bin_dir=project_cfg.LLAMACPP_ROCM_LEMONADE_DIR,
        # - The Ryzen iGPU is ROCm1 and reports system RAM as free VRAM. The backend initializes
        #   every visible device, so it faults while the context is built even when --device limits
        #   tensor placement. Hiding the iGPU at the HIP level is what makes b1375 load; index 0 is
        #   the discrete card in --list-devices order.
        env={"HIP_VISIBLE_DEVICES": "0"},
    ),
    "rocm-rdna": LlamacppStartupBuild(  # went from 34 to 41t/s with adaptive mtp over 4k tokens (swift15), has other issues potentially
        bin_dir=project_cfg.LLAMACPP_FRAMEWORK_DIR / "rdna/build/bin", extra_args={}
    ),
}

# - One llama.cpp default for every use: coding, embeddings and the Kobold external arm all resolve
#   through `llamacpp_build()`, so one build runs unless a use case overrides it.
# - The rolling `vulkan` build is the default from b12590: a 24-text embedding request and a 27B
#   re-prefill both answered 200 on it, which are the two faults that held the v1.0.0 pin.
# - v1.0.0 stays installed as the fallback, and ROCm still collapses past a 64K read
#   ([builds](../config/llamacpp/BUILDS.md)).
LLAMACPP_DEFAULT_BUILD = "vulkan"
# - Per-use overrides; None means "follow the llama.cpp default".
LLAMACPP_CODING_BUILD: str | None = None
LLAMACPP_EMBEDDINGS_BUILD: str | None = None

_BUILD_OVERRIDES: dict[str, str | None] = {"coding": LLAMACPP_CODING_BUILD, "embeddings": LLAMACPP_EMBEDDINGS_BUILD}


def llamacpp_build(use: str = "coding") -> str:
    """The build id a use case runs: its override when set, otherwise the one llama.cpp default."""
    if use not in _BUILD_OVERRIDES:
        raise ValueError(f"Unknown llama.cpp use case: {use}")
    return _BUILD_OVERRIDES[use] or LLAMACPP_DEFAULT_BUILD


LLAMACPP_ACTIVE_CODING_AGENT_PROFILE = "swift15"
# - deferred work: wired so a re-enable is one edit, never selectable by a launcher or a benchmark
LLAMACPP_DEFERRED_PROFILES = frozenset({"swift15-hrx"})
LLAMACPP_DEFERRED_BUILDS = frozenset({"hrx"})


@dataclass(kw_only=True)
class LlamacppStartupServiceSettings(GenericStartupServiceSettings):
    idle_timeout_s: int = 900
    ready_timeout_s: int = 120
    verbosity: int = 4


LLAMACPP_SERVICE = LlamacppStartupServiceSettings(
    mode=ServiceMode.SERVER, listen_ip="127.0.0.1", port=9931, internal_port=9932
)


LLAMACPP_INI_DIR = project_cfg.component("llamacpp").config_dir
# - INI keys are llama-server flags without leading dashes (build_server_args
#   in llamacpp.py re-adds them via build_cli_args)
# - Unknown keys pass straight through and llama-server rejects them

# - llama-server log threshold (`-lv N`): 0 generic, 1 error, 2 warning, 3 info,
#   4 trace, 5 debug; messages above the threshold are dropped
# - 4 records native fit estimates, GPU offload, and buffer allocations for the
#   shared memory report; 3 omits these details in the installed build

# - Fixed server flags (keys carry their dashes; see build_cli_args)
# - Flag-only switches are True-valued entries, and build_cli_args emits them bare
# "--n-cpu-moe": 13
# CLI flags; request-related flags establish initial server defaults.
LLAMACPP_SERVER_ARGS = {
    # "--device": "ROCm0",
    "--load-mode": "none",
    "-fa": "on",
    "--reasoning-preserve": True,
    "--reasoning-effort": "medium",
}

# - llama-server authenticates nothing, but clients that speak the OpenAI API
#   refuse to send a request without a key; every local client resolves this
#   same name to this same ignored value
LLAMACPP_API_KEY_ENV = "LLAMACPP_API_KEY"
LLAMACPP_API_KEY_NOOP = "noop"

# - what llama-server binds when a proxy owns the client-facing port


def llama_base_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{LLAMACPP_SERVICE.port if port is None else port}/v1"


# - "server" = llama-server.exe on `port`, clients talk to it directly
# - "proxy"  = llamacpp_proxy.py on `port`, llama-server on `internal-port`:
#   the proxy answers /health and /v1/models from configuration without loading
#   anything, starts the server on the first request that needs the model, and
#   stops it again after `idle-timeout-s` with nothing in flight


# --- coding clients ---


@dataclass
class SharedStartupRequestCodingClientSettings:
    entry: Path
    agent_dir: Path
    node_cmd: str = "node"
    packages: tuple[Path, ...] = ()
    additional_tools: tuple[str, ...] = ()
    cli_args: tuple[str, ...] = ()
    extensions: tuple[Path, ...] = pi_packages.local_extensions()

    model: str = "qwen3.8-27b"


PI_CLIENT = SharedStartupRequestCodingClientSettings(
    entry=pi_packages.package_path(pi_packages.manifest()["core_package"]) / "dist" / "cli.js",
    agent_dir=project_cfg.component("coding_agents/pi").state_dir / "agent",
    packages=pi_packages.package_paths(),
    additional_tools=tuple(pi_packages.manifest()["default_tools"]),
    cli_args=pi_packages.cli_args(),
)


def _strata_profile() -> tuple[Path, str]:
    """Tracked profile file plus the model name recorded inside it."""
    folder = project_cfg.component("strata").config_dir
    path = folder / "prefill.json"
    fallback = "swift-1.5-iq2_xs-prefill"
    try:
        return path, str(config_paths.load_json(path).get("model_name") or fallback)
    except (OSError, ValueError):
        return path, fallback


_STRATA_CONFIG_PATH, _STRATA_MODEL_NAME = _strata_profile()


@dataclass
class StrataStartupServiceSettings:
    control_dir: Path = project_cfg.component("strata").framework_dir / "control"
    # - Profile file is the tracked default; its own model_name decides which saved runtime the launcher targets
    config_path: Path = _STRATA_CONFIG_PATH
    model: str = "swift-iq2_xs"
    model_name: str = _STRATA_MODEL_NAME
    port: int = 18501
    startup_timeout_s: float = 180


STRATA_SERVICE = StrataStartupServiceSettings()


LITTLECODER_CLIENT = SharedStartupRequestCodingClientSettings(
    entry=project_cfg.FRAMEWORKS_DIR
    / "coding_agents"
    / "littlecoder"
    / "node_modules"
    / "little-coder"
    / "bin"
    / "little-coder.mjs",
    agent_dir=project_cfg.component("coding_agents/littlecoder").state_dir / "agent",
)


OHMYPI_CLIENT = SharedStartupRequestCodingClientSettings(
    entry=project_cfg.FRAMEWORKS_DIR / "coding_agents" / "ohmypi" / "omp-windows-x64.exe",
    agent_dir=project_cfg.component("coding_agents/ohmypi").state_dir / "agent",
)
NANOCODER_CLIENT = SharedStartupRequestCodingClientSettings(
    entry=project_cfg.FRAMEWORKS_DIR
    / "coding_agents"
    / "nanocoder"
    / "node_modules"
    / "@nanocollective"
    / "nanocoder"
    / "dist"
    / "cli.js",
    agent_dir=project_cfg.component("coding_agents/nanocoder").state_dir,
)


# --- DeepSeek Harness (optional coding client) ---


# - The harness ships @deepseek-ai/dsh-llm-pi-ai mounted dormant: it registers
#   no provider routes until a `providers` section names them. DSH_* below is
#   the local llama.cpp route that makes the running llama-server selectable
#   from the harness model picker, alongside the DeepSeek routes
# - default_context_window mirrors profiles.ContextSize.K96, the ctx-size the
#   LLAMACPP_PROFILES entries launch with
@dataclass
class DeepseekStartupRequestClientSettings:
    home: Path = project_cfg.component("coding_agents/deepseek").state_dir
    exe: Path = project_cfg.FRAMEWORKS_DIR / "coding_agents" / "deepseek" / "DeepSeek Harness.exe"
    profile: str = "desktop"
    route: str = "llamacpp"
    display_name: str = "llama.cpp (local)"
    api_key_env: str = LLAMACPP_API_KEY_ENV
    default_context_window: int = 98304
    default_max_tokens: int = 32768
    # - the idle timeout covers the gap before the first token, which is where a
    #   lazily started server spends its whole load; the adapter's own 5 minute
    #   default is not enough headroom for a cold 27B
    stream_idle_timeout_ms: int = 600000

    def patch_path(self, profile: str | None = None) -> Path:
        return self.home / "profiles" / (profile or self.profile) / "cordis.patch.yml"


DEEPSEEK_CLIENT = DeepseekStartupRequestClientSettings()
