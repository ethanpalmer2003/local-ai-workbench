# Brief conversational runtime screen

2026-10-28. One warmup and two measured requests per setup; startup/loading
excluded by the shared lifecycle. Approved execution: AppContainer false,
administrator false. Servers were task-owned and cleaned up; no packages changed.

## Four TTS frameworks

Exact same short/long English texts; complete WAV synthesis, no playback timing.

| Runtime / model | Short seconds | Long seconds | RTF short / long |
| --- | ---: | ---: | ---: |
| Piper / Lessac medium | 0.122 | 0.262 | 0.024 / 0.024 |
| Sherpa / same Lessac model | 0.144 | 0.267 | 0.030 / 0.026 |
| AudioCpp CPU / Kokoro Q8 | 1.929 | 4.546 | 0.371 / 0.393 |
| Kobold CPU / Kokoro Q4 | 3.166 | 6.888 | 0.597 / 0.599 |

RTF is generation seconds/audio seconds; lower is faster. Piper/Sherpa share
the exact model. Kokoro uses af_heart in both, but different quantization and
phonemizers; five threads versus Sherpa's four and Piper's runtime default.
Two model families do not isolate a four-way framework effect. No listening,
multilingual quality, streaming-first-audio or active-LLM overlap ranking.

Kokoro evidence (../output/shared/kobold_embedded_compare/unreviewed/1793231643344683600/artifacts/comparison.md);
Piper (../output/tts/shared/resident/unreviewed/1793231696855565000/artifacts/piper.json);
Sherpa (../output/tts/shared/resident/unreviewed/1793231696855565000/artifacts/sherpa-onnx.json).

## Gemma E4B

Identical Q4_0 GGUF/hash, Vulkan, 8192 context, F16 KV, four threads, seed 42,
temperature zero, model Jinja template and thinking disabled. Two prompts:
conversation question and English correction. Both produced identical visible
answers and reported 6/28 generated tokens.

| Runtime | First usable content seconds | Complete reply seconds |
| --- | --- | --- |
| llama.cpp | 0.063 / 0.072 | 0.112 / 0.329 |
| Kobold | 0.594 / 0.591 | 0.594 / 0.591 |

Kobold delivered one content chunk per response; llama.cpp delivered 5/27.
This describes the tested OpenAI endpoint, not every Kobold streaming interface.
Combined startup/loading was 4.58/8.08 seconds respectively, excluded above.
Matched report (../output/shared/gemma_runtime_screen/unreviewed/1793231834278361100/artifacts/report.json).
An initial template/reasoning-mismatched run is diagnostic only, excluded.

## Preliminary shortlist

- Prefer llama.cpp for this conversation profile; keep Kobold as the integration fallback.
- Deprioritize embedded Kobold Kokoro for speed; retain AudioCpp Kokoro as its faster alternative.
- Piper/Sherpa both advance; the tiny sample does not justify choosing between them.
- Current Lessac is English-only. Multilingual voices, pronunciation/listening,
  ASR screening and actual conversational overlap remain separate work.
