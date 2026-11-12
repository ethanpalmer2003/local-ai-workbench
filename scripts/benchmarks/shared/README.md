# Shared benchmark support

Every runner in this tree reads its measurement rules from here, so a result from one area means
the same thing as a result from another. Area runners stay in their own folder.

- `benchmark.py` owns the lifecycle (setup, load, warmup, measure, cleanup) and gates what counts
  as a completed sample; `resident_http.py` is the HTTP client for a resident server.
- `reporting.py` writes the report shape; `provenance.py` stamps the model, framework and producing-
  script state a run used; `framework_compare.py` drives two frameworks on one corpus.
- `timing.py`, `vram.py`, `paths.py`, `preflight.py` and `language_corpus.py` are the leaves:
  clocks, memory sampling, output paths, refusal before a bad run, and the corpora.
- Contracts: [benchmark guide](../README.md); results: [MODEL-COMPARISONS](../MODEL-COMPARISONS.md).
