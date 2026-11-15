# llama.cpp builds and their faults

Installed tags change with `update_frameworks`; a fault recorded here is what this machine saw on that exact
tag, not a claim about the commit. Tuning that follows from a fault lives in [TUNING.md](TUNING.md), and the
symptom index is [upstream](../../../notes/UPSTREAM-INDEX.md).

| Build | Symptom | Response |
| --- | --- | --- |
| Vulkan b12421, b12422 (2026-11-15) | A multi-text `/v1/embeddings` request exits with `0xC0000005` (access violation) four inputs in, on both tags; single-text requests of the same strings run 400 times, and generation is untested against them | The embedding server runs ROCm instead; [similarity](../../review/SIMILARITY.md) |
| Vulkan b12422, generation | The 27B coding model server exits with `0xC0000005` (access violation) while re-prefilling a 3,707-token prompt, after `memory_seq_rm [0, end)` and with no error line of its own; reproducible at 32K and at the profile's own context, so the Pi client sees only `502 Backend request failed` | The 27B arm cannot be benchmarked on this tag; roll back before relying on it. The access violation is the same status the batched embedding request returns, so suspect one memory bug in the build rather than two | [coding benchmark](../../benchmarks/coding_agents/README.md) |
| Vulkan b12363 (2026-11-13) | No fault seen in six 512-token generations at 16k and 32k; the build before it froze on the fourth 256-token generation | Request budget stays the guard; [draft](../../../notes/reviews/LLAMACPP-VULKAN-2026-11-09.md) |
| ROCm b1377 (2026-11-15) | Aborts during device fit in `common_fit_params` while the Ryzen iGPU is visible | `HIP_VISIBLE_DEVICES=0`, which the [`rocm-lemonade` build selection](../../launchers/launcher_config.py) and the embedding settings both apply |
| ROCm b1373, b1375 | Same abort with `ROCm error: unspecified launch failure`, `current device: -1` | Same escape hatch; b1372 tolerated the iGPU; [note](../../../notes/reviews/ROCM-DRIVER-TIMEOUT-2026-11-13.md) |

The pattern worth keeping: a batched request is what both llama.cpp faults here have needed, so a screen that
sends one prompt at a time says nothing about them.

The nearest upstream report is [ggml-org/llama.cpp#12836](https://github.com/ggml-org/llama.cpp/issues/12836),
"crash when `-b` > `-ub` with embeddings", closed by
[#17912](https://github.com/ggml-org/llama.cpp/pull/17912), which clamps `n_batch` to `n_ubatch` at startup. That
one raises a `GGML_ASSERT` about non-causal attention, so it does not describe b12421: this server runs with
`-b` equal to `-ub`, and the failure is a silent access violation rather than an assertion.

