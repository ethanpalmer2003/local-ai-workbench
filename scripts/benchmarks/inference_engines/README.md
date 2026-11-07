# Strata vs Avalon inference benchmark

- Runner: `scripts.benchmarks.inference_engines.benchmark_strata_avalon`; entry `C:/AI/bat/benchmarks/benchmark_strata_avalon.bat`.
- Answers "which engine is faster, and in which phase"; the [coding-agent benchmark](../coding_agents/README.md) answers "does the agent finish the task".

```powershell
C:/AI/bat/benchmarks/benchmark_strata_avalon.bat
C:/AI/bat/benchmarks/benchmark_strata_avalon.bat --engines strata --samples 5
C:/AI/bat/benchmarks/benchmark_strata_avalon.bat --conversation --strata-resident-experts
```

Both arms serve the same Strata Swift IQ2_XS weights with the `strata_profiles` contract (long Python prefix, 128 tokens, temperature 0, seed 42, reasoning off), so decode, prefill and TTFT medians share one native scope. The first sample per arm is discarded (`--warmup-samples`) because it pays the cold expert pages. Arms run sequentially; whatever holds a chosen port is stopped first, so a run never waits on a session. `--draft-n-max` sets Avalon's MTP depth; `--strata-resident-experts` and `--strata-cache-floor-mib` alter the Strata arm only.

## Feature parity, and why Avalon prefills slower

| Feature | Strata arm | Avalon arm | Blocking evidence |
| --- | --- | --- | --- |
| MTP speculation | on (`--spec 4`) | on (`--spec-type draft-mtp`, `--spec-draft-n-max 2`, `-md avalon/mtp/mtp-...gguf`) | Avalon's head is a separate 1.4 GiB NextN GGUF, not the 89 GiB pack. Strata's `mtp-q2_0.gguf` is `qwen4exp-mtp`, which Avalon rejects. |
| Expert cache | on (`--expert-cache auto`) | on (`--moe-cache auto`, `GGML_CUDA_MOE_CACHE_MIN_EXPERT_KB=1`) | the 1 MiB floor skips these ~512 KiB experts and the fork aborts (`MUL_MAT_ID with host weights outside a hosted MoE block`) rather than fall back to the CPU. |
| Expert residency | `--mmap-experts`, the A/B arm | VRAM pool + RAM experts | The arena's rate "depends on the OS page cache holding 34 GB"; 31 GiB RAM never fits it, so each prompt re-reads ~47 GB from SSD. `--resident-cpu-experts` keeps those experts in RAM instead. |
| Heat ranking | app-managed | none | `moe-cache-ranking.bin` ships only with Avalon's pack. |
| KV cache | `int8` | `q8_0`/`q8_0` | matched. |
| Prompt cache | on, parking refused | `--cache-ram 1024`, else off | Strata logged `0 reused + 3025 read` every sample: the 271 MiB snapshot plus the 2560 MiB floor exceeded the ~264 MiB free. Avalon defaults `--cache-ram` to 0 when the model exceeds RAM. |

## Metric scope

Both arms report native server `timings`: prefill tok/s, decode tok/s and TTFT, plus parsed prompt-cache reuse per arm. HTTP request time is not decode throughput, and this is a paired screen, not a ranking. Every run records startup, warmup, samples, settings, failures and logs under `scripts/benchmarks/output/llm/`.

The retired llama.cpp build sweep (llama.cpp/Vulkan builds plus hipfire/TabbyAPI adapters) is archived in `C:/AI/trash/retired-llm-inference-sweep`.
