# Engines to trial

Two engines are queued for a comparison row. Neither is installed, so both stay out of every run until one is; both speak an OpenAI-compatible API, so the `--engine endpoint` arm of [the coding-engine runner](README.md) is what reaches them. Their rows belong beside the Avalon arm once one loads a local model here.

- **RustingStrata** ([AMD notes](https://github.com/RustingStudio/RustingStrata/blob/main/docs/AMD.md)): a Rust engine on a Vulkan backend. It needs a Vulkan 1.3 driver with subgroup size 32, or fixed 64. Its first output line reports `device-coherent memory`, `cooperative matrix` and `conditional rendering`; coherent memory must be `yes` when experts stay in RAM, because the GPU polls a mailbox the CPU writes. Known AMD faults: slow decode with CPU-resident experts, a GPU reset during long prefill (the driver caps a submission at 10 s, so lower `STRATA_VK_ATTN_BUDGET` or `--chunk`), and rare NaN logits. The switches for narrowing a report (`STRATA_VK_NO_COOP`, `STRATA_VK_ATTN_BUDGET`, `STRATA_VK_DP_OLD`, `STRATA_VK_NO_COND`, `STRATA_VK_NO_TQ`, `STRATA_VK_SMEM_LIMIT`) are in that page.
- **LexiEngine** ([releases](https://github.com/W61k3r/LexiSuite-Releases)): the inference engine of a Rust appliance suite, serving GGUF on Vulkan, CUDA and CPU behind OpenAI and Anthropic-compatible APIs. Its published speeds are an RX 7900 XTX on Ubuntu, and the suite ships as a USB image or a Linux/WSL install, so a Windows comparison needs WSL2 with GPU passthrough. The source is proprietary: free for personal and educational use, licensed per instance commercially.

Neither supports this host's Windows-native path today, so a trial starts by proving the engine starts at all and serving one installed GGUF, before any comparison row is recorded.

## What a trial records

1. The version string and the engine's own first line (driver, subgroup, device-coherent memory).
2. Startup, cold prefill, decode and TTFT from the engine's own timings, on the same prompt contract as [the paired screen](README.md).
3. The failure reason, kept verbatim, when the engine refuses the card, the context or the model.
