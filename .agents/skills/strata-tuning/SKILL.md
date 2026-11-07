---
name: strata-tuning
description: Use when the user wants Strata faster, asks which Strata settings or profile to use, or wants a decode/prefill comparison on this machine. Covers the measured profile pair, the reference harness and the safe order of knob changes.
---

# Tuning Strata on this box

Hardware ceiling: RX 7800 XT 16 GB, 31 GiB RAM. Any claim needs a measured pair, never a single run.

## Two delivered profiles

| profile | decode | cold prompt read |
| --- | ---: | ---: |
| [decode](../../../scripts/config/strata/decode.json) | ~37 tok/s | ~187 tok/s |
| [prefill](../../../scripts/config/strata/prefill.json) | ~22 tok/s | ~525 tok/s |

- Prefill wins when fresh tokens are roughly 2-4x the output tokens, which is normal codebase work; decode wins for long single-shot output.
- Prefill gain comes from RAM-resident experts plus the reference env switches, not from `--spec`.

## Measure

```powershell
# issue #3695 protocol: warm decode runs, cold prompt read, cache reuse
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.benchmarks.inference_engines.benchmark_strata_reference --strata-config <a> --strata-config <b>
# agent wall time, matched prompts
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.benchmarks.coding_agents.shared.benchmark_agents --backends strata --tasks proverb --repeats 1 --strata-config <a>
```

Both run the shared preflight and free their own ports.

## Knobs, in order of effect

1. `--resident-budget-gib` (RAM experts) and `--vram-reserve-mib` (VRAM tier): the largest lever, prefill and decode trade off.
2. `-ngl`: less GPU offload frees VRAM for TTS/image, slows the LLM.
3. `--spec 2` beats `--spec 4` here; `--kv k8v4`, `--cache-reuse 256` are cheap.
4. Context size: decode is flat between 64K and 131K on this card.

Change one knob per run; matched offload, KV type and context or the comparison means nothing. Details: [llm guide](../../../scripts/benchmarks/inference_engines/README.md), [config guide](../../../scripts/config/strata/README.md).
