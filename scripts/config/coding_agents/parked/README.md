---
# Parked coding harnesses

Not in use, not imported, and not maintained: the code is kept because it worked and may come back, but
nothing here is tested, updated or launched. Pi is the only coding client this repository starts, tests and
updates; the parked entries name what a future reader would have to restore.

Parked on 2026-11-20:

| File | What it is | Why it is here |
| --- | --- | --- |
| `llamacpp_dsh.py` | DeepSeek Harness launcher: configures its route, profile and environment against a running llama.cpp server | DSH is not the client this repository uses |
| `llamacpp_littlecoder.py` | little-coder launcher entry point over `llamacpp_coding` | not the client in use |
| `llamacpp_ohmypi.py` | oh-my-pi launcher entry point over `llamacpp_coding` | not the client in use |
| `llamacpp_nanocoder.py` | nanocoder launcher entry point over `llamacpp_coding` | not the client in use |

## Rules

1. Nothing outside this folder imports anything inside it; the layout check fails a live module that does.
2. These files sit outside the maintained set, so the inventory, dead-code, annotation and docstring checks
   do not read them.
3. A new parked item is moved here, listed in the table above, and given a row in
   [deferred](../../../shared/deferred.yaml).

## What is still live

The client settings for these harnesses stay in `scripts/launchers/launcher_base.py`, and
`coding_clients.py` stays with `llamacpp_coding.py`, because the coding benchmark still measures those
clients. The DeepSeek Harness settings and its kill root in `scripts/launchers/kill_all_services.py` also
stay, so the service can still be stopped. Moving any of that here needs the benchmark's client arms retired
first; that work is in the TODO.

## Why these were retired

The [coding benchmark](../../../benchmarks/coding_agents/README.md) compared these harnesses against Pi on
the same weights, and Pi is what this host kept. None of them failed a check, so their evidence still stands
and any of them can be re-benchmarked rather than reconstructed.

## Re-benchmarking

1. A parked harness: move its entry point back, restore its arm in `CLIENTS` in
   `scripts/benchmarks/coding_agents/shared/benchmark_agents.py`, and set `in_use=True` on its updater row in
   `scripts/download/frameworks/shared/other_updates.py`.
2. A new harness: add its settings to `scripts/launchers/launcher_base.py`, one arm to `CLIENTS`, and a
   `ToolSpec` row so the updater tracks it.
3. Run `bat/benchmarks/benchmark_coding_agents.bat`; every arm is measured on the same weights and the run
   records its provenance, so the comparison is repeatable later.

## Unparking

1. Move the file back into `scripts/launchers/llamacpp/` and add it to the table's removal.
2. Restore whatever the file imported: the launcher target list in the live suite, the kill list in
   `scripts/launchers/kill_all_services.py`, and the settings in `launcher_base.py` if they were parked too.
3. Run `python -m scripts.review` and the model-free suite, then the live launcher suite once the client is
   installed again.
