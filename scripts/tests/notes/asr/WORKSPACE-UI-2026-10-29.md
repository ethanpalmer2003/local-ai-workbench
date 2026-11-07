# Speech workspace validation - 2026-10-29

Status: verified functional smoke, not a performance ranking.

- Approved outside-sandbox execution; actual Windows token: AppContainer false,
  administrator elevation false. Context is also recorded with lifecycle events.
- Cold HTTP chat -> Gemma E4B -> Kokoro WAV passed. Reply: "I am fine, thank you
  for asking." WAV: 112,844 bytes. Native LLM startup/model readiness: 6.367 s;
  request: 0.178 s. AudioCpp startup: 1.854 s; Kokoro explicit load: 5.601 s;
  speech request: 0.354 s. One request, no warmup/ranking claim.
- Generated English WAV -> Nemotron transcription passed: "Hello, how are you
  today". ASR/TTS shared one owned AudioCpp process; LLM stayed unloaded.
- Both live checks ended with all model stages unloaded.
- Evidence: `scripts/state/logs/asr/shared/practice-lifecycle-1793300817654949200.jsonl`.
- 33 focused regressions pass, including the actual HTTP entry point, shared
  residency, level/correction prompts, transcript review, cancelled replies and
  microphone permission arriving after capture cancellation. The lifecycle JS
  loads alongside the workflow JS in browser fixtures.
- Native browser Send also passed with A2/corrections enabled: "Hello! That is
  great. What is your name?" Reply history and replayable audio appeared, controls
  returned to Ready, and ASR remained unloaded for typed input.
- A real microphone was not captured. Continuous capture/permission races use
  simulated browser/audio fixtures; listening quality is not scored here.

The HTTP smoke found and fixed a handler-name collision that bypassed automatic
service startup. Browser inspection found and fixed a lifecycle-script syntax error.
Both paths now have regression coverage.
