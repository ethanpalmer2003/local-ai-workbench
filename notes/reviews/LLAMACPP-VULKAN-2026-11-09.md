# llama.cpp Vulkan freezes on repeated long generations

Draft report, not posted. Evidence from 2026-11-09 on this machine.

## Symptom

The Vulkan build of llama.cpp serves three 256-token generations and then stops answering. The request never returns and the server keeps its port; the last server line is a `sched_graph_realloc` message. Nothing in the response stream arrives, so the benchmark's request timeout is what ends the call.

## Reproduced with

| Setting | Runs that passed | Freeze |
| --- | --- | --- |
| swift15 profile, 8192 context, 256 tokens | warmup 1, warmup 2, sample 1 | sample 2 |
| swift15-8k profile, 8192 context, 256 tokens | warmup 1, warmup 2, sample 1 | sample 2 |
| swift15 profile, 4096 context, 256 tokens | warmup 1, warmup 2, sample 1 | sample 2 |
| swift15 profile, 4096 context, 32 tokens | five requests | none |

The same settings on the ROCm Lemonade build completed all three samples at 8192 context: 53.6, 43.4 and 51.6 tok/s, TTFT 0.26-0.28 s, 11.3 GiB peak.

## Reading

Not a capacity or profile effect: 4k and 8k behave the same, and both profiles carry the MTP/ngram arguments. Length matters, because 32-token generations survive five requests. A prompt-cache checkpoint accumulation followed by a graph reallocation is the visible step, so the draft hypothesis is that the rebuild after a few long outputs hangs.

## Local response

Benchmarks take the Lemonade build for repeated long generations and keep Vulkan runs short, with request and wall-clock budgets so a freeze ends the run. Retest after the next build change.

Evidence: `scripts/benchmarks/output/llamacpp/benchmark_context_stream/inconclusive/1794265265718855500` (freeze, Vulkan 8192), `1794265574615309200` (Lemonade pass).
