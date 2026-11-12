# Deferred work

An index of what is parked. The reason each thing cannot start stays with its owner - the
capability rows in [capability_matrix.py](../scripts/tools/capability_matrix.py), the rebuild table in
[UPSTREAM](UPSTREAM.md), the platform limits in [OPEN-QUESTIONS](OPEN-QUESTIONS.md) - so this page
records only what is parked, where the reason lives, and what would start it.

| Parked | Kind | Revisit when | Reason lives in |
| --- | --- | --- | --- |
| Fish Audio Drama 3, and every comparison of it | model | a larger-memory target or a smaller conversion exists | [capability matrix](../scripts/tools/capability_matrix.py), [audit timing](../scripts/benchmarks/audit_timing.py) |
| HRX llama.cpp | build | upstream slows down, or a paired screen comes back | [UPSTREAM](UPSTREAM.md) |
| HRX build capability row | row | HRX returns | [capability matrix](../scripts/tools/capability_matrix.py) |
| llama.cpp backend benchmark | row | HRX returns | [capability matrix](../scripts/tools/capability_matrix.py) |
| Avalon | framework | it earns another look | [updater](../scripts/download/frameworks/shared/other_updates.py) |
| ExLlama family (hipfire, TabbyAPI) | framework | a Linux host with ROCm and EXL2/EXL3 exists | [OPEN-QUESTIONS](OPEN-QUESTIONS.md) |
| Medium/high-context grids | work | Vulkan long generations work | [TODO](TODO.md), [draft](reviews/LLAMACPP-VULKAN-2026-11-09.md) |
| sdcpp ROCm runtime | runtime | the ROCm runtime is validated | [sdcpp guide](../scripts/config/sdcpp/README.md) |
| ComfyUI autotune, quality and scaling | work | a measured reason appears | [ComfyUI notes](../scripts/benchmarks/personal/comfyui/README.md) |
| ASR test execution, Handy and Kobold coverage | work | an explicit instruction | [ASR cases](../scripts/tests/cases/asr/README.md) |

Adding a row: name the thing, say where the reason lives, and name the condition that would start
it. A row leaves when the work is done or the condition no longer holds - not when it is forgotten.
