# Shared launcher helpers

This package contains cross-backend helpers grouped by job:

- `services/`: `process.py` owns readiness polling, HTTP probes and safe cleanup;
  `LAUNCH.existing_service_policy` selects what startup does with an occupied
  service port (`KILL` by default; `REUSE` or `ERROR` are alternatives).
  `native.py` applies that policy before health-checked startup. `service_lifecycle.py`
  owns on-demand service/model residency and separates preparation from request
  timing. Browser workspace lifecycle UI does not start models on page load.
- `transport/`: HTTP input, multipart uploads, streaming HTTP and the WebSocket
  worker. Keep correctness fixtures independent so shared implementation bugs
  remain detectable.
- `media/`: audio decoding, mono conversion, resampling, PCM WAV encoding and
  shared speech-text cleanup. `SHARED_TTS_TEXT_CLEANUP` owns generic settings;
  voice-language filtering affects speech only, preserving displayed replies and
  romanization. Latin voices skip CJK; Japanese voices retain Japanese. Never
  remove whole Unicode planes to filter emoji. Model adapters own clipping,
  duration and prompt policy; Breeze tone and vocal events stay in its adapter.
- `browser/`: browser WAV encoding/playback, speech capture/client helpers and
  workspace lifecycle UI. `speech_tools.js` handles speech-response errors and
  capture-to-WAV conversion. These assets are served by launcher routes.
- `native_abi/`: explicit DLL loading, search-path ownership, symbol signatures,
  and selected plain ABI structures. Unsupported ABI fields fail before binding;
  adapters retain their own model structs, configuration and native object
  destruction.

ASR [file profiles](../../config/asr/file_profiles.py) own CLI/server
argument metadata. The [resident catalog](../asr/shared/resident_profiles.py)
builds server commands from those profiles and launcher builders; consumers must
not import command definitions from test modules.

## Device selection

No tracked file stores a GPU ordinal. The one owner is
[runtime/gpu_selection.py](../runtime/gpu_selection.py): it asks the engine's own binary for its device list
(`--list-devices`), matches the adapter named in
[config/shared/hardware.json](../../config/shared/hardware.json), and returns the id or index that engine
takes. A launch fails when the adapter is missing; an index of 0 is never the fallback, because that position
may be the integrated adapter. Check an engine before wiring it:
`python -m scripts.launchers.runtime.gpu_selection frameworks/sdcpp/vulkan/sd-server.exe`.

Two vendor-owned surfaces stay outside the rule and are accepted: Strata's desktop app reads the tracked
configs directly, so its `gpu: 0` means the discrete adapter only when this repository starts it and applies
the HIP mask; AudioCpp's native `server.json` keeps `device: 0` as its default for direct readers, while the
launcher materializes the resolved index.

Imports never start services or load model libraries. Optional audio dependencies
load only when conversion is requested. Timing remains owned by the
[shared benchmark lifecycle](../../benchmarks/README.md), independently of
framework and model behavior.
