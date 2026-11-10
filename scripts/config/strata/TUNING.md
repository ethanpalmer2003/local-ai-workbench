# Strata tuning

Two backend profiles, both measured on this machine with the issue #3695 harness on 2026-10-26; a dated report link is still missing ([TODO](../../../notes/TODO.md))
(`scripts.benchmarks.inference_engines.benchmark_strata_reference`). Selection mechanics and the profile
files themselves are owned by the [backend configuration](README.md).

| profile | decode | cold prompt read | what it is |
| --- | ---: | ---: | --- |
| [decode.json](decode.json) | 36.9 tok/s | 187 tok/s | experts on the SSD page cache: fastest per generated token |
| [prefill.json](prefill.json) | 24.6 tok/s | 525 tok/s | 18 GiB of experts in RAM plus the reference env switches: fastest to read a fresh prompt |

- Pick by what the workload spends time on: a long fresh prompt wants the prefill profile; a long answer
  or many short turns in a warm session wants the decode profile. Cached prompt tokens cost neither arm,
  so reuse decides which side dominates.
- Default is `decode.json`; how to switch profiles, and where they are loaded from, is in the
  [backend configuration](README.md). `decode.json` carries `--resident-budget-gib 8` since 2026-11-09:
  without a budget its auto expert cache committed the pack and the benchmark's 1 GiB RAM floor stopped the
  arm. The budget makes the pair run, and the replay measured prefill ahead on both decode and prompt read
  ([screen](../../../notes/reviews/STRATA-PROFILES-2026-11-09.md)), so re-measure before preferring one profile.
- Experimental RX 7800 XT / 32 GB alternative: [reference profile, tests and limits](REFERENCE.md).
- Not measured: filled-context prefill beyond the screen above, speculation, and how the two profiles
  behave on a warm session with mixed read and generate. [TODO](../../../notes/TODO.md) owns the grids.
