# Practice integration checks

2026-10-28: both default practice gateways pass a brief saved-PCM flow:
Silero speech end -> Nemotron final transcript -> Gemma E4B reply -> Kokoro WAV.
One Vulkan AudioCpp server serves ASR/TTS, with one CPU Silero helper per active
microphone session. The same AudioCpp server stayed loaded across both chat runs.

- Combined native report (../output/asr/shared/practice_smoke/unreviewed/1793240046629735700/artifacts/report.json)
- Native log: `scripts/state/logs/shared/practice-smoke-complete.log`
- 353 model-free regression checks: `scripts/state/logs/shared/practice-regressions.log`

Approved outside-sandbox execution: AppContainer false, administrator false.
Tests used isolated ports 19193-19195 and stopped only owned services. No packages
were installed. Shared lifecycle records separate combined startup/model loading,
warmup, resident requests and cleanup for AudioCpp, Gemma and VAD. The request
includes paced playback of the saved input; it is not an ASR speed comparison.

Simulated browser contracts cover 512-sample AudioWorklet framing, automatic turn
submission, chat/TTS routing, French voice selection and microphone cleanup.
Server contracts cover ownership, frame validation, one-session capacity,
origin/payload rejection, failure cleanup and both gateway route handlers.

The initial native attempt exposed an empty spoken reply when Gemma spent its
budget thinking. Practice disables thinking and rejects empty spoken replies.
Test-only Kobold port-alias/readiness issues were corrected; earlier failed
artifacts remain preserved.

Actual microphone permission/device capture, acoustic echo, browser playback,
multilingual/learner accuracy and interruption latency remain unverified.
Current UI is sequential: recognition receives silence during tutor generation
and playback, so it does not implement voice interruption. Auto language detection
uses the English voice; explicit English/Spanish/French selects matching voices.

Procedure/settings: [ASR turn guide](../../launchers/audiocpp/ASR-VAD.md).
