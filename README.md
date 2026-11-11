# AI workspace

A Windows-first workbench for local AI frameworks: installation, weights, configuration, launch and
recorded evidence per engine. Comparing frameworks that offer the similar capabilities, and tuning a framework for AMD hardware: RX 7800 XT (16GB VRAM), and 32GB DDR5 RAM.

## Purpose

Local AI frameworks each carry their own config, ports, weights and quirks. This repo aims to evaluate AMD performance on a variety of frameworks and builds (e.g. vulkan vs rocm) and compare similar functionality found in multiple frameworks (e.g. tts performance in lemonade server vs koboldcpp vs audiocpp).

## Comparing frameworks

Frameworks are measured individually, and in the combined workflows to replicate real usage:
- Language practice: inference engines and models for a multilingual llm, tts, and asr.
- Coding: heavy quantitized llm, performance optimized inference engine, agent harness

## Tuning for this device

Some comparisons stay inside one framework: ROCm against Vulkan, context and offload settings,
quantization and batch size. These measure hardware performance for a fixed workload, not one
framework against another.

- `TUNING.md` for each component states what is in use, the evidence behind it and
  what stays unmeasured: [ComfyUI](scripts/config/comfyui/TUNING.md), [SD.cpp](scripts/config/sdcpp/TUNING.md),
  [llama.cpp](scripts/config/llamacpp/TUNING.md), [Strata](scripts/config/strata/TUNING.md).
- Tuning evidence is recorded like comparison evidence: provenance plus a measured pair, because a
  single run cannot show that a change helped.

## Examples

```powershell
# Coding: llama.cpp plus the Pi agent client
C:\AI\bat\launch_llamacpp_pi_agent.bat

# Language practice: chat, speech and recognition behind one gateway
C:\AI\bat\browser\launch_language_kobold.bat

# Compare the practice stack with Lemonade on chat, speech and recognition
C:\AI\bat\benchmarks\benchmark_framework_compare.bat

# ComfyUI with its tuned attention and VRAM settings
C:\AI\bat\browser\comfyui\launch_comfyui.bat

# Refresh the last-run evidence table for the long opt-in checks
C:\AI\scripts\.venv\Scripts\python.exe -m scripts.tools.capability_matrix
```

Long runs record provenance: workspace and framework commits, weight identity, effective settings,
corpus revision and manifest hash. A result whose inputs changed is marked stale rather than compared.
Recognition is scored on a pinned multilingual corpus with word and character error rates;
synthesised speech is checked against the requested text.

## In progress

The working lists are [TODO](notes/TODO.md) for local work that can start, [upstream
fixes](notes/UPSTREAM.md) for potential issues in existing frameworks found during limited testing,
and [open questions](notes/OPEN-QUESTIONS.md) for decisions not yet made.

## Layout

Launchers are in [bat/](bat). Project code, configuration, and setup instructions are documented in
[scripts/](scripts/README.md). Project-wide notes live in [notes/](notes/); working rules live in
[AGENTS.md](AGENTS.md) and [.agents/](.agents/).

The data/, frameworks/ and trash/ folders are intentionally excluded from Git. See
[onboarding](notes/ONBOARDING.md) to recreate the required installations.
