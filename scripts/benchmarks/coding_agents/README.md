# Coding-agent benchmarks

- Runner: `scripts.benchmarks.coding_agents.shared.benchmark_agents`; regression tests remain in `scripts/tests/cases/coding_agents/`.
- Shared runners compare Pi, LittleCoder, Oh My Pi and NanoCoder on identical English/code tasks.

```powershell
C:/AI/bat/benchmarks/benchmark_coding_agents.bat
C:/AI/bat/benchmarks/benchmark_coding_agents.bat --backends llamacpp strata
```

- Benchmark defaults: low reasoning; normal launchers use medium. Use the same prompt, model/profile, context, token/turn budget, client extension mode and task checkout.
- Each result records task seconds plus server-reported token totals, cached tokens, median TTFT, tokens prefilled, prefill tok/s, decode tok/s and draft acceptance. Raw per-request records, including every native `timings` block, stay in `logs/<backend>/<client>/<task>/<repeat>/requests.json`; `artifacts/comparison.md` carries the medians.
- Separate client correctness from speed. One easy task/repetition does not rank clients/models generally; client-injected instructions and different token totals are confounders.
- Strata/llama.cpp comparisons require matched native settings and recorded context/cache behavior. [Model/profile guide](../MODEL-COMPARISONS.md).
- Benchmark and update runs own the host: chosen ports are freed first, never reused or refused. Collect baseline/stage/process memory and owned-child cleanup.
- Source tasks and test contracts stay versioned; downloaded Aider Polyglot/other upstream tools remain in `frameworks/benchmarks`.
- Results: new `scripts/benchmarks/output/coding_agents/shared/benchmark_agents/`; historical `benchmark_frameworks/` and `scripts/tests/output/harnesses/` were superseded and retired to trash.
- Read compact summaries while waiting; preserve incomplete evidence. [Estimates](../../tests/notes/ESTIMATES.md), [outcomes](../../tests/notes/OUTCOMES.md), [test rules](../../tests/README.md).
- Additional grids/technical-Markdown workloads remain in the [TODO](../../../notes/TODO.md); no automatic resumption.
