"""ASR-only catalog; component keys match frameworks/asr and model owners."""

from pathlib import Path

from scripts.download.frameworks.update_shared import UpdateSummary
from scripts.download.frameworks.update_types import ReleaseType, ToolSpec


def install_handy(tool: ToolSpec) -> None:
    """Post-install hook: run the portable setup when the app is missing."""
    from scripts.download.frameworks.asr import handy

    handy.install_app()


def install_handy_pending(tool: ToolSpec) -> bool:
    """A current installer still needs its post-install step while the app is absent."""
    from scripts.download.frameworks.asr import handy

    return handy.app_missing()


def process_whisper(
    tool: ToolSpec, dest_dir: Path, tmp_dir: Path, check_only: bool, summary: UpdateSummary | None
) -> None:
    """Build the current Whisper Vulkan release through the normal update plan."""
    from scripts.download.frameworks.asr import whispercpp

    needed = whispercpp.process(tool, dest_dir, tmp_dir, check_only)
    if summary is not None:
        summary.record(tool, "available" if needed else "current")


TOOLS = [
    ToolSpec(
        "asr/handy/installer",
        "Handy-setup.exe",
        ReleaseType.DATE,
        repo="cjpais/Handy",
        asset_pattern=r"^Handy_.*_x64-setup\.exe$",
    ),
    ToolSpec(
        "asr/parakeetcpp/vulkan",
        "parakeet-cli.exe",
        ReleaseType.DATE,
        repo="mudler/parakeet.cpp",
        asset_pattern=r"^parakeet-v.*-bin-win-vulkan-x64\.zip$",
    ),
    ToolSpec(
        "asr/parakeetcpp/cpu",
        "parakeet-cli.exe",
        ReleaseType.DATE,
        repo="mudler/parakeet.cpp",
        asset_pattern=r"^parakeet-v.*-bin-win-cpu-x64\.zip$",
    ),
    ToolSpec(
        "asr/parakeetcpp/cpu-stream", "parakeet.dll", ReleaseType.MANUAL,
        repo="mudler/parakeet.cpp", source_checkout="asr/parakeetcpp/additions", in_use=False,
    ),  # Pinned optional C API build; routine updates must not rebuild it.
    ToolSpec(
        "asr/whispercpp/vulkan",
        "whisper-cli.exe",
        ReleaseType.DATE,
        repo="jerryshell/whisper.cpp-windows-vulkan-bin",
        asset_pattern=r"^whisper\.cpp-windows-vulkan\.zip$",
        in_use=False,
    ),
    ToolSpec(
        "asr/whispercpp/vulkan-build",
        "whisper-cli.exe",
        ReleaseType.NATIVE_BUILD,
        repo="ggml-org/whisper.cpp",
        source_checkout="asr/whispercpp/additions",
    ),
    # Official prebuilt packages; preserve NeMo's bin/lib layout.
    ToolSpec(
        "asr/nemo-speechcpp/vulkan",
        "bin/nemo-speech.exe",
        ReleaseType.DATE,
        repo="NVIDIA/NeMo-Speech.cpp",
        asset_pattern=r"^nemo-speech-(?!nightly-)[\d.]+-windows-x86_64-vulkan\.zip$",
    ),
    ToolSpec(
        "asr/speechcpp/vulkan",
        "speech.exe",
        ReleaseType.DATE,
        repo="nyosegawa/speech.cpp",
        asset_pattern=r"^speech-[\d.]+-windows-x64-vulkan\.zip$",
    ),
    ToolSpec(
        "asr/crispasr/vulkan",
        "crispasr.exe",
        ReleaseType.DATE,
        repo="CrispStrobe/CrispASR",
        asset_pattern=r"^crispasr-windows-x86_64-vulkan\.zip$",
    ),
    ToolSpec(
        "asr/funasr/vulkan",
        "llama-funasr-sensevoice.exe",
        ReleaseType.DATE,
        repo="modelscope/FunASR",
        asset_pattern=r"^funasr-llamacpp-windows-x64-vulkan\.zip$",
    ),
]
