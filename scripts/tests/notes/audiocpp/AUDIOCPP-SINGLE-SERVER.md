# One AudioCpp server: ASR and Kokoro

2026-10-28. Official Vulkan build, standard runtime; no experimental parallel flag.
Nemotron Q8 ASR and Kokoro Q8/af_heart load eagerly in one process, five threads,
two-model residency limit, idle unload disabled. Both use the global Vulkan backend.
Kokoro is the lightweight multilingual TTS choice for ASR coexistence checks;
this screen uses English only.

## Result

One server works for alternating and simultaneous requests. Seven API snapshots
report both models loaded; server PID is unchanged. TTS output hashes match
across alternating/concurrent/paced-overlap requests. No unload/reload was observed;
the API does not expose a generation counter proving absence of hidden reloads.

| Test | ASR | Kokoro TTS |
| --- | --- | --- |
| Alternating requests, streaming ASR session | 251-296 ms complete-file request | 187-198 ms |
| Simultaneous complete-file requests | 400 ms | 225 ms |
| Paced ASR plus TTS started 0.9 s into input | First partial 987 ms; final 51 ms after input end | First audio 169 ms; complete 170 ms |

ASR input is 5.3 seconds; generated speech is 5.2 seconds. Startup/loading/warmup
are excluded. The earlier offline-ASR-mode screen gave 62-90 ms alternating ASR
and 157-235 ms TTS; its mode differs from the streamed configuration above.
These are tiny samples, not percentiles or proof of simultaneous GPU kernels.

Sampled process GPU allocation peak: 2162 MiB; process RAM working-set peak:
166 MB. Only three process GPU samples were available; peaks are lower bounds,
not exact memory requirements. Desktop/other allocations are separate.

[Streaming/overlap report](../../output/audiocpp/single_server_speech/unreviewed/1793236264505744900/artifacts/report.json),
[memory](../../output/audiocpp/single_server_speech/unreviewed/1793236264505744900/artifacts/vram.json),
[offline-mode report](../../output/audiocpp/single_server_speech/unreviewed/1793236100539245300/artifacts/report.json).

## Scope and reuse

- Approved token: AppContainer false, administrator false; no existing AudioCpp
  session was present. Task-owned server/helper cleaned up; no packages/defaults changed.
- Run `python -m scripts.tests.cases.audiocpp.single_server_speech` for the bounded
  screen. Generated config, exact model hashes, transcripts and WAVs stay in output.
- Earlier Kokoro CPU timings cannot rank against this Vulkan run.
- Gemma residency/generation, automatic VAD, actual playback/echo cancellation,
  long sessions and multilingual quality remain untested in this combined setup.
- Type and structure checks pass. Prefer this one-instance architecture; test
  separate instances only for a demonstrated queueing/isolation/resource problem.
