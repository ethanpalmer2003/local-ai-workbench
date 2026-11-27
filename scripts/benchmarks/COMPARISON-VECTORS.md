# Comparison vectors

The dimensions a model result may vary on. One comparison holds every other vector fixed, names the one it
tests, and records the values it actually used, so a later run can tell which of them moved. Engine,
build, harness and model were already tracked per run; quantization, vendor quantization, weight layout,
MoE offload and the memory envelope are now named here as first-class axes.

| Vector | Values measured here | Owner |
| --- | --- | --- |
| Inference engine | llama.cpp, Strata, Avalon, Loom serve | [inference engines](inference_engines/README.md) |
| Engine build | llama.cpp `vulkan` b12602, `vulkan-1.0.0` b12359, `rocm-lemonade`, HRX; Strata control 0.1.60 | [builds](../config/llamacpp/BUILDS.md) |
| Compute backend | Vulkan, ROCm/HIP, HRX, CPU | `LLAMACPP_BUILDS` plus `--device` pin |
| Coding harness | Pi by default; littlecoder, ohmypi and nanocoder only on request | [coding agents](coding_agents/README.md) |
| Model | Swift-1.5 27B, Flash Next, Inkling-2-Mini; Qwen4 27B when released | [catalog](../config/models/catalog.json) |
| Tokenizer and template | GGUF-embedded chat template, `--jinja`, reasoning tags, vision projector absent or present | model metadata |
| Model quantization | IQ3_XXS, IQ2_XS, Q4_K_XL, Q8_K_XL, plus the file size it costs | catalog entry |
| Vendor quantization | Unsloth dynamic v3, ISTA GSQ-RCO, bartowski, ggml-org imatrix, LookAtMyQuant | catalog notes |
| Weight layout | mainline GGUF, vendor looped layout, `Mainline_Support` copy, matching drafter | catalog notes |
| MoE offload | expert layers resident on GPU, CPU-resident experts, mmap on or off | profile session options |
| Memory envelope | 16 GB VRAM on the pinned discrete adapter, 32 GB RAM; measured model, context and compute rather than file size | [tuning](../config/llamacpp/TUNING.md) |
| Context and KV | 32K/64K/96K occupancy and capacity, q8_0 or f16 KV, flash attention, slot count | profile plus INI |
| Speculation | MTP depth, ngram-mod, DSpark drafter, draft acceptance | profile plus INI |
| Reasoning and sampling | thinking effort and budget, temperature, top-p, top-k, min-p, seed | request settings |
| Tasks and repeats | `whitespace`, `duration`, `ledger`, `proverb`, polyglot suite; one or more repeats | task suite |
| Measurement scope | task wall time against server-reported TTFT, prefill and decode, with cache reuse stated | [benchmarks](README.md) |

## Future tests

- Quantization ladder per model at a matched memory budget: IQ3_XXS against Q2_K_XL and IQ4_XS.
- Vendor quantization head to head: Unsloth dynamic v3 against the ISTA GSQ-RCO build of the same model, and
  a LookAtMyQuant GGUF against both where one exists for this host.
- MoE offload ladder under the 16 GB card: resident experts against CPU-resident layers, decode and TTFT.
- Inkling 2 Mini quality on harder tasks; only wall time is measured so far.
- Loom inference once its Vulkan model preparation compiles.
