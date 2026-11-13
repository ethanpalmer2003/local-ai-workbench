# ROCm crash surfaces as an AMD driver timeout

Dated evidence, 2026-11-13, this machine: RX 7800 XT plus an integrated GPU, Windows.

## What happens

llama.cpp ROCm (Lemonade release) enumerates both GPUs, then dies while building the context:

```
llama_context: n_ctx = 32768, flash_attn = enabled
E ROCm error: unspecified launch failure
E   current device: -1, in function ggml_cuda_set_device (ggml-cuda.cu:130)
E   hipGetDevice(&current_device)
```

The process exits `0xC0000409`. b1373 and b1375 both do this; b1372 loads and ran the coding arm at 119.8 tok/s on 2026-11-11.

## On the desktop

AMD Adrenalin shows a driver-timeout notification at the same moment. Nothing else records it: no Event ID 4101 in the System log for the last two days and no AMD provider entry in the Application log. `TdrDelay` and `TdrDdiDelay` are both 8 s, raised from the 2 s default, so a two-second watchdog is not what fires.

## Reading

`unspecified launch failure` next to `current device: -1` means the HIP call ran with no usable device: the context was already lost. Enumeration succeeding while context creation fails points at the ggml-cuda/HIP path that changed between b1372 and b1373, not at a driver that vanished. The Adrenalin toast is the driver recovering after the fault, so it is a symptom rather than the cause.

## Confirmed cause

The second ROCm device is the Ryzen iGPU, and it reports system RAM as free VRAM. The backend initializes every visible device, so a build that leaves both visible faults while the context is built. Masking it fixes the load:

| Attempt | Result |
| --- | --- |
| b1375, both devices visible | dies at context build, `current device: -1` |
| b1375, `--device ROCm0` | still dies; the log shows the card selected, so placement is not the fault |
| b1375, `HIP_VISIBLE_DEVICES=0` | loads and decodes at 51-56 tok/s on the discrete card |
| b1372, both devices visible | loaded, so the tolerance for the second device is what changed after b1372 |

The build entry now carries the mask, so launchers and benchmarks inherit it.

## Data scope

The iGPU is not a tested device and no measurement here uses it: the mask is set on the build, so every run records one adapter, and the VRAM sampler attributes the adapter its own processes touch rather than summing what the machine has. This page is the only place the device is named, and it names it once, as the cause.

## Is it known upstream?

No report matches it: nothing describes prefill losing several times its rate as only the allocation grows. The nearest is [llama.cpp#32201](https://github.com/ggml-org/llama.cpp/pull/32201), an open RDNA3 HIP FlashAttention kernel whose own baseline shows prompt throughput falling with depth, so RDNA3 HIP attention is known to be weak at depth. Our logs rule out CPU spill: both runs offload 66/66 layers and the 96k KV fits (13.9 of 16.4 GiB). `llama-bench -p 3045 -d 0` at 8192 and 98304 would isolate it.

## Questions for another reader

- Is this a known regression in the llamacpp-rocm fork after b1372, in release notes or issues?
- Why does `current device` read -1 when enumeration succeeded in the same process?
- Are there WER or `amdkmdag` traces for that instant, and does an 8 s `TdrDelay` hide or cause the symptom?
- Would a driver update or another HIP SDK change it?

Evidence: `scripts/benchmarks/output/llamacpp/benchmark_context_stream/inconclusive/1794597852387930200/logs/server-rocm-lemonade.log`.
