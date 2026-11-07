# AudioCpp and TTS

[Model languages and offline query](../../config/notes/MODEL-LANGUAGES.md).

- [Silero automatic ASR turns](ASR-VAD.md): Nemotron/Kokoro server plus a tiny CPU VAD helper; saved-file launcher and streaming integration API.
- [Retained TTS runtimes](RETAINED-TTS.md): Sherpa ONNX and Piper installs, updates and the resident comparison, kept as alternatives.

AudioCpp is the default practice TTS runtime. Prioritize natural multilingual
speech and latency; Piper/Sherpa remain alternatives. Listening checks are separate.

Nemotron/Kokoro share one server: [checks](../../tests/notes/audiocpp/AUDIOCPP-SINGLE-SERVER.md).

- Speech test: [launcher](../../../bat/browser/launch_test.bat); ASR, LLM and TTS are optional. The AudioCpp proxy redirects `/test/` there. Native Vulkan is default; `--build` follows launcher config.
- ROCm: updater `--only audiocpp/rocm`; installs under `frameworks/audiocpp/rocm/`. Compare with Vulkan using `python -m scripts.tests.cases.audiocpp.audiocpp_backend_compare`; [evidence](../../../notes/NATIVE-VALIDATION.md).
- Both release executables live directly in `frameworks/audiocpp/{vulkan,rocm}/`; updater flattens vendor build folders. Older ROCm variants stay under `additions/rocm/`.
- Brief tests: `python -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case breeze2`; [Audio model setup](../../config/audiocpp/MODELS.md). Default is one warmup and one measured short sentence per official backend.
- Editable native modes/models/session options: `config/audiocpp/server.json`. Python service/playback selection: `AUDIOCPP_SERVICE`; Kokoro profile: `KOKORO_TTS`.
- Kokoro defaults to the bundled multilingual Q8 package. `KOKORO_TTS.audiocpp_package`
  selects `multilingual` or retained `small`; both stay in the download catalog.
  Japanese needs bundled UniDic plus `AUDIOCPP_MECAB_LIBRARY`. Provision the pinned
  portable DLL/licenses with `python -m scripts.download.frameworks.audiocpp.setup_mecab`;
  it does not install a Python package. Language choices inspect the selected GGUF.
- Standalone reads native JSON; shared GPU and CPU Kokoro derive configs in `state/generated/audiocpp/`. [Ownership](../../config/notes/GENERATED-FILES.md).

## Speech test page

- [Diagnostic page](../../tests/ui/speech.html) and Kobold Lite share [pcm_audio.js](../shared/browser/pcm_audio.js), with independent overrides.
- Page initialization reads `/proxy/config`; generation remains disabled if this fails. After Python edits, restart the proxy and refresh defaults.
- One [speech workspace](../asr/PRACTICE-WORKSPACE.md) owns the maximalist test view and optional ASR, LLM and TTS stages. The AudioCpp proxy's old `/test/` URL redirects to that workspace.
- Ming is selectable as a TTS model; its playback rate is 44100 Hz and Instruction maps to native `instruct`.
- HTTP PCM/WAV and SSE feed one decoder/player. SSE expects PCM delta events plus completion; compressed audio falls back to complete decoding.
- Select launcher default to clear saved transport overrides. Native model mode must support the requested response; client streaming flags do not change loaded model mode.

## Restart management

- Proxy/backend/both controls respect readiness, active work, cancellation and ownership. [Shared restart code](../proxy_restart.py).

Delivery, streaming trade-offs and tone/text processing: [TTS-DELIVERY.md](TTS-DELIVERY.md).

- [Measured outcomes](../../tests/notes/OUTCOMES.md), [candidate experiments](../../tests/notes/audiocpp/AUDIOCPP-OPTIMIZATIONS.md), [shared GPU](../../config/notes/SHARED-GPU.md), [images on demand](../../config/notes/IMAGE-ON-DEMAND.md).
