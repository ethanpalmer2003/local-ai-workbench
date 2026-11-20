# llama.cpp builds and their faults

Installed tags change with `update_frameworks`; a fault recorded here is what this machine saw on that exact
tag, not a claim about the commit. Tuning that follows from a fault lives in [TUNING.md](TUNING.md), and the
symptom index is [upstream](../../../notes/UPSTREAM-INDEX.md).

| Build | Symptom | Response |
| --- | --- | --- |
| Vulkan b12590 (2026-11-20) | Clean on both faults: a 24-text `/v1/embeddings` request returns 200 with 24 vectors, and the 27B server takes a short prompt and then a 3.7K-token re-prefill without exiting | Now the default (`vulkan`); the regression was fixed after b12422 |
| Vulkan b12421, b12422 (2026-11-15) | A multi-text `/v1/embeddings` request exits with `0xC0000005` (access violation) four inputs in, on both tags; single-text requests of the same strings run 400 times, and generation is untested against them | The embedding server ran ROCm instead; [similarity](../../review/SIMILARITY.md) |
| Vulkan b12422, prefill | The 27B server exits with `0xC0000005` while re-prefilling a 3,707-token prompt, after `memory_seq_rm [0, end)` and with no error line of its own; reproduced at 32K and at the profile's own context, and with speculation off (`swift15-nospec` sends `--spec-type none` and still exits at the same point), so the Pi client sees only `502 Backend request failed`. Turning flash attention off is not testable here: `swift15-nofa` exits 1 at startup | The 27B arm could not be benchmarked on these tags; it ran both tasks on ROCm instead. The access violation is the same status the batched embedding request returns, so suspect one Vulkan memory fault in the build rather than two | [coding benchmark](../../benchmarks/coding_agents/README.md) |
| Vulkan 1.0.0 (b12359, 2026-11-13) | Clean on both failures: a 24-text `/v1/embeddings` request returns 200 with 24 vectors, and the 27B Pi `proverb` run completes in 36.3 s at 371 tok/s prefill and 32.8 decode | Kept as the `vulkan-1.0.0` build pin, so the regression is bracketed: it landed after 1.0.0 and before b12421 | [release](https://github.com/ggml-org/llama.cpp/releases/tag/v1.0.0) |
| Vulkan b12363 (2026-11-13) | No fault seen in six 512-token generations at 16k and 32k; the build before it froze on the fourth 256-token generation | Request budget stays the guard; [draft](../../../notes/reviews/LLAMACPP-VULKAN-2026-11-09.md) |
| ROCm b1377 (2026-11-15) | Aborts during device fit in `common_fit_params` while the Ryzen iGPU is visible | `HIP_VISIBLE_DEVICES=0`, which the [`rocm-lemonade` build selection](../../launchers/launcher_config.py) and the embedding settings both apply |
| ROCm b1373, b1375 | Same abort with `ROCm error: unspecified launch failure`, `current device: -1` | Same escape hatch; b1372 tolerated the iGPU; [note](../../../notes/reviews/ROCM-DRIVER-TIMEOUT-2026-11-13.md) |

Selection: `LLAMACPP_DEFAULT_BUILD` is the rolling `vulkan` build: b12590 returned 200 for a 24-text
`/v1/embeddings` request and for a 27B 3.7K-token re-prefill (2026-11-20), the two faults that held the pin.
`LLAMACPP_CODING_BUILD` and `LLAMACPP_EMBEDDINGS_BUILD` override it per use; `vulkan-1.0.0` stays as the
fallback.

The RDNA build runs from an explicit flag: `update_frameworks --build rdna` rebuilds it after the update pass,
and `test_full.bat --build rdna` forwards that. It builds llama.cpp at the patch set's `release.json` `base`
(4f9dfa0e3 for v17-r327) with `-DGGML_HIP=ON -DGPU_TARGETS=gfx1101`, and needs the Windows SDK bin on PATH for
the link's `mt.exe`. On the 27B, Vulkan wins wall time (21.2 against 32.6 s, 51.0 against 100.2 s): this build
prefills at under half the rate, though it decodes faster; [outcomes](../../tests/notes/OUTCOMES.md).

Both faults here needed a batched request, so a one-prompt screen says nothing about them. The nearest upstream
report is
[ggml-org/llama.cpp#12836](https://github.com/ggml-org/llama.cpp/issues/12836) with
[#17912](https://github.com/ggml-org/llama.cpp/pull/17912) closing it: a `-b` > `-ub` assert, not this silent
access violation.

