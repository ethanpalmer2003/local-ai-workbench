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

## Questions for another reader

- Is this a known regression in the llamacpp-rocm fork after b1372, in release notes or issues?
- Why does `current device` read -1 when enumeration succeeded in the same process?
- Are there WER or `amdkmdag` traces for that instant, and does an 8 s `TdrDelay` hide or cause the symptom?
- Would `HIP_VISIBLE_DEVICES=0`, a driver update or a different HIP SDK change it?

Evidence: `scripts/benchmarks/output/llamacpp/benchmark_context_stream/inconclusive/1794597852387930200/logs/server-rocm-lemonade.log`.
