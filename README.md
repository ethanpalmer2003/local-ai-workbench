# AI workspace

A Windows-first workbench for local AI frameworks: installation, weights, configuration, launch and
recorded evidence per engine. Two jobs run through it: comparing frameworks that offer similar
capabilities, and tuning a framework for AMD hardware, an RX 7800 XT with 16 GB VRAM and 32 GB DDR5 RAM.

## Purpose

Local AI frameworks each carry their own config, ports, weights and quirks. This repo evaluates AMD
performance across frameworks and builds (Vulkan against ROCm) and compares similar functionality in
several frameworks (TTS in the Lemonade server, KoboldCpp and AudioCpp). It adds one canonical key per
component, readiness checks that mean the same thing everywhere, provenance beside every measurement,
and a marker for results whose inputs changed.

## Comparing frameworks

Frameworks are measured alone and in the combined workflows that replicate real use:

- Language practice: a multilingual LLM, TTS and ASR behind one gateway.
- Coding: a quantized LLM, a tuned inference engine and an agent harness.

A workflow states what a framework must provide, and a stack that cannot meet it is refused at launch.

## Tuning for this device

Some comparisons stay inside one framework: ROCm against Vulkan, context and offload settings,
quantization and batch size. These measure hardware for a fixed workload, not one framework against
another.

- There is a `TUNING.md` for each tuned component, stating what is in use, the evidence behind it and
  what stays unmeasured: [ComfyUI](scripts/config/comfyui/TUNING.md), [SD.cpp](scripts/config/sdcpp/TUNING.md),
  [llama.cpp](scripts/config/llamacpp/TUNING.md), [Strata](scripts/config/strata/TUNING.md).
- Tuning evidence follows the comparison rule: provenance plus a measured pair.

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

# Refresh the last-run evidence table for the long opt-in checks
scripts/.venv/Scripts/python.exe -m scripts.tools.capability_matrix
```

## Evidence

A long run records the workspace and framework commits, weight identity, effective settings, corpus
revision and manifest hash; a changed input marks the result stale instead of comparing it. Recognition
is scored on a pinned multilingual corpus with word and character error rates, and synthesized speech
is checked against the requested text.

## In progress

[TODO](notes/TODO.md) holds local work that can start, [upstream fixes](notes/UPSTREAM.md) potential
framework issues found during limited testing, and [open questions](notes/OPEN-QUESTIONS.md) decisions
not yet made.

## Layout

Launchers are in [bat/](bat); code, configuration and setup in [scripts/](scripts/README.md); notes in
[notes/](notes/); working rules in [AGENTS.md](AGENTS.md) and [.agents/](.agents/). The `data/`,
`frameworks/` and `trash/` folders stay out of Git; see [onboarding](notes/ONBOARDING.md) to recreate
the installations.
