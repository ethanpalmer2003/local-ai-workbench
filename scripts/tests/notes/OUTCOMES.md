# Experiment outcomes

## Classification

- Outcomes and their meanings: [execution and reporting](../EXECUTION-AND-REPORTING.md); new runs default unreviewed.
- Historical artifacts retain their original settings/paths; completed evidence does not authorize reruns.

## Decisions and limits

- Paired easy Pi task: Strata Swift and 27B both passed 8/8; 31.84/79.03-second timings had different token totals/prefill costs. No general ranking.
- MTP depth/gate sweep, 2026-11-15, 27B on the pinned Vulkan 1.0.0, one round each, 32K prompt:
  the shipped `spec-draft-n-max 2` with no `p-min` was best or tied on both workloads (47.8 tok/s
  generation, 50.8 on the 32K rewrite, acceptance about 0.70). Deeper drafts lost: depth 3 read 40.7
  and 44.5, depth 4 43.1 and 45.6. The gate raised acceptance as documented upstream (0.55 to 0.88) but
  never raised throughput, and its one apparent gain (48.9 on short generation at `p-min 0.6`) came with
  40.3 on the rewrite, which is single-sample variance. One round, so 2-4% gaps are not decided; nothing
  justifies moving off depth 2. Output `benchmarks/output/llamacpp/benchmark_ngram/unreviewed/1794780309255370400`.
- MTP at 96K, 2026-11-15, 27B on the pinned Vulkan 1.0.0, one arm per depth: depth 2 ungated decoded
  31.7 tok/s at 96,114 prompt tokens with acceptance 0.85, against about 50 at a 32K prompt, and the 96K
  prefill alone took roughly 410 s; the `p-min 0.6` arm read 32.1, so the gate changes nothing. Against the
  32K sweep that is a third less decode and a fourfold wall time. Output
  `benchmarks/output/llamacpp/benchmark_ngram/unreviewed/1794782005118321900`.
- Deep-context rewrite, 2026-11-15: the graded rewrite passes at 32K, at 40K (142.8 s, 34.8 tok/s) and at
  64K, and the answers there carry the function followed by `<think>` prose, which the old exact-parse grader
  marked wrong; grading now compares the longest parsable prefix. At 96K the answer collapses: with reasoning
  on it is 46 tokens of `<think>` and no code, identically across three runs and with a 128- or 512-token
  budget, and with `swift15-noreason` it is a 17-token fragment of the function, both far short of the
  allowance. The deep allocation truncates generation itself rather than the think path, and the output budget
  is ruled out.
- Long-context read check, 2026-11-15, 27B on ROCm b1377, one warmup and one sample per capacity, 3,044-token prompt: cold TTFT 5.55 s at 64K and 26.01 s at 96K, which is 548 against 117 tok/s prefill, while decode stayed flat at 60.6 and 62.5 tok/s. The 64K-to-96K cliff reproduces on b1377 and matches the 2026-11-13 pair on b1375; outputs `benchmarks/output/llamacpp/benchmark_context_stream/inconclusive/1794778187678735400` (64K) and `.../1794778208574993200` (96K).
- KV precision screen, 2026-11-15, 27B on the ROCm Lemonade build, `proverb`, Pi, 32K: q8 KV finished in 23.2 s with 59.6 tok/s decode and 510 prefill; `swift15-f16-kv` finished in 32.1 s with 35.1 decode and 584 prefill. f16 trades 41% of decode for 14% more prefill, so q8 stays the default. It also fits at 32K on this card, which the profile never assumed.
- Strata-only agent round, 2026-11-15, engine 0.1.59 with control 0.1.60, one repeat each: `proverb` passed 1/1 on all four clients (pi 74.1 s) and `ledger` passed 1/1 (pi 144.0 s); `ohmypi` reported no tokens, so only its wall time compares. Evidence: `benchmarks/output/coding_agents/shared/benchmark_agents/unreviewed/1794767657491819500` (proverb) and `.../1794768206418512400` (ledger).
- Strata against the 27B, Pi client, 2026-11-15, one repeat each, both at 32K context: the 27B won both tasks on wall time: `proverb` 23.2 s against Strata's 74.1 s, `ledger` 59.3 s against 144.0 s, with similar token totals on `proverb` (24,472 against 23,253). The 27B arm used the ROCm Lemonade build because Vulkan b12422 crashed it mid-prefill; 500-510 tok/s prefill, 54.8-59.6 decode, 61-74% draft. Evidence: `.../benchmark_agents/unreviewed/1794774061977902600` (proverb) and `.../1794774099840651000` (ledger). This ranks wall time for two tasks, not model quality.
- Four llama.cpp builds, 2026-11-20, 27B, Pi, one repeat, 32K, all passing both tasks: unpatched ROCm Lemonade (b12579) 19.0 s and 56.4 s at 529-536 tok/s prefill, 64.6-65.4 decode; RDNA-boosts ROCm (base 4f9dfa0e3, b12387 plus 18 patches) 32.6 s and 100.2 s at 221-377; RDNA-boosts Vulkan (same patches, built locally) 30.4 s and 50.7 s at 367-503; plain Vulkan b12590 21.7 s and 60.1 s at 457-474. The patched Vulkan arm trades the two tasks (slower `whitespace`, faster `ledger`), `ledger` noise is about 10 s on one repeat, and the ROCm arm loses outright, so both are parked.
- 27B on the rolling Vulkan b12590, 2026-11-20, Pi client, one repeat each, 32K context: both local tasks passed, `whitespace` in 23.2 s and `ledger` in 65.9 s (26,587 tokens, 447 tok/s prefill, 48.1 decode, 66% draft acceptance). The pinned 1.0.0 could not run this arm; on ROCm the same pair is 0.4 s slower on `whitespace` and 6.6 s slower on `ledger`. The Strata arm could not start: its control python failed with `[WinError 5]` before serving (the 0.1.60 image-encoder fault), so the pair stays unpaired until that install is fixed. Evidence: `benchmarks/output/coding_agents/shared/benchmark_agents/unreviewed/1795211588854486000`.
- Strata against the 27B, 2026-11-21, Vulkan b12602, Pi, one repeat, 64K: both passed both tasks. Strata median 60.4 s at 162/30.0 tok/s and 33,978 tokens against 43.6 s at 468/55.2 and 23,782; Strata won `ledger` (62.6 against 67.5) and lost `whitespace`. Profiles no longer pass `--vision`: the 0.1.60 control died on an empty `vision.exe`. Evidence: `benchmarks/output/coding_agents/shared/benchmark_agents/unreviewed/2026-11-21/1795292395860939600`.
- Four-client easy tasks tied supplied-test quality; the fastest client varied by task. Historical output was superseded and retired to trash.
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
