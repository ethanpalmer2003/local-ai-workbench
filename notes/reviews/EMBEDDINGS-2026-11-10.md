# Embedding screen: near-duplicate Markdown

Screen, not a ranking. Evidence from 2026-11-10 on this machine.

## What ran

Every bullet and sentence in the 121 maintained Markdown documents, embedded through llama.cpp's
embeddings endpoint: first EmbeddingGemma-2 Q8_0 (768 dimensions, mean pooling), then
Qwen3-Embedding-0.6B Q8_0 (1024 dimensions, last-token pooling). Same 1,439 units after filtering:
tables and code fences dropped, procedural lines allowlisted, units under 8 words dropped. A section
pair needs two matching units or one unit of 25+ words.

| threshold | EmbeddingGemma-2 | Qwen3-Embedding-0.6B | shared |
| --- | ---: | ---: | ---: |
| 0.92 | 20 | 11 | 4 |
| 0.90 | 49 | 22 | 10 |
| 0.88 | 116 | 56 | 22 |
| 0.85 | 420 | 163 | 85 |

Both models surface the same structural noise first; the filters removed it. Agreement on the rest is
low (Jaccard about 0.16 at every threshold), so the model choice changes what is found.

## Reading

- Gemma finds about twice as much at the same threshold, is smaller (310 MB against 639 MB) and is no
  slower here. A sample of eight of its 49 pairs at 0.90 all showed real duplication or drift.
- The most valuable find is not a duplicate: `notes/NATIVE-VALIDATION.md` records 284 model-free
  regressions while `ASR-PRACTICE-ALTERNATIVES.md` records 356, the same fact restated and stale.
- Qwen is quieter at equal threshold and misses findings Gemma reports, so it stays a cross-check at
  0.95 rather than the primary model.
- Thresholds do not carry between models: Qwen sits lower overall, so its band is not Gemma's.

## If this holds

EmbeddingGemma-2 at 0.90 with the two-unit rule is the working setting, kept as an opt-in check with no
gate: a finding is a pair to review, never an edit. If the review load grows, narrow the band before
dropping documents, because the real finds cross evidence and normative docs.

## Code screen

The same model over one function per chunk (1,607 functions, tests skipped) found five pairs at
0.95. One was real duplication: both Strata benchmarks carried their own streaming request, now
merged into `benchmark_requests.stream_chat`. The other four are distinct owners: two launcher CLI
shims, a context-manager factory and its inner function, and the dynamic-VRAM adapter with its
inverse.

Evidence: `scripts/state/generated/shared/similarity/` (each run) and `data/embeddings/` (vectors, model
digest, pairs). No default changed; nothing gates.
