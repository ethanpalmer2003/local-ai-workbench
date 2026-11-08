"""Shared paths and environment setup for the AI project.

- Llama build selection belongs in `launcher_config.py`
- This module only owns project paths, model dirs, HF env vars
"""

import os
from dataclasses import dataclass
from pathlib import Path

# This file lives in the project's shared config package.
# - three levels up from scripts/config reaches the repository root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ============================================================
# CORE PATHS
# ============================================================

DATA_DIR = BASE_DIR / "data"
FRAMEWORKS_DIR = BASE_DIR / "frameworks"
BENCHMARK_TOOLS_DIR = FRAMEWORKS_DIR / "benchmarks"
SCRIPTS_DIR = BASE_DIR / "scripts"
BAT_DIR = BASE_DIR / "bat"
ENV_FILE = SCRIPTS_DIR / ".env"

INPUT_DIR = DATA_DIR / "input"
VOICES_DIR = DATA_DIR / "voices"
OUTPUT_DIR = Path(os.environ.get("AI_OUTPUT_DIR") or DATA_DIR / "output")
TESTS_DIR = SCRIPTS_DIR / "tests"
CONFIG_DIR = SCRIPTS_DIR / "config"
STATE_DIR = SCRIPTS_DIR / "state"
GENERATED_DIR = STATE_DIR / "generated"
LOGS_DIR = Path(os.environ.get("AI_LOGS_DIR") or STATE_DIR / "logs")
CACHE_DIR = STATE_DIR / "cache"
TEST_CASES_DIR = TESTS_DIR / "cases"
TEST_OUTPUT_DIR = TESTS_DIR / "output"

# ============================================================
# ENVIRONMENT LOADING
# ============================================================

# - Load env vars at import time so all scripts can use config.HF_TOKEN
try:
    from dotenv import load_dotenv

    load_dotenv(str(ENV_FILE))
except ImportError:
    pass  # - dotenv not installed, rely on system env vars

HF_TOKEN = os.environ.get("HF_TOKEN")
# - local service credentials stay in scripts/.env, never in tracked config
KOBOLD_ADMIN_PASSWORD = os.environ.get("KOBOLD_ADMIN_PASSWORD") or ""


# ============================================================
# HUGGINGFACE CACHE
# ============================================================

HF_HOME_DIR = DATA_DIR / "huggingface"  # HF cache root (HF_HUB_DIR env var)
HF_MODELS_DIR = HF_HOME_DIR / "models"  # Downloaded model files root
CHAT_TEMPLATES_DIR = HF_HOME_DIR / "chat-templates"

# - Set HF env vars BEFORE any huggingface_hub imports
# - HF_HOME is the permanent Windows env var; HF_HUB_DIR is set here for runtime
os.environ["HF_HOME"] = str(HF_HOME_DIR)
os.environ["HF_HUB_DIR"] = str(HF_HOME_DIR)
# - The hub cache must stay out of HF_MODELS_DIR: component model folders are the only
#   registered children there, and a cache root would read as an unowned model folder
os.environ["HF_HUB_CACHE"] = str(HF_HOME_DIR / "hub")


# ============================================================
# PER-FRAMEWORK PATHS
# (model dirs, install dirs, and exe paths grouped together per framework)
# ============================================================


@dataclass(frozen=True)
class ComponentPaths:
    key: str
    framework_override: str | None = None
    models_override: str | None = None
    state_in_framework: str | None = None
    models_in_state: str | None = None

    @property
    def framework_dir(self) -> Path:
        return FRAMEWORKS_DIR / (self.framework_override or self.key)

    @property
    def models_dir(self) -> Path:
        if self.models_in_state:
            return self.state_dir / self.models_in_state
        return DATA_DIR / self.models_override if self.models_override else HF_MODELS_DIR / self.key

    @property
    def launcher_dir(self) -> Path:
        return SCRIPTS_DIR / "launchers" / self.key

    @property
    def config_dir(self) -> Path:
        return CONFIG_DIR / self.key

    @property
    def state_dir(self) -> Path:
        if self.state_in_framework:
            return self.framework_dir / self.state_in_framework
        return STATE_DIR / self.key

    @property
    def logs_dir(self) -> Path:
        return LOGS_DIR / self.key

    @property
    def cache_dir(self) -> Path:
        return CACHE_DIR / self.key

    @property
    def generated_dir(self) -> Path:
        return GENERATED_DIR / self.key

    @property
    def test_cases_dir(self) -> Path:
        return TEST_CASES_DIR / self.key

    @property
    def test_ui_dir(self) -> Path:
        return TESTS_DIR / "ui" / self.key

    def batch_dir(self, operation: str) -> Path:
        return BAT_DIR / operation / self.key


COMPONENTS = {
    key: ComponentPaths(key)
    for key in (
        "asr",
        "asr/whispercpp",
        "asr/parakeetcpp",
        "asr/handy",
        "asr/shared",
        "asr/nemo-speechcpp",
        "asr/speechcpp",
        "asr/crispasr",
        "asr/funasr",
        "audiocpp",
        "audiocpp/additions/espeak-ng",
        "audiocpp/additions/mecab",
        "avalon",
        "tts/piper",
        "tts/sherpa-onnx",
        "tts/shared",
        "llamacpp",
        "koboldcpp",
        "sdcpp",
        "coding_agents/commandcode",
        "coding_agents/commandcode-desktop",
        "coding_agents/pi",
        "coding_agents/deepseek",
        "coding_agents/ohmypi",
        "coding_agents/littlecoder",
        "coding_agents/nanocoder",
        "coding_agents/shared",
        "shared",
        "localai",
        "text-generation-webui",
        "benchmarks",
    )
}
COMPONENTS.update(
    {
        "llamacpp": ComponentPaths("llamacpp", models_override="huggingface/models/llms"),
        # - model servers share one root: they all wrap other engines rather than being one themselves
        "koboldcpp": ComponentPaths(
            "koboldcpp",
            framework_override="model_servers/koboldcpp",
            models_override="huggingface/models/llms/character_models",
        ),
        "lemonade_server": ComponentPaths("lemonade_server", framework_override="model_servers/lemonade_server"),
        "localai": ComponentPaths("localai", framework_override="model_servers/LocalAI"),
        "text-generation-webui": ComponentPaths(
            "text-generation-webui", framework_override="model_servers/text-generation-webui"
        ),
        "asr/handy": ComponentPaths("asr/handy", state_in_framework="app/Data", models_in_state="models"),
        "asr/llamacpp": ComponentPaths("asr/llamacpp", framework_override="llamacpp"),
        "asr/koboldcpp": ComponentPaths("asr/koboldcpp", framework_override="model_servers/koboldcpp"),
        "asr/audiocpp": ComponentPaths("asr/audiocpp", framework_override="audiocpp"),
        "asr/sherpa-onnx": ComponentPaths("asr/sherpa-onnx", framework_override="tts/sherpa-onnx"),
        "coding_agents/commandcode-desktop": ComponentPaths(
            "coding_agents/commandcode-desktop", framework_override="coding_agents/Command Code"
        ),
        "comfyui": ComponentPaths("comfyui", models_override="videogen"),
        # - benchmark corpora are downloaded reference audio, not model weights
        "benchmarks": ComponentPaths("benchmarks", models_override="benchmarks"),
        "strata": ComponentPaths("strata", framework_override="Strata"),
    }
)
MODEL_ALIASES: dict[str, str] = {}
# App-managed weights not represented by individual download entries.
MODEL_DISCOVERY_SUBDIRS = {"strata": "models", "asr/handy": ""}


def component(key: str) -> ComponentPaths:
    return COMPONENTS[key]


def framework_install_dir(name: str) -> Path:
    owners = [key for key in COMPONENTS if name == key or name.startswith(key + "/")]
    if not owners:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe framework path: {name}")
        return FRAMEWORKS_DIR / relative
    key = max(owners, key=len)
    suffix = name[len(key) :].lstrip("/")
    return component(key).framework_dir / suffix


def model_destination(key: str, filename: str) -> str:
    return (component(key).models_dir.relative_to(DATA_DIR) / filename).as_posix()


ASR_FRAMEWORKS_DIR = component("asr").framework_dir
COMFYUI_FRAMEWORK_DIR = component("comfyui").framework_dir
COMFYUI_ROCM_DIR = COMFYUI_FRAMEWORK_DIR / "rocm"
COMFYUI_MODELS_DIR = component("comfyui").models_dir


# --- audiocpp (AUDIOCPP / audio generation) ---
AUDIOCPP_FRAMEWORK_DIR = component("audiocpp").framework_dir
AUDIOCPP_MODELS_DIR = component("audiocpp").models_dir
AUDIOCPP_ROCM_DIR = AUDIOCPP_FRAMEWORK_DIR / "rocm"
AUDIOCPP_ROCM_BIN_DIR = AUDIOCPP_ROCM_DIR
AUDIOCPP_ROCM_LEGACY_DIR = AUDIOCPP_FRAMEWORK_DIR / "additions/rocm/7.1-old"
AUDIOCPP_ROCM_BUILD_DIR = AUDIOCPP_FRAMEWORK_DIR / "additions/rocm/therock-10.2-hip-7.17-gfx1101"
AUDIOCPP_VULKAN_DIR = AUDIOCPP_FRAMEWORK_DIR / "vulkan"
AUDIOCPP_VULKAN_BIN_DIR = AUDIOCPP_VULKAN_DIR
AUDIOCPP_BIN_DIR = AUDIOCPP_VULKAN_BIN_DIR
AUDIOCPP_SERVER_EXE = AUDIOCPP_BIN_DIR / "audiocpp_server.exe"
AUDIOCPP_CLI_EXE = AUDIOCPP_BIN_DIR / "audiocpp_cli.exe"

# --- avalon (llama.cpp fork for Qwen3.8-Flash-Next; benchmark engine) ---
AVALON_FRAMEWORK_DIR = component("avalon").framework_dir
AVALON_BIN_DIR = AVALON_FRAMEWORK_DIR / "build" / "bin"
AVALON_SERVER_EXE = AVALON_BIN_DIR / "llama-server.exe"
AVALON_MODELS_DIR = component("avalon").models_dir
AVALON_MTP_GGUF = AVALON_MODELS_DIR / "mtp" / "mtp-Qwen3.8-Flash-Next-shared-IQ3K-IQ4NL-FR65k.gguf"

# --- strata (app-managed GGUF weights, served by the Strata engine or Avalon) ---
STRATA_MODELS_DIR = component("strata").models_dir

# --- koboldcpp (GGUF storage only - no install dir/exe tracked here) ---
KOBOLDCPP_FRAMEWORK_DIR = component("koboldcpp").framework_dir
KOBOLDCPP_MODELS_DIR = component("koboldcpp").models_dir

# --- ASR models (speech recognition) ---
ASR_MODELS_DIR = component("asr").models_dir

# --- llamacpp (LLM inference) ---
# - Build dir selection lives in launcher_config.py (LLAMACPP_BUILDS /
#   ACTIVE_LLAMACPP_BUILD) - single place deciding the active build
# - Only the model dir is tracked here
LLAMACPP_FRAMEWORK_DIR = component("llamacpp").framework_dir
LLAMACPP_SPEECH_UI_DIR = LLAMACPP_FRAMEWORK_DIR / "additions/speech-ui"
HANDY_APP_DIR = component("asr/handy").framework_dir / "app"
LLMS_MODELS_DIR = component("llamacpp").models_dir
LLMS_CODING_MODELS_DIR = LLMS_MODELS_DIR / "coding_models"
LLMS_MULTILINGUAL_MODELS_DIR = LLMS_MODELS_DIR / "multilingual_models"
LLMS_CHARACTER_MODELS_DIR = component("koboldcpp").models_dir

# --- sdcpp (Stable Diffusion) ---
SDCPP_FRAMEWORK_DIR = component("sdcpp").framework_dir
SDCPP_MODELS_DIR = component("sdcpp").models_dir
SDCPP_ROCM_DIR = SDCPP_FRAMEWORK_DIR / "rocm"
SDCPP_VULKAN_DIR = SDCPP_FRAMEWORK_DIR / "vulkan"
SDCPP_ROCM_SDK_BIN_DIR = DATA_DIR / "ROCm" / "therock-dist-windows-gfx110X-all-10.2.0a20260927" / "bin"


# ============================================================
# DIRECTORY INITIALIZATION
# ============================================================


def ensure_project_directories() -> None:
    """Create the standard project directories when a command needs them.

    - mkdir(parents=True, exist_ok=True) for each core dir
    """
    for directory in (
        DATA_DIR,
        FRAMEWORKS_DIR,
        SCRIPTS_DIR,
        INPUT_DIR,
        OUTPUT_DIR,
        HF_HOME_DIR,
        HF_MODELS_DIR,
        CHAT_TEMPLATES_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
