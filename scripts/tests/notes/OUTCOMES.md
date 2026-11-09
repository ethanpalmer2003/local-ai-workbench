# Experiment outcomes

## Classification

- `verified`: reviewed scoped result; `no-gain`: no justified change; `inconclusive`: insufficient/incomplete; `superseded`: corrected method replaced it; `unreviewed`: not reviewed. New runs default unreviewed.
- Historical artifacts retain their original settings/paths; completed evidence does not authorize reruns.

## Decisions and limits

- Paired easy Pi task: Strata Swift and 27B both passed 8/8; 31.84/79.03-second timings had different token totals/prefill costs. No general ranking.
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
