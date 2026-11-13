# Strata vs Avalon inference benchmark

- Runner: `scripts.benchmarks.inference_engines.benchmark_strata_avalon`; entry `C:/AI/bat/benchmarks/benchmark_strata_avalon.bat`.
- Answers "which engine is faster, and in which phase"; the [coding-agent benchmark](../coding_agents/README.md) answers "does the agent finish the task".
- Generic cross-engine runner: `scripts.benchmarks.inference_engines.benchmark_coding_engines` runs one coding corpus (two tasks, one fresh generation and one rewrite of given code) with cold and warm requests against `--engine llamacpp` (a configured profile/build) or `--engine endpoint` (any OpenAI-compatible server, including Strata, Avalon, Lemonade and KoboldCpp). It reports cold prefill, warm prefill, decode, TTFT and draft acceptance from each server's own timings, which makes it the comparable row across engines.

```powershell
C:/AI/bat/benchmarks/benchmark_strata_avalon.bat
C:/AI/bat/benchmarks/benchmark_strata_avalon.bat --engines strata --samples 5
C:/AI/bat/benchmarks/benchmark_strata_avalon.bat --conversation --strata-resident-experts
python -m scripts.benchmarks.inference_engines.benchmark_coding_engines --engine llamacpp --profile swift15
```

Both arms serve the same Strata Swift IQ2_XS weights with the `strata_profiles` contract (long Python prefix, 128 tokens, temperature 0, seed 42), so their medians share one scope. The first sample per arm is discarded (`--warmup-samples`) because it pays the cold expert pages. Arms run sequentially; whatever holds a chosen port is stopped first, so a run never waits on a session. `--draft-n-max` sets Avalon's MTP depth; `--strata-resident-experts` and `--strata-cache-floor-mib` alter the Strata arm only.

## Feature parity, and why Avalon prefills slower

| Feature | Strata arm | Avalon arm | Blocking evidence |
| --- | --- | --- | --- |
| MTP speculation | on (`--spec 4`) | on (`--spec-type draft-mtp`, `--spec-draft-n-max 2`, `-md avalon/mtp/mtp-...gguf`) | Avalon's head is a separate 1.4 GiB NextN GGUF, not the 89 GiB pack. Strata's `mtp-q2_0.gguf` is `qwen4exp-mtp`, which Avalon rejects. |
| Expert cache | on (`--expert-cache auto`) | on (`--moe-cache auto`, `GGML_CUDA_MOE_CACHE_MIN_EXPERT_KB=1`) | the 1 MiB floor skips these ~512 KiB experts and the fork aborts (`MUL_MAT_ID with host weights outside a hosted MoE block`) instead of falling back to the CPU. |
| Expert residency | `--mmap-experts`, the A/B arm | VRAM pool + RAM experts | The arena's rate "depends on the OS page cache holding 34 GB"; 31 GiB RAM never fits it, so each prompt re-reads ~47 GB from SSD. `--resident-cpu-experts` keeps those experts in RAM instead. |
| Heat ranking | app-managed | none | `moe-cache-ranking.bin` ships only with Avalon's pack. |
| KV cache | `int8` | `q8_0`/`q8_0` | matched. |
| Prompt cache | on, parking refused | `--cache-ram 1024`, else off | Strata logged `0 reused + 3025 read` every sample: the 271 MiB snapshot plus the 2560 MiB floor exceeded the ~264 MiB free. Avalon defaults `--cache-ram` to 0 when the model exceeds RAM. |

## Measured

| Date | Engine | Cold prefill | Decode | TTFT | Draft acceptance |
| --- | --- | --- | --- | --- | --- |
| 2026-11-13 | llama.cpp `vulkan` b12363, `swift15` | 526 tok/s (3044-token prompt, 11.5 s) | 134.8 tok/s (199 fresh, 71 rewrite) | 0.118 s | 0.859 |
| 2026-11-13 | llama.cpp `rocm-lemonade` b1375, `swift15` | 129.5 tok/s (3044-token prompt, 46.7 s) | 149.6 tok/s (216 fresh, 83 rewrite) | 0.112 s | 0.937 |

- The 96K allocation costs ROCm four turns of prefill on the same 3044 tokens; at 64K it reads 551 against Vulkan's 526 tok/s, so ROCm collapses only between 64K and 96K. Decode splits by task class: 71-83 tok/s on the rewrite against 199-216 on fresh generation.
- The Strata arm runs again: 357 tok/s prefill and 46.2 decode over the 3025-token prefix, TTFT 8.5 s, startup 38 s, with no prompt reuse (`0 reused + 18185 read`). The earlier "cannot create the refill stream" exit no longer reproduces; the vision encoder's `WinError 5` is untested.

## Superseded measurements

Kept because it was once a decision basis. Do not mix it into a new table; re-run instead.

| Date | Engine | Cold prefill | Warm prefill | Decode | TTFT | Draft acceptance |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-11 | llama.cpp `rocm-lemonade` b1372, `swift15` | 119.8 tok/s (3046-token prompt, 38.1 s) | 113.2 tok/s | 45.5 tok/s | 0.141 s | 0.856 |
| 2026-11-13 | llama.cpp `vulkan` b12363, `swift15`, one sample | 139.1 tok/s (66-token prompt, 1.3 s) | 119.7 tok/s | 47.0 tok/s | 0.31 s | 0.793 |
| 2026-11-13 | llama.cpp `rocm-lemonade` b1375, `swift15`, one sample | 118.0 tok/s (66-token prompt, 1.5 s) | 95.6 tok/s | 47.9 tok/s | 0.37 s | 0.809 |

- A four-task corpus ran on both builds and `swift15-8k` on 2026-11-13 and gave up its place above: its median sat near the fresh-generation class, so only its prefill agrees. Its outputs stay in the run folders.
- Superseded by the 2026-11-13 harness change: pooled samples without a warm-up, so decode carried the ramp and its own samples span 31 to 126 tok/s. Two one-sample rows predate the warm-up. Warm prefill was dropped: a warm sample prefills only its cache miss.
- Evidence: `scripts/benchmarks/output/inference_engines/benchmark_coding_engines/unreviewed/1794441020487629300/artifacts/summary.txt`.

## Metric scope

Both arms report native server `timings`: prefill tok/s, decode tok/s and TTFT, plus parsed prompt-cache reuse per arm. HTTP request time is not decode throughput, and this is a paired screen, not a ranking. Every run records startup, warmup, samples, settings, failures and logs under `scripts/benchmarks/output/llm/`.

The retired llama.cpp build sweep (llama.cpp/Vulkan builds plus hipfire/TabbyAPI adapters) is archived in `C:/AI/trash/retired-llm-inference-sweep`.
