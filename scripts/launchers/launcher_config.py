import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import cast

from scripts.config import models as model_cfg
from scripts.config import overlay_inputs as inputs
from scripts.config import paths as config_paths
from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server as audio_cfg
from scripts.config.coding_agents.pi import packages as pi_packages

# - deliberate re-export: consumers read it as cfg.LLAMACPP_PROFILES
from scripts.launchers.llamacpp.llamacpp_profiles import LLAMACPP_PROFILES as LLAMACPP_PROFILES

# ============================================================
# GENERIC PATHS AND LAUNCH SETTINGS
# ============================================================


VENV_PYTHON = project_cfg.SCRIPTS_DIR / ".venv" / "Scripts" / "python.exe"


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


# ============================================================
# LLAMACPP SETTINGS
# ============================================================


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
    "rocm-stock": LlamacppStartupBuild(bin_dir=project_cfg.LLAMACPP_FRAMEWORK_DIR / "rocm/stock", extra_args={}),
    "vulkan": LlamacppStartupBuild(bin_dir=project_cfg.LLAMACPP_FRAMEWORK_DIR / "vulkan", extra_args={}),
    "rocm-lemonade": LlamacppStartupBuild(bin_dir=project_cfg.LLAMACPP_ROCM_LEMONADE_DIR, extra_args={}),
    "rocm-rdna": LlamacppStartupBuild(  # went from 34 to 41t/s with adaptive mtp over 4k tokens (swift15), has other issues potentially
        bin_dir=project_cfg.LLAMACPP_FRAMEWORK_DIR / "rdna/build/bin", extra_args={}
    ),
}

LLAMACPP_ACTIVE_BUILD = "rocm-lemonade"

LLAMACPP_ACTIVE_CODING_AGENT_PROFILE = "swift15"


@dataclass(kw_only=True)
class LlamacppStartupServiceSettings(GenericStartupServiceSettings):
    idle_timeout_s: int = 900
    ready_timeout_s: int = 120
    verbosity: int = 4


LLAMACPP_SERVICE = LlamacppStartupServiceSettings(
    mode=ServiceMode.SERVER, listen_ip="127.0.0.1", port=9931, internal_port=9932
)


LLAMACPP_INI_DIR = project_cfg.component("llamacpp").config_dir
LLAMACPP_JINJA_DIR = LLAMACPP_INI_DIR / "jinja"
# - INI keys are llama-server flags without leading dashes (build_server_args
#   in llamacpp.py re-adds them via build_cli_args)
# - Unknown keys pass straight through and llama-server rejects them

# - llama-server log threshold (`-lv N`): 0 generic, 1 error, 2 warning, 3 info,
#   4 trace, 5 debug; messages above the threshold are dropped
# - 4 records native fit estimates, GPU offload, and buffer allocations for the
#   shared memory report; 3 omits these details in the installed build

# - Fixed server flags (keys carry their dashes; see build_cli_args)
# - Flag-only switches are True-valued entries - build_cli_args emits them bare
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

    @property
    def credentials_path(self) -> Path:
        return self.home / ".credentials.yaml"


DEEPSEEK_CLIENT = DeepseekStartupRequestClientSettings()


# ============================================================
# SHARED TTS REQUEST SETTINGS (AUDIOCPP, KOBOLD LITE, TEST UI)
# ============================================================


class SharedTtsStreamingRequestTextMode(str, Enum):
    WHOLE = "whole"
    NARRATION = "narration"
    NARRATION_ON = "narration_on"
    BOUNDED = "bounded"
    SENTENCES = "sentences"


class SharedTtsStreamingRequestTransport(str, Enum):
    HTTP = "audio"
    SSE = "sse"


class SharedTtsStreamingRequestChunkPolicy(str, Enum):
    GROW = "grow"
    FIXED = "fixed"


@dataclass
class SharedTtsStreamingRequestSettings:
    # Browser playback and text submission; these fields are not sent to audio.cpp.
    playback_buffer_ms: int = 2000
    pcm_sample_rate: int = 24000
    text_mode: SharedTtsStreamingRequestTextMode = SharedTtsStreamingRequestTextMode.NARRATION
    text_limit: int = 400
    # Sent to audio.cpp with each streaming request.
    transport: SharedTtsStreamingRequestTransport = SharedTtsStreamingRequestTransport.HTTP
    # - None uses the server's default; support depends on the installed build.
    stream_frames_per_event: int | None = None
    stream_lookahead_margin: int | None = None
    stream_chunk_policy: SharedTtsStreamingRequestChunkPolicy | None = None


# ============================================================
# KOBOLDCPP SETTINGS
# ============================================================


class KoboldcppSpeechStartupEngine(str, Enum):
    CONFIGURED = "configured"
    KOKORO_INTERNAL = "kokoro-internal"
    KOKORO_AUDIOCPP = "kokoro-audiocpp"


class AsrStartupEngine(str, Enum):
    AUDIOCPP = "audiocpp-nemotron"
    NEMO = "nemo-nemotron"
    PARAKEET_STREAM = "parakeetcpp-nemotron-cpu"
    SPEECHCPP = "speechcpp-qwen-0.6b"
    PARAKEET_V3 = "parakeetcpp-v3"
    EMBEDDED = "embedded"
    WHISPER_VULKAN = "whisper-vulkan"
    QWEN3_ASR = "qwen3-asr"
    GEMMA_AUDIO = "gemma-audio"
    GEMMA_KOBOLD = "gemma-kobold"
    COHERE = "audiocpp-cohere"
    GRANITE = "granite-audio"


class TtsQualityClass(str, Enum):
    """What a profile needs from speech output; a framework that cannot meet it is not an option."""

    NONE = "none"
    FAST_MULTILINGUAL = "fast-multilingual"
    VOICE_DESIGN = "voice-design"


@dataclass(frozen=True)
class ProfileRequirements:
    """One workflow profile: the parts a framework must provide to be considered at all."""

    tts: TtsQualityClass
    asr: bool
    agent: bool
    llm_role: str


# - The three profiles this repository runs. The character profile needs voice-design speech, language needs ASR plus
#   fast multilingual speech, and coding needs an agent in front of the inference engine.
PROFILE_REQUIREMENTS = {
    "character": ProfileRequirements(TtsQualityClass.VOICE_DESIGN, asr=False, agent=False, llm_role="mid"),
    "language": ProfileRequirements(TtsQualityClass.FAST_MULTILINGUAL, asr=True, agent=False, llm_role="lightweight"),
    "coding": ProfileRequirements(TtsQualityClass.NONE, asr=False, agent=True, llm_role="coding"),
}

# - Speech output each framework can actually provide; Lemonade has kokoro only and no Breeze,
#   which is why it is a language profile and never a character one.
FRAMEWORK_TTS_CLASSES = {
    "koboldcpp": TtsQualityClass.VOICE_DESIGN,
    "audiocpp": TtsQualityClass.VOICE_DESIGN,
    "lemonade_server": TtsQualityClass.FAST_MULTILINGUAL,
    "llamacpp": TtsQualityClass.NONE,
}


def tts_class_for(model: str) -> TtsQualityClass:
    """The speech class a TTS model provides, read from its catalog label."""
    if "breeze" in model:
        return TtsQualityClass.VOICE_DESIGN
    if "kokoro" in model:
        return TtsQualityClass.FAST_MULTILINGUAL
    return TtsQualityClass.NONE


def model_fits_profile(profile: str, tts_model: str) -> bool:
    """True when the TTS model meets the profile's speech requirement."""
    required = PROFILE_REQUIREMENTS[profile].tts
    return required is TtsQualityClass.NONE or tts_class_for(tts_model) is required


def require_profile_fit(profile: str, tts_model: str) -> None:
    """Refuse a stack the profile cannot be served by, instead of discovering it at runtime."""
    if not model_fits_profile(profile, tts_model):
        required = PROFILE_REQUIREMENTS[profile].tts
        provided = tts_class_for(tts_model)
        raise ValueError(f"{tts_model} provides {provided.value} speech; the {profile} profile needs {required.value}")


@dataclass(frozen=True)
class SpeechWorkflowDefaults:
    """One workspace workflow's default speech stack, declared in a single place."""

    profile: str
    framework: str
    asr_engine: AsrStartupEngine | None
    llm_model: str
    tts_model: str
    tts_voice: str
    clone_voice: bool


# - A default may be replaced from the overlay, so the profile requirement is checked where a
#   framework is selected for a profile (require_profile_fit), not on every dataclass change.


# - Kokoro TTS packages: the selected package is the single source of the practice TTS default.
KOKORO_TTS_PACKAGES = {
    "small": "audiocpp/kokoro-audiocpp-q8_0",
    "multilingual": "audiocpp/kokoro-audiocpp-multilingual-q8_0",
}
DEFAULT_KOKORO_PACKAGE = "multilingual"


# - KOBOLD_CHAT: Rocinante chat, Breeze voice-design TTS through the AudioCpp proxy, no external ASR.
#   Design needs no reference clip, so the default voice comes from the tone instruction.
# - A voice id from the overlay's defaults.json enables cloning; without one, Breeze uses its own default.
_CHAT_TTS_VOICE: str = inputs.setting("chat.tts.voice", inputs.default_voice())
KOBOLD_CHAT = SpeechWorkflowDefaults(
    profile="character",
    framework="koboldcpp",
    asr_engine=None,
    llm_model=inputs.setting("chat.llm", "koboldcpp/TheDrummer_Rocinante-X-12B-v1-IQ4_XS"),
    tts_model=inputs.setting("chat.tts.model", "audiocpp/breeze-tts-2-q4_0"),
    tts_voice=_CHAT_TTS_VOICE,
    clone_voice=bool(_CHAT_TTS_VOICE),
)
# - Language practice: Gemma chat, Kokoro TTS without cloning, Qwen3-ASR recognition.
#   Qwen reads all four practice languages with the lowest pooled error on the pinned corpus;
#   Whisper Vulkan stays the faster alternate. AudioCpp Nemotron misheard English and could not
#   transcribe Japanese at all (notes/TODO.md records that engine's failure).
LANGUAGE_PRACTICE = SpeechWorkflowDefaults(
    profile="language",
    framework="llamacpp",
    asr_engine=AsrStartupEngine.QWEN3_ASR,
    llm_model="llamacpp/gemma-4-E4B-it-Q4_0",
    tts_model=KOKORO_TTS_PACKAGES[DEFAULT_KOKORO_PACKAGE],
    tts_voice="af_heart",
    clone_voice=False,
)


@dataclass
class SharedAsrStartupServiceSettings:
    engine: AsrStartupEngine = LANGUAGE_PRACTICE.asr_engine or AsrStartupEngine.AUDIOCPP
    host: str = "127.0.0.1"
    port: int = 8895


ASR_SERVICE = SharedAsrStartupServiceSettings()


@dataclass
class ResidentAsrStartupSettings:
    profile: str
    port: int


SPEECHCPP_ASR = ResidentAsrStartupSettings("speechcpp", 8897)
COHERE_ASR = ResidentAsrStartupSettings("audiocpp-cohere", 8901)
NEMO_SPEECHCPP_ASR = ResidentAsrStartupSettings("nemo-speechcpp", 8899)
PARAKEETCPP_STREAM_ASR = ResidentAsrStartupSettings("parakeetcpp-nemotron-streaming", 8900)
PARAKEETCPP_STREAM_LIBRARY = project_cfg.component("asr/parakeetcpp").framework_dir / "cpu-stream/parakeet.dll"
PARAKEETCPP_V3_ASR = ResidentAsrStartupSettings("parakeetcpp-v3", 8898)


@dataclass
class WhispercppAsrStartupRequestSettings:
    exe: Path = project_cfg.component("asr/whispercpp").framework_dir / "vulkan-build/whisper-server.exe"
    model: Path = model_cfg.path("asr/whispercpp/large-v3-turbo-q5_0")
    port: int = 8890
    threads: int = 4
    device: int = 0
    flash_attention: bool = True
    language: str = "en"


WHISPERCPP_ASR = WhispercppAsrStartupRequestSettings()


@dataclass
class ParakeetcppAsrStartupRequestSettings:
    build: str = "vulkan"
    model: Path = model_cfg.path("asr/parakeetcpp/parakeet-tdt-ctc-110m-q8_0")
    vad_model: Path = model_cfg.path("asr/parakeetcpp/silero-vad-f16")
    vad: bool = True
    threads: int = 4
    device: str = "Vulkan0"

    def executable(self, build: str) -> Path:
        return project_cfg.component("asr/parakeetcpp").framework_dir / build / "parakeet-cli.exe"


PARAKEETCPP_ASR = ParakeetcppAsrStartupRequestSettings()


@dataclass
class Qwen3AsrStartupRequestSettings:
    build: str = "vulkan"
    device: str = "Vulkan0"
    model: Path = model_cfg.path("asr/llamacpp/qwen3-asr-1.7b-q8_0")
    mmproj: Path = model_cfg.path("asr/llamacpp/qwen3-asr-1.7b-mmproj-q8_0")
    port: int = 8891
    context_size: int = 8192
    threads: int = 4
    max_tokens: int = 512

    @property
    def exe(self) -> Path:
        return LLAMACPP_BUILDS[self.build].bin_dir / "llama-server.exe"


QWEN3_ASR = Qwen3AsrStartupRequestSettings()


@dataclass
class GemmaAudioAsrStartupRequestSettings:
    build: str = "vulkan"
    model: Path = model_cfg.path(LANGUAGE_PRACTICE.llm_model)
    mmproj: Path = model_cfg.path("llamacpp/gemma-4-E4B-it-mmproj-q8_0")
    port: int = 8892
    context_size: int = 8192
    threads: int = 4
    max_tokens: int = 512
    max_audio_seconds: float = 30.0

    @property
    def exe(self) -> Path:
        return LLAMACPP_BUILDS[self.build].bin_dir / "llama-server.exe"


GEMMA_AUDIO_ASR = GemmaAudioAsrStartupRequestSettings()
GRANITE_AUDIO_ASR = GemmaAudioAsrStartupRequestSettings(
    model=model_cfg.path("asr/llamacpp/granite-speech-5.0-2b-q8_0"),
    mmproj=model_cfg.path("asr/llamacpp/granite-speech-5.0-2b-mmproj-f16"),
    port=8902,
)


@dataclass
class LlamacppLanguagePracticeStartupSettings:
    host: str = "127.0.0.1"
    port: int = 5003
    internal_port: int = 5004


LLAMACPP_PRACTICE = LlamacppLanguagePracticeStartupSettings()


@dataclass
class SharedKokoroStartupRequestSettings:
    koboldcpp_model: Path = model_cfg.path("audiocpp/kokoro-kobold-q4")
    audiocpp_package: str = DEFAULT_KOKORO_PACKAGE  # 'small' retains the compact package.
    voice: str = LANGUAGE_PRACTICE.tts_voice
    language: str = "en-us"
    threads: int = 5
    espeak_dir: Path = project_cfg.component("audiocpp/additions/espeak-ng").framework_dir / "eSpeak NG"
    mecab_library: Path = project_cfg.component("audiocpp/additions/mecab").framework_dir / "libmecab.dll"

    @property
    def audiocpp_model(self) -> Path:
        return model_cfg.path(KOKORO_TTS_PACKAGES[self.audiocpp_package])


KOKORO_TTS = SharedKokoroStartupRequestSettings()


@dataclass(frozen=True)
class AudiocppVadSettings:
    server_port: int = 8894
    model: Path = model_cfg.path("audiocpp/silero-vad")
    threshold: float = 0.5
    silence_ms: int = 700
    pre_roll_ms: int = 300
    sample_rate: int = 16000
    frame_samples: int = 512
    max_turn_seconds: float = 30.0


AUDIOCPP_VAD = AudiocppVadSettings()


@dataclass
class KoboldcppStartupServiceSettings:
    exe: Path = project_cfg.KOBOLDCPP_FRAMEWORK_DIR / "koboldcpp-nocuda.exe"
    config: Path = project_cfg.component("koboldcpp").config_dir / "kobold_external_stack.kcpps"
    model: str = KOBOLD_CHAT.llm_model
    speech_engine: KoboldcppSpeechStartupEngine = KoboldcppSpeechStartupEngine.CONFIGURED
    transcription_engine: AsrStartupEngine = KOBOLD_CHAT.asr_engine or AsrStartupEngine.EMBEDDED
    streaming_ui: bool = True
    streaming_ui_port: int = 5001
    streaming_ui_host: str = "0.0.0.0"
    streaming_ui_path: str = ""


KOBOLDCPP_SERVICE = KoboldcppStartupServiceSettings()

# - Admin password stays out of the tracked config and out of service snapshots; set KOBOLD_ADMIN_PASSWORD in scripts/.env.
KOBOLDCPP_ADMIN_PASSWORD = project_cfg.KOBOLD_ADMIN_PASSWORD


# Native Kobold process/model configuration.
KOBOLDCPP_KCPPS_ARGS = {
    "port": 5002,
    "port_param": 5002,
    "host": "127.0.0.1",
    "contextsize": 16384,
    "threads": 5,
    "usevulkan": [0],
    "quantkv": "q8_0",
    "reasoningeffort": "none",
    "splitmode": "layer",
    "whispermodel": str(model_cfg.path("asr/whispercpp/large-v3-turbo-q5_0")),
}

# - The port the server listens on; typed so callers need not narrow the kcpps mapping
KOBOLDCPP_PORT: int = cast(int, KOBOLDCPP_KCPPS_ARGS["port"])

# - KoboldCpp chat allowlist, in the canonical registry-label namespace; paths come from the registry.
#   The character weights sit in the private overlay, so a clone without it keeps the tracked model.
KOBOLDCPP_CHAT_LABELS = (
    "llamacpp/gemma-4-E4B-it-Q4_0",
    "koboldcpp/TheDrummer_Rocinante-X-12B-v1-IQ4_XS",
    "koboldcpp/TheDrummer_Snowpiercer-15B-v4-IQ4_XS",
    "koboldcpp/TheDrummer_Cydonia-24B-v4.3-IQ3_XXS",
    "koboldcpp/TheDrummer_Orion-26B-A4B-v1.1-IQ3_XXS",
)
KOBOLDCPP_MODELS = {
    label: model_cfg.path(label)
    for label in KOBOLDCPP_CHAT_LABELS
    if label in {model.label for model in model_cfg.MODELS}
}


def kobold_chat_model_label() -> str:
    """The configured chat model, or the first allowed one when the private weights are absent."""
    return KOBOLDCPP_SERVICE.model if KOBOLDCPP_SERVICE.model in KOBOLDCPP_MODELS else next(iter(KOBOLDCPP_MODELS))


def kobold_chat_model_path() -> Path:
    return KOBOLDCPP_MODELS[kobold_chat_model_label()]


# 	Vulkan0 (GPU)	Vulkan_Host (CPU)
# moecpu=1	11590.28 MiB	906.12 MiB
# moecpu=2	11215.93 MiB	1280.46 MiB
KOBOLDCPP_MODEL_KCPPS_OVERRIDES = {
    "koboldcpp/TheDrummer_Orion-26B-A4B-v1.1-IQ3_XXS": {"moecpu": 10, "usevulkan": [0], "gpulayers": 30}
}


# ============================================================
# AUDIOCPP (AUDIOCPP TTS + STT) SETTINGS
# ============================================================


# --- core: applies in both "server" and "proxy" mode ---


# - "server" = audiocpp_server.exe only (no wrapping)
# - "proxy"  = audiocpp_server.exe + model/voice-validating proxy (audiocpp_proxy.py)
class AudiocppModel(str, Enum):
    FISH_DRAMA3_Q2 = "audiocpp/fish-drama3-q2"
    BREEZE_TTS = "audiocpp/breeze-tts-2-q4_0"
    BREEZE_DESIGN = "audiocpp/breeze-tts-2-q4_0-design"
    MING3_TTS = "audiocpp/ming3-tts-0.5b-q8_0"
    MING3_AUDIO = "audiocpp/ming3-audio-tiny-q4_k"


# - Both entries load the same weights; only the default task differs.
BREEZE_MODELS = frozenset({AudiocppModel.BREEZE_TTS.value, AudiocppModel.BREEZE_DESIGN.value})


# - Voice ids come from the local input overlay (`scripts/config/overlay_inputs.py`); the repo ships none.
#   A VoiceId keeps the old `.value` call sites working now that the enum is gone.
class VoiceId(str):
    @property
    def value(self) -> str:
        return str(self)


DEFAULT_AUDIOCPP_PROXY_VOICE = VoiceId(KOBOLD_CHAT.tts_voice)


@dataclass(kw_only=True)
class AudiocppStartupRequestServiceSettings(GenericStartupServiceSettings):
    """Server startup plus request defaults; model and streaming_enabled affect both."""

    model: str
    streaming_enabled: bool = False

    voice: str
    streaming: SharedTtsStreamingRequestSettings = field(default_factory=SharedTtsStreamingRequestSettings)


AUDIOCPP_SERVICE = AudiocppStartupRequestServiceSettings(
    mode=ServiceMode.PROXY,
    enabled=True,
    listen_ip="0.0.0.0",
    port=8888,
    internal_port=8889,
    model=KOBOLD_CHAT.tts_model,
    voice=KOBOLD_CHAT.tts_voice,
    streaming_enabled=True,
)

# Native server JSON; model modes are edited directly in that file.
AUDIOCPP_SERVER_ARGS: dict[str, str] = {"config": str(audio_cfg.CONFIG_PATH)}

AUDIOCPP_PROXY_ACCEPTED_MODELS = tuple(model.value for model in AudiocppModel)
AUDIOCPP_PROXY_CLONE_VOICES: tuple[str, ...] = inputs.voice_ids()

AUDIOCPP_INPUT_DIR = project_cfg.VOICES_DIR  # voice samples for AUDIOCPP

# --- proxy only: model presets ---


@dataclass
class AudiocppProxyRequestModelPreset:
    prepend: str = ""
    request_options: dict[str, object] = field(default_factory=dict)
    pcm_sample_rate: int | None = None
    playback_buffer_ms: int | None = None
    playback_note: str = ""
    streaming_supported: bool = True
    instruction_option: str | None = "instruction"


# - Optional per-model request behavior; models without a preset pass through
# - Tone tags and the optional default instruction live in tts_text_processing.py.
# - Breeze chunk modes: "default" uses word-based splitting; "tag_aware" keeps tags intact.
#   The preset selects the proxy default, and request options can override it with either mode.
AUDIOCPP_PROXY_MODEL_PRESETS = {
    AudiocppModel.FISH_DRAMA3_Q2: AudiocppProxyRequestModelPreset(pcm_sample_rate=44100, playback_buffer_ms=4000),
    AudiocppModel.BREEZE_TTS: AudiocppProxyRequestModelPreset(
        request_options={"text_chunk_mode": "tag_aware"}, playback_buffer_ms=2000
    ),
    AudiocppModel.BREEZE_DESIGN: AudiocppProxyRequestModelPreset(
        request_options={"text_chunk_mode": "tag_aware"}, playback_buffer_ms=2000
    ),
    AudiocppModel.MING3_TTS: AudiocppProxyRequestModelPreset(
        pcm_sample_rate=44100, playback_buffer_ms=1000, instruction_option="instruct"
    ),
    AudiocppModel.MING3_AUDIO: AudiocppProxyRequestModelPreset(
        pcm_sample_rate=44100,
        playback_note="Complete WAV only; streaming is unavailable for this model.",
        streaming_supported=False,
        instruction_option=None,
    ),
}


# --- shared proxy behavior: text cleanup (streaming + buffered) ---
@dataclass
class SharedTtsTextCleanupSettings:
    # - Strings stripped from "input"
    # - Candidates: "*" (markdown emphasis shouldn't be read aloud),
    #   "." (caused unwanted Breeze pauses)
    strip_characters: list[str] = field(default_factory=lambda: ["`", "#", "<END>", "<START>"])

    # Emoji filtering is Unicode-aware in shared/media/text_processing.py; preserve other scripts.
    strip_patterns: list[str] = field(default_factory=list)

    # - {regex: replacement} applied before the strips, so words never get glued
    #   (stripping "a\u2014b" would give "ab")
    # - em/en dashes -> " "; use ", " instead to turn them into a pause
    replace_patterns: dict[str, str] = field(default_factory=lambda: {r"\s*[\u2014\u2013]\s*": " "})


SHARED_TTS_TEXT_CLEANUP = SharedTtsTextCleanupSettings()


# - Warmup makes model VRAM usage visible before the first request
# - Uses the same clone reference as normal requests


# ============================================================
# SDCPP (image gen) SETTINGS
# ============================================================


# --- core: applies in both "server" and "proxy" mode ---


# - "server" = sd-server.exe only (no wrapping)
# - "proxy"  = sd-server.exe + prompt-wrapping proxy
@dataclass(kw_only=True)
class SdcppStartupRequestServiceSettings(GenericStartupServiceSettings):
    """Startup and request model defaults; request labels do not hot-swap the checkpoint."""

    model: str
    build: str


SDCPP_SERVICE = SdcppStartupRequestServiceSettings(
    mode=ServiceMode.PROXY,
    enabled=False,
    listen_ip="0.0.0.0",
    port=1234,
    internal_port=1235,
    model="nova3d-q4",
    build="vulkan",
)
SDCPP_BUILDS = {"rocm": project_cfg.SDCPP_ROCM_DIR, "vulkan": project_cfg.SDCPP_VULKAN_DIR}

# - Named models -> checkpoint path; SDCPP_ACTIVE_ARGS["model"] picks which one loads
# - NOTE: sd-server.exe loads one model at a time via -m (same limitation as
#   AUDIOCPP_PROXY_MODEL_PRESETS above), so the proxy's model-field handling
#   below is cosmetic API compatibility, not hot-swapping
SDCPP_MODELS = {
    "nova3d": str(model_cfg.path("sdcpp/nova3DCGXL_ilV90")),
    "nova3d-q4": str(model_cfg.path("sdcpp/nova3DCGXL_ilV90_q4_K")),
}
# - The quantized checkpoint is bundled with CLIP/VAE; separate files are optional component overrides.

SDCPP_LORA_DIR = project_cfg.SDCPP_MODELS_DIR / "lora"

# - Optional: when set, every generated image is written here in both proxy
#   and standalone server mode (server mode runs a pass-through proxy to do it)
# - Set SDCPP_SAVE_OUTPUTS=False to disable
SDCPP_SAVE_OUTPUTS = True
SDCPP_OUTPUT_DIR = project_cfg.OUTPUT_DIR / "images" / "sdcpp"

# - Raw args passed straight to sd-server.exe on startup
# Model-load and executable options.
SDCPP_SERVER_ARGS: dict[str, object] = {
    "m": SDCPP_MODELS[str(SDCPP_SERVICE.model)],
    "lora-model-dir": str(SDCPP_LORA_DIR),
    "diffusion-fa": True,
}

# - Generation parameters injected by the proxy into the API request
# - Keys are the exact JSON field names sd-server.exe accepts (verified
#   against the binary: negative_prompt, clip_skip, cfg_scale, sampler_name)
# Generation defaults, overridden by explicit incoming values.
SDCPP_REQUEST_DEFAULTS: dict[str, object] = {
    "sampler_name": "euler_a",
    "steps": 20,
    "clip_skip": 2,
    "cfg_scale": 4.5,
    "width": 832,
    "height": 1216,
    "seed": 446796035,
    "negative_prompt": "extra digits, (particles, adversarial noise:1.2), multiple views, multiple angle, split view, grid view, two shot, outside border, picture frame, framed, border, letterboxed, pillarboxed, 2koma, modern, recent, old, oldest, cartoon, graphic, text, painting, crayon, graphite, abstract, glitch, deformed, mutated, ugly, disfigured, long body, lowres, bad anatomy, bad hands, missing fingers, extra fingers, extra digits, fewer digits, cropped, very displeasing, (worst quality, bad quality:1.2), sketch, jpeg artifacts, signature, watermark, username, (censored, bar censor, mosaic censor:1.2), simple background, conjoined, bad ai-generated",
}


# --- proxy only: request validation & prompt building ---

# - Allowed incoming "model" values; anything else falls back to
#   ACTIVE_SDCPP_MODEL
# - Only enforced when SDCPP_MODE == "proxy"
SDCPP_PROXY_ACCEPTED_MODELS = list(SDCPP_MODELS.keys())


class SdcppProxyRequestLora:
    def __init__(self, filename: str, default_weight: float = 0.8):
        self.filename = filename
        self.default_weight = default_weight

    def tag(self, weight: float | None = None) -> str:
        w = weight if weight is not None else self.default_weight
        return f"<lora:{self.filename}:{w}>"


@dataclass
class SdcppProxyRequestPromptSettings:
    # - Style scaffolding around the subject; matches the reference prompt for this model
    prefix: str = (
        "masterpiece, best quality, amazing quality, 4k, very aesthetic, high resolution, ultra-detailed, "
        "absurdres, newest, esthetic, scenery, 3d, rendered, dispersion \\(optics\\), prism, anaglyph"
    )
    suffix: str = (
        "dramatic shadow, depth of field, vignetting, dappled sunlight, lens flare, backlighting, volumetric lighting"
    )

    # - Fallback subject when the request carries no prompt; the overlay may replace it
    default_inner_prompt: str = inputs.setting("image.prompt", "a person standing outdoors in soft daylight, full body")

    # - Comma-joined lora tags prepended to every prompt, e.g. SdcppProxyRequestLora("style", 0.6).tag()
    #   Personal LoRAs live in the overlay; the repository default selects none.
    lora_selections: str = inputs.setting("image.loras", "")

    def build(self, inner_prompt: str | None = None) -> str:
        inner = inner_prompt or self.default_inner_prompt
        return ", ".join(part for part in (self.lora_selections, self.prefix, inner, self.suffix) if part)


SDCPP_PROXY_PROMPT = SdcppProxyRequestPromptSettings()


# ============================================================
# LEMONADE SERVER SETTINGS
# ============================================================


@dataclass(frozen=True)
class LemonadeStartupServiceSettings:
    """Lemonade's own server: one API in front of its llama.cpp, kokoro and sd.cpp backends."""

    framework_dir: Path = project_cfg.component("lemonade_server").framework_dir
    port: int = 13305
    # - Lemonade keeps its settings in the user profile, not in this repository; a run
    #   points extra_models_dir at our weights and restores the file afterwards.
    config: Path = Path.home() / ".config/lemonade/config.json"
    startup_timeout_s: float = 90.0

    @property
    def exe(self) -> Path:
        return self.framework_dir / "bin/LemonadeServer.exe"


LEMONADE_SERVICE = LemonadeStartupServiceSettings()
