# KoboldCpp benchmarks

Two measurements that need a KoboldCpp stack: the Drama3 chat comparison against the same job in
llama.cpp, and the stack's VRAM floor. Results and caveats: [MODEL-COMPARISONS](../MODEL-COMPARISONS.md).

- `drama3_kobold_compare.py` runs the Drama3 offload pair and reports resident VRAM, decode and
  time to first token for each arm.
- `kobold_stack_vram.py` measures the floor with no model resident, so a later arm can assert it.
- Server contract and ports: [launcher settings](../../launchers/launcher_config.py); report
  shape: [reporting](../shared/reporting.py).
