# AudioCpp and TTS

[Model languages and offline query](../../config/notes/MODEL-LANGUAGES.md).

- [Silero automatic ASR turns](ASR-VAD.md): Nemotron/TTS server plus a tiny CPU VAD helper; saved-file launcher and streaming integration API. The browser loop and gateway session: [streaming integration](ASR-VAD-STREAMING-INTEGRATION.md).
- [Retained TTS runtimes](RETAINED-TTS.md): Sherpa ONNX and Piper installs, updates and the resident comparison, kept as alternatives.

AudioCpp is the default practice TTS runtime. Prioritize natural multilingual
speech and latency; Piper/Sherpa remain alternatives. Listening checks are separate.
The practice model is Supertonic 3: one self-contained GGUF with 31 listed languages
and preset voices `M1`-`M5`/`F1`-`F5`, named by `LANGUAGE_PRACTICE.tts_model` and
configured in `config/audiocpp/server.json`. Kokoro is parked: its packages stay installed but
nothing selects them.

Nemotron and the practice TTS model share one server: [checks](../../tests/notes/audiocpp/AUDIOCPP-SINGLE-SERVER.md).

- Speech test: [launcher](../../../bat/browser/launch_test.bat); ASR, LLM and TTS are optional. The workspace serves the page. Native Vulkan is default; `--build` follows launcher config.
- ROCm: updater `--only audiocpp/rocm`; installs under `frameworks/audiocpp/rocm/`. Compare with Vulkan using `python -m scripts.tests.cases.audiocpp.audiocpp_backend_compare`; [evidence](../../../notes/NATIVE-VALIDATION.md).
- Both release executables live directly in `frameworks/audiocpp/{vulkan,rocm}/`; updater flattens vendor build folders. Older ROCm variants stay under `additions/rocm/`.
- Brief tests: `python -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case breeze2`; `--case supertonic` and `--case ming3-tts` cover the remaining families. [Audio model setup](../../config/audiocpp/MODELS.md). Default is one warmup and one measured short sentence per official backend.
- Editable native modes/models/session options: `config/audiocpp/server.json`. Python service/playback selection: `AUDIOCPP_SERVICE`; Supertonic presets: `SUPERTONIC_TTS`; request defaults: `AUDIOCPP_SPEECH`.
- The server links eSpeak NG and MeCab for its own frontends; `AUDIOCPP_SPEECH` owns both paths and `AUDIOCPP_ESPEAK_LIBRARY`/`AUDIOCPP_ESPEAK_DATA`/`AUDIOCPP_MECAB_LIBRARY` carry them. Provision the pinned portable DLL/licenses with `python -m scripts.download.frameworks.audiocpp.setup_mecab`; it installs no Python package.
- Standalone reads native JSON; shared GPU and CPU speech configs derive in `runs/state/generated/audiocpp/`. [Ownership](../../config/notes/DERIVED-OUTPUTS.md).

## Speech test page

- [Diagnostic page](../../tests/ui/speech.html) and Kobold Lite share [pcm_audio.js](../shared/browser/pcm_audio.js), with independent overrides.
- Page initialization reads `/proxy/config`; generation remains disabled if this fails. After Python edits, restart the proxy and refresh defaults.
- One [speech workspace](../asr/PRACTICE-WORKSPACE.md) owns the page and the optional ASR, LLM and TTS stages; it relays every speech request through the AudioCpp proxy, which no longer serves a page of its own.
- The page starts its practice view on the language-practice voice (Supertonic) and its test view on this proxy's model (Breeze). A last-used tone shows as a note, never as a filled-in default: Breeze's default instruction is empty.
- Ming is selectable as a TTS model; its playback rate is 44100 Hz and Instruction maps to native `instruct`.
- Clone reference quality: `python -m scripts.review.voice_references` lists the chosen clip per voice and flags sound annotations, scene text, broken characters and missing clips; the audio itself lives in the private overlay.
- HTTP PCM/WAV and SSE feed one decoder/player. SSE expects PCM delta events plus completion; compressed audio falls back to complete decoding.
- Select launcher default to clear saved transport overrides. Native model mode must support the requested response; client streaming flags do not change loaded model mode.

## Restart management

- Proxy/backend/both controls respect readiness, active work, cancellation and ownership. [Shared restart code](../proxy_restart.py).

Delivery, streaming trade-offs and tone/text processing: [TTS-DELIVERY.md](TTS-DELIVERY.md).

- [Measured outcomes](../../tests/notes/OUTCOMES.md), [candidate experiments](../../tests/notes/audiocpp/AUDIOCPP-OPTIMIZATIONS.md), [shared GPU](../../config/notes/SHARED-GPU.md), [images on demand](../../config/notes/IMAGE-ON-DEMAND.md).
