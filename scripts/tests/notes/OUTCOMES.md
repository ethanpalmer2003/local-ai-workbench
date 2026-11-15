# Experiment outcomes

## Classification

- Outcomes and their meanings: [execution and reporting](../EXECUTION-AND-REPORTING.md); new runs default unreviewed.
- Historical artifacts retain their original settings/paths; completed evidence does not authorize reruns.

## Decisions and limits

- Paired easy Pi task: Strata Swift and 27B both passed 8/8; 31.84/79.03-second timings had different token totals/prefill costs. No general ranking.
- Strata-only agent round, 2026-11-15, engine 0.1.59 with control 0.1.60, decode profile, one repeat each: `proverb` passed 1/1 on all four clients (pi 74.1 s, littlecoder 120.7, nanocoder 93.3, ohmypi 227.9); `ledger`, the two-file output-format task, also passed 1/1 on all four (pi 144.0 s, littlecoder 225.1, nanocoder 142.9, ohmypi 423.9). `ohmypi` reported no token totals in either task, so its wall time is the only comparable figure. The 27B arm was not run, so neither task is a ranking; the easy pair above is the only one. Evidence: `benchmarks/output/coding_agents/shared/benchmark_agents/unreviewed/1794767657491819500` (proverb) and `.../1794768206418512400` (ledger).
- Four-client easy tasks tied supplied-test quality; observed fastest client varied by task. Historical harness output was superseded by the [current coding-agent benchmark](../../benchmarks/coding_agents/README.md) and retired to trash.
- MTP depth 2 and ngram 24/48/64 have bounded short-task support. [Settings/evidence](../../config/llamacpp/TUNING.md).

## Delivery and transport outcomes

Rocinante/Gemma delivery, SSE transport and Ming listening impressions moved to [OUTCOMES-DELIVERY-TRANSPORT.md](OUTCOMES-DELIVERY-TRANSPORT.md).

## Breeze Q4_0 backend screen

- Default-voice RTF: Vulkan 0.552, old ROCm 0.620, current ROCm 0.681; Vulkan used less sampled process VRAM. Listening quality was not graded.
- Backend evidence (../output/probes/audiocpp_backend_compare/).

## llama.cpp warmed short-context stream

- Vulkan/Lemonade varied across short 512-token requests; actual occupied context was tiny. This does not establish the deferred filled-context comparison.

## Drama 3 Q2 CPU expert offload

- Longer-speech screen: 28 layers RTF 1.21/9.11 GiB peak; 40 layers 1.38/6.12 GiB. Neither reached real time; one sample and differing audio lengths limit ranking. User selected 40 layers/2048 context.
- Offload evidence (../output/probes/drama3_offload/).

## Drama 3 with resident Rocinante

- Idle-residency comparison retired as evidence for active overlap. Replacement baseline must record simultaneous generation, queue delay and underruns.

- [Future experiments](audiocpp/AUDIOCPP-OPTIMIZATIONS.md), [pending work](../../../notes/TODO.md).
