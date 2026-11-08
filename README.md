# AI workspace

A Windows-first workbench for local AI frameworks: installation, weights, configuration, launch
and recorded evidence per engine. The work it serves is evaluation, so a framework can be measured
on its own or in a workflow that needs several of them working together.

## Purpose

Local AI arrives as a set of frameworks that each own their config, ports, weights and quirks.
Comparing them needs more than a working install: one canonical key per component, readiness checks
that mean the same thing everywhere, provenance recorded beside every measurement, and results that
say what changed since the last run. This repository provides that for llama.cpp, KoboldCpp,
Lemonade, AudioCpp (speech synthesis and recognition), whisper.cpp, Parakeet.cpp, SD.cpp and
ComfyUI.

## What gets evaluated

Frameworks are measured individually, and in the combined workflows a real capability requires:

- Language practice: an inference engine, speech synthesis and recognition behind one gateway, so
  chat, spoken output and transcripts are all part of the same session.
- Coding: an agent harness in front of an inference engine, where the harness decides how the model
  is driven and the engine decides how fast it answers.

Each workflow states what a framework must provide before it is considered at all, so a stack that
cannot meet the requirement is refused up front rather than discovered at runtime.

## Examples

```powershell
# Coding: llama.cpp plus the Pi agent client
C:\AI\bat\launch_llamacpp_pi_agent.bat

# Language practice: chat, speech and recognition behind one gateway
C:\AI\bat\browser\launch_language_kobold.bat

# Compare the practice stack with Lemonade on chat, speech and recognition
C:\AI\bat\benchmarks\benchmark_framework_compare.bat

# Refresh the last-run evidence table for the long opt-in checks
C:\AI\scripts\.venv\Scripts\python.exe -m scripts.tools.capability_matrix
```

Long runs record provenance (workspace and framework commits, weight identity, effective settings,
corpus revision and manifest hash), so a later run can tell what changed, and a stale result is
marked rather than silently compared. Recognition is scored on a pinned multilingual corpus with
word and character error rates, and synthesised speech is rejected when it cannot be the sentence it
claims to be.

## Layout

Launchers are in [bat/](bat). Project code, configuration, and setup instructions are documented in
[scripts/](scripts/README.md). Project-wide notes live in [notes/](notes/); working rules live in
[AGENTS.md](AGENTS.md) and [.agents/](.agents/).

The data/, frameworks/ and trash/ folders are intentionally excluded from Git. See
[onboarding](notes/ONBOARDING.md) to recreate the required installations.
