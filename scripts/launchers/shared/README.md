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

Imports never start services or load model libraries. Optional audio dependencies
load only when conversion is requested. Timing remains owned by the
[shared benchmark lifecycle](../../benchmarks/README.md), independently of
framework and model behavior.
