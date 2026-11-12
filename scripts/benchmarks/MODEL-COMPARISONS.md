# Model/profile comparisons

- llama.cpp profile runner: `scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles`; Strata runner: `scripts.benchmarks.coding_agents.strata_profiles`.
- One coding corpus across engines: `scripts.benchmarks.inference_engines.benchmark_coding_engines` runs cold and warm requests per task and reports cold prefill, warm prefill, decode, TTFT and draft acceptance from each server's own timings. `--engine llamacpp` starts a profile; `--engine endpoint` dials any OpenAI-compatible server ([scope](inference_engines/README.md)).
- Strata vs Avalon on identical Strata IQ2_XS weights: `scripts.benchmarks.inference_engines.benchmark_strata_avalon` (Strata keeps MTP/cache; Avalon cannot use either on this quant).
- The cross-engine build sweep was retired to `C:/AI/trash/retired-llm-inference-sweep`; hipfire and TabbyAPI/ExLlamaV3 skip on Windows and need non-GGUF weights, so Swift IQ3_XXS numbers stay llama.cpp-only.
- Current default profile: `swift15`; `swift15-mtp-notemplate` remains selectable. Historical `swift15-mtp` labels are not current profile IDs.

```powershell
python -m scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles --builds vulkan rocm-lemonade --profiles swift15-8k --prompt-set prose --max-tokens 64 --warmup-tokens 64 --repeats 3
```

- Native workload: live/opt-in. Refuse conflicting sessions, warm up, alternate order and separate startup/model loading from measurements.
- Match hashes, tokenizer/template, context occupancy/capacity, sampling, KV type, FA, speculation, reasoning and token limits. Request count alone is insufficient.
- Build comparisons run on the configured default model, so only the build changes: Breeze 2 for AudioCpp and `swift15` for llama.cpp coding builds. The llama.cpp coding builds are the ROCm builds taken from Lemonade's release assets; Lemonade's own server is a separate language-practice framework measured with Gemma. A non-default model such as Ming gets one check on the default build, never across every build.
- Short-context evidence cannot establish filled-context performance. Reused prompts/cache conditions must be explicit.
- Latest paired easy Pi task: both Strata Swift and 27B passed 8/8; timings and token totals are in [outcomes](../tests/notes/OUTCOMES.md).
- Strata profile pair, screen not ranking: numbers, conditions and the older disagreeing table live in the dated record, [STRATA-PROFILES-2026-11-09](../../notes/reviews/STRATA-PROFILES-2026-11-09.md).
- Strata vs Avalon, that pair (2-5 samples, n-max 2): Strata decode 22.9 tok/s, prefill 110.5, TTFT 27.4 s; Avalon 27.6-34.1, prefill 61-65, TTFT 46-49 s. Variance is real (Avalon measured 22.4→34.1 across runs); no winner from one pair.
- Strata CPU-expert residency is unavailable here: `--resident-cpu-experts` needs the whole 24.90 GiB complement in RAM, but 24.35 GiB available minus the 8 GiB headroom leaves ~16-20 GiB, so the engine exits rather than degrading. `--kv-grow` also fails: the 4.09 GiB mapping runs out of VRAM down to 0.97 GiB. The 22.9 baseline is Strata's best configuration here.
- Avalon prompt caching needs `--cache-ram` explicitly: its default is 0 when the model exceeds RAM. At 1024 MiB it reuses only 15 of 3025 tokens, so TTFT stays ~46 s; prefill, not decode, dominates wall time.
- The 48 GiB manual page file (96 GiB max, 2.7 GiB peak) already exceeds what "System managed" would allocate; Strata's page-file advice does not apply and changing it would likely reduce the commit budget.
- [Configuration rationale](../config/llamacpp/TUNING.md), [experimental Strata profile](../config/strata/REFERENCE.md).
- New outputs follow `scripts/benchmarks/output/`; superseded `tests/output/models/` and `tests/output/harnesses/` were retired to trash (manifest included). Retain failures and incomplete matrices.
