# Native llama.cpp benchmarks

- `benchmark_speedbench`: fresh generation / speculation; `benchmark_specspeed`: upstream source-copy/edit workload; `benchmark_ngram`: matched local copy/generation cases.
- `benchmark_context_stream`: context occupancy/cache behavior; `benchmark_llamacpp_profiles`: build/profile screen.
- Downloaded tools: `frameworks/benchmarks/{speed-bench,specspeed,club-rdna16}`. Project runners and English/code scope remain owned here.
- Native checks are live work. Match request/settings/order; warm up; record exact model/template/hash/reasoning and sampled resource baselines.
- Shared benchmark reasoning is low; normal launcher default is medium. Historical mixed/template-default reasoning cannot rank medium performance.
- Run from `C:/AI` with the project interpreter; use each module's CLI for bounded subsets. Package/source updates are separate.
- Backend sessions reuse only compatible healthy servers and preserve unrelated sessions. Occupied ports are refused unless the test explicitly owns them.
- Reports include timing, token/output correctness, failure/cleanup and memory evidence where available. New results remain under `benchmarks/output/llamacpp/`.
- [Model/profile screen](../MODEL-COMPARISONS.md), [settings and measured choices](../../config/llamacpp/TUNING.md), [benchmark rules](../README.md).
- Medium/high-context grids and repeated Vulkan variation investigations remain deferred in [TODO](../../../notes/TODO.md).
