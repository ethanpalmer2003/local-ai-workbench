# Benchmarks

Benchmark runners and their timing support live here, separate from correctness and smoke tests in `scripts/tests`.

- Strata vs Avalon on the same weights: [llm/](inference_engines/README.md) (`bat/benchmarks/benchmark_strata_avalon.bat`); reports native prefill, decode and TTFT medians per arm.
- Coding agents: [coding_agents/](coding_agents/README.md) (`bat/benchmarks/benchmark_coding_agents.bat`).
- Language practice vs Lemonade (`bat/benchmarks/benchmark_framework_compare.bat`): chat, Kokoro speech and recognition on the pinned corpus, one stack at a time. Every long run records [provenance](shared/provenance.py) so a later run can tell what changed.
- The llama.cpp build sweep (`benchmark_llm_inference`) is retired; its sources are archived in `C:/AI/trash/retired-llm-inference-sweep`.

New runs go under `scripts/benchmarks/output`; media-generation areas (`sdcpp`, `comfyui`) nest under `output/personal/`. `tts_engines`, `asr` and `koboldcpp` stay at the root because the same engines serve language practice. Existing evidence stays at its historical path.

`shared/benchmark.py` owns timing across ASR, TTS, language models and images. Adapters own loading, request protocols and task-owned cleanup.

The [model inventory](../download/models/METADATA.md) can index existing reports
as measured metadata, separately from declared capabilities and published quality.
Record exact checkpoint, runtime/device/settings, corpus, execution context and
resource-counter scope. Never replace missing memory counters with file size.

1. Create `BenchmarkLifecycle` with an identity tied to the actual process and loaded model.
2. `prepare(startup, load)` records separate phases when observable. Use `combined=True`
   when startup and loading cannot be separated. `adopt_prepared` imports a measured
   setup interval from an existing runner; never estimate or subtract loading costs.
3. Run `warmup`. For lazy loading use `includes_model_load=True`; that phase is
   explicitly loading plus first inference, never pure loading.
4. Wrap requests with `measure` or `request`. Keep input preparation and artifact
   writing outside the timed callback where possible. Record the boundary when an
   adapter includes serialization, decoding or saving.
5. Record first output with `timing.mark("first_output")` for streaming. Total request
   duration alone does not measure interactive streaming latency.
6. Preserve `record()` including failures; clean up owned processes in `finally`
   or with the lifecycle context manager. Never terminate an unrelated session.

Only completed `resident_request` rows qualify for `summarize_requests`.
Warmup, startup, model loading, cleanup, failed requests and old wall-time samples
are excluded. p95 requires 20 samples. Retain native decode/kernel metrics as separate
fields; HTTP request time is not decode throughput.

`resident_http.py` provides a task-owned persistent HTTP process for any domain.
It refuses occupied ports. A model reload within the same PID must change the
adapter identity; the lifecycle cannot discover hidden server-side reloads.

`fork()` gives concurrent API requests independent recorders tied to the verified
warmed session. Identity checks run outside request timing. `accept=` rejects
backend error responses without ranking them as successful requests.
`measure_cold_process` records only a process total; unobservable startup/loading/
inference fields remain null. It never qualifies as resident speed.
`workflow_timing` similarly records pipeline totals when runtime offloading/loading
cannot be isolated; ComfyUI uses this scope rather than claiming resident inference.

Run `python -m scripts.benchmarks.audit_timing` to review timed sources. Model-free correctness and functional smoke tests stay in `scripts/tests`; they do not belong to performance rankings.
Historical evidence is immutable. Cold CLI probes remain useful compatibility checks, but cannot establish resident speed rankings.
