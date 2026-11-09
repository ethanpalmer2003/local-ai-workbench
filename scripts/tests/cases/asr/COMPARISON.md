# ASR comparison

High-ranking group: [selection](../../../config/asr/leaderboard_group.json),
[dated published quality/speed snapshot](../../notes/asr/leaderboards-2026-10-29/README.md).
Use `--group leaderboard-high-ranking --resources --language en --run --samples 3 --clips 2`
with the resident runner. All five candidates remain visible, including missing
assets/runtime failures. Isolated resources do not establish LLM/TTS coexistence
capacity. Publisher RTFx remains separate from local speed.

- [Streaming/VAD groups](../../../launchers/asr/CAPABILITIES.md); [evaluation](../../notes/asr/ASR-SCREEN.md).
- ASR coexistence tests use Kokoro or another lightweight multilingual TTS, not Breeze/heavier speech models. [One-server evidence](../../notes/audiocpp/AUDIOCPP-SINGLE-SERVER.md); isolated ASR measurements remain labelled separately.

The [resident runner](../../../benchmarks/asr/asr_resident_compare.py) uses the domain-neutral
[benchmark lifecycle](../../../benchmarks/README.md). Startup/loading, first inference,
warmup and cleanup are separate from measured requests. Unknown phase splits stay
unknown; no estimated loading cost is subtracted.

```powershell
C:/AI/bat/benchmarks/benchmark_asr_compare.bat
C:/AI/bat/benchmarks/benchmark_asr_compare.bat --run --samples 2 --clips 2
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tests.cases.asr.shared.coverage
```

Preview does not start native code. Default is every configured resident profile: AudioCpp Cohere, NeMo and Ming;
speech.cpp; Parakeet CPU/Vulkan, v3 and Nemotron streaming; Whisper Vulkan and embedded Kobold Whisper;
llama.cpp Qwen, Gemma and Granite. Cohere and Granite have brief saved checks
on two synthetic English clips, three repeats each; this does not establish multilingual/noisy quality.
The original Parakeet CPU/Vulkan profiles use English 110M.
`--engines` selects a subset; `--budget` bounds the whole inference sequence.
The default corpus is saved synthetic English Kokoro audio. `--corpus` accepts the
shared JSON manifest. Inputs are prepared before timing; response transfer and JSON
parsing are included. Reports retain commands, model SHA256, corpus references,
actual execution context, Unicode WER/CER, failures, lifecycle phases and request
summaries. Missing assets/failures remain visible; servers are task-owned and
occupied ports are refused.

The [coverage ledger](shared/coverage.py) explicitly lists every current ASR option,
including missing resident adapters, manual Handy dictation, disabled legacy Whisper,
and any unsupported alternatives. New file profiles automatically appear as unreviewed.
Do not interpret a coverage entry as a completed test. Real microphone pacing,
first-partial latency and multilingual/noisy accuracy remain separate checks.

[Whisper/Kobold](../../../benchmarks/asr/whisper_embedded_compare.py) and
[Gemma audio](../../../benchmarks/asr/gemma_audio_compare.py) now record the same lifecycle, but retain
their existing orchestration and decoder controls. They have not been rerun after
migration. Handy requires manual evaluation. Kobold Gemma uses the separate migrated runner. This is not
a complete quality or speed ranking.

The old cold CLI runner and leaderboard were archived under `C:/AI/trash/benchmark-cleanup-2026-10-28/`. Functional transcript parsing remains in `file_diagnostic.py`.
Its process-inclusive results are [historical evidence](../../../../notes/asr/ASR-COMPARISON.md),
not resident latency. Existing resource/smoke probes remain useful functional checks.

Initial resident validation: all eleven adapters passed one clip and one measured
request on 2026-10-28, in bounded subsets. This verifies persistent operation, not quality or reliable comparative speed. Evidence (../../output/asr/shared/resident_compare/unreviewed/1793214073218879900/artifacts/report.json).

[Additional three-profile checks](../../notes/asr/ASR-EXTRA-PROFILES.md) pass. All resident comparisons use complete clips; Nemotron's CPU streaming-file check is separate from its Vulkan offline HTTP timing.
