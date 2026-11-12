# AI workspace

A Windows-first workbench for local AI frameworks: installation, weights, configuration, launching and
recorded evidence per engine. It serves two jobs: comparing frameworks that offer similar capabilities,
and tuning single frameworks for one AMD device, an RX 7800 XT with 16 GB VRAM and 32 GB DDR5 RAM.

## What the workspace adds

Each framework is third-party and keeps its own configuration, ports and weight paths. Four conventions
make them comparable:

- One canonical key per component, used across configuration, catalogs, tests and batches.
- Readiness checks with the same meaning for every engine.
- Provenance stored beside each measurement.
- Results whose inputs changed are marked stale rather than compared.

## Examples

Paths are relative to the checkout root.

```powershell
# Coding: llama.cpp plus the Pi agent client
bat/launch_llamacpp_pi_agent.bat

# Language practice: chat, speech and recognition behind one gateway
bat/browser/launch_language_kobold.bat

# Compare the practice stack with Lemonade on chat, speech and recognition
bat/benchmarks/benchmark_framework_compare.bat

# ComfyUI with its tuned attention and VRAM settings
bat/browser/comfyui/launch_comfyui.bat
```

## Comparing and tuning

Frameworks are measured alone and in combined workflows that replicate real use: a multilingual LLM
with speech and recognition behind one gateway, or a quantized LLM with a tuned inference engine and an
agent harness. A workflow states what a framework must provide, and a stack that cannot meet it is
refused at launch. Similar functions are compared across frameworks, for example TTS in Lemonade,
KoboldCpp and AudioCpp.

Tuning keeps the workload fixed and changes one variable for this device: ROCm against Vulkan builds,
context and offload settings, quantization and batch size. Applied to llama.cpp, Strata, ComfyUI and
SD.cpp. Both jobs follow the same evidence rule.

## Evidence

A long run records the workspace and framework commits, the digest of the script that produced it,
weight identity, effective settings, corpus revision and manifest hash. Recognition is scored on a pinned multilingual corpus with word and
character error rates, and synthesized speech is checked against the requested text. Methods are in
[scripts/benchmarks/README.md](scripts/benchmarks/README.md).

## In progress

[TODO](notes/TODO.md) holds local work that can start, [upstream fixes](notes/UPSTREAM.md) potential
framework issues found during limited testing, and [open questions](notes/OPEN-QUESTIONS.md) decisions
not yet made.

## Layout

Launchers are in [bat/](bat); code, configuration and setup in [scripts/](scripts/README.md); notes in
[notes/](notes/); working rules in [AGENTS.md](AGENTS.md) and [.agents/](.agents/). The `data/`,
`frameworks/` and `trash/` folders are not tracked by Git; see [onboarding](notes/ONBOARDING.md) to
recreate the installations.
