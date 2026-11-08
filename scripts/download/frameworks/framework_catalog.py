"""Compose the llama.cpp, speech and other framework catalogs."""

from dataclasses import replace

from scripts.download.frameworks import update_shared
from scripts.download.frameworks.asr import updates as asr_updates
from scripts.download.frameworks.audiocpp import updates as audiocpp_updates
from scripts.download.frameworks.llamacpp import updates as llamacpp_updates
from scripts.download.frameworks.llamacpp.updates import hrx_tools as hrx_tools
from scripts.download.frameworks.llamacpp.updates import rdna_tools as rdna_tools
from scripts.download.frameworks.shared import other_updates
from scripts.download.frameworks.shared.other_updates import benchmark_tools as benchmark_tools
from scripts.download.frameworks.shared.other_updates import pi_tools as pi_tools
from scripts.download.frameworks.tts import updates as tts_updates
from scripts.download.frameworks.update_types import ReleaseType as ReleaseType
from scripts.download.frameworks.update_types import ToolSpec as ToolSpec
from scripts.download.frameworks.update_types import update_kind as update_kind

CATEGORIES = dict(update_shared.CATEGORY_HEADINGS)
CATALOGS = {
    "llamacpp": llamacpp_updates.TOOLS,
    "speech": [*audiocpp_updates.TOOLS, *tts_updates.TOOLS],
    "asr": asr_updates.TOOLS,
    "other": other_updates.TOOLS,
}
TOOLS = [replace(tool, category=category) for category, tools in CATALOGS.items() for tool in tools]

update_shared.MANAGED_HANDLERS.update(
    {
        ReleaseType.NPM: other_updates.process_tool,
        ReleaseType.BAT: other_updates.process_tool,
        ReleaseType.STRATA: other_updates.process_tool,
        ReleaseType.DESKTOP: other_updates.process_tool,
        ReleaseType.BUILD: audiocpp_updates.process_tool,
    }
)
update_shared.POST_INSTALLERS["asr/handy/installer"] = asr_updates.install_handy
update_shared.POST_INSTALL_PENDING["asr/handy/installer"] = asr_updates.install_handy_pending
update_shared.MANAGED_HANDLERS[ReleaseType.NATIVE_BUILD] = asr_updates.process_whisper
update_shared.RELEASE_INSTALLERS[ReleaseType.WHEEL] = tts_updates.install_wheel
update_shared.SOURCE_PATCH_WRITER = llamacpp_updates.snapshot_source_patches
update_shared.SOURCE_DIRTY_CHECK = llamacpp_updates.source_dirty
update_shared.SOURCE_AHEAD_CHECK = llamacpp_updates.source_ahead
update_shared.SNAPSHOT_MODIFIERS["benchmarks/specspeed"] = other_updates.modify_specspeed
update_shared.ASSET_FALLBACKS["audiocpp/additions/rocm/7.1-old"] = audiocpp_updates.legacy_asset
update_shared.RELEASE_NOTES["llamacpp/rocm/lemonade"] = llamacpp_updates.release_notes
