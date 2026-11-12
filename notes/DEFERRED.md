# Deferred work

One index of what is parked, why, and what would revisit it. Machine-readable reasons stay with
their owners - the capability rows in [capability_matrix.py](../scripts/tools/capability_matrix.py),
the rebuild table in [UPSTREAM](UPSTREAM.md), the platform limits in [OPEN-QUESTIONS](OPEN-QUESTIONS.md) -
so this page links them instead of copying them.

| Parked | Kind | Why | Revisit when | Owner |
| --- | --- | --- | --- | --- |
| Fish Audio Drama 3 | model and all its work | its 15.9 GiB offload comparison and the Kobold Drama compare are heavier than this setup carries | a larger-memory target or a smaller conversion exists | [capability matrix](../scripts/tools/capability_matrix.py), [audit timing](../scripts/benchmarks/audit_timing.py) |
| HRX llama.cpp | build | patches exist, but upstream changes too fast to keep re-merging | upstream slows down, or a paired screen comes back | [UPSTREAM](UPSTREAM.md) |
| Avalon | framework updates | the fork trails stable llama.cpp and lost the paired screen | it earns another look | [updater](../scripts/download/frameworks/shared/other_updates.py) |
| HRX build row, llama.cpp backend benchmark | capability rows | one is the paused build, the other compares against it | HRX returns | [capability matrix](../scripts/tools/capability_matrix.py) |
| Drama offload screen | capability row | the model above is parked | the same condition as Drama 3 | [capability matrix](../scripts/tools/capability_matrix.py) |
| ExLlama family (hipfire, TabbyAPI) | frameworks | needs a Linux host with ROCm and EXL2/EXL3 weights | that host exists | [OPEN-QUESTIONS](OPEN-QUESTIONS.md) |
| Medium/high-context grids | work | follows the Vulkan freeze on long generations | Vulkan long generations work | [TODO](TODO.md), [draft](reviews/LLAMACPP-VULKAN-2026-11-09.md) |
| sdcpp ROCm runtime | runtime | not removed, the ROCm path is not exercised | the ROCm runtime is validated | [sdcpp guide](../scripts/config/sdcpp/README.md) |
| ComfyUI autotune, quality and scaling | work | closed with the TUNING record | a measured reason appears | [ComfyUI notes](../scripts/benchmarks/personal/comfyui/README.md) |
| ASR test execution, Handy and Kobold coverage | work | explicit deferral, not a gap | an explicit instruction | [ASR cases](../scripts/tests/cases/asr/README.md) |

Adding a row: name the thing, the reason it cannot start, and the condition that would start it.
A row leaves when the work is done or the reason no longer holds - not when it is forgotten.
