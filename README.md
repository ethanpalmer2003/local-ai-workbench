# AI workspace

A Windows-first workbench for running local AI at home: one launcher, configuration catalog,
test suite and benchmark per framework, organised around three things people actually do with
it: character chat, language practice and coding.

## Purpose

Local AI is a pile of frameworks that each want their own config, ports, weights and quirks.
This repository gives every component one canonical key that owns its install folder, model
storage, settings, logs and tests, then drives those components through the same launchers,
readiness checks and evidence layout. Served frameworks include llama.cpp, KoboldCpp, Lemonade,
AudioCpp (speech synthesis and recognition), whisper.cpp, Parakeet.cpp, SD.cpp and ComfyUI.

Three workflow profiles decide what a stack must provide before it is considered at all:

- `character`: character chat: a mid-size chat model plus voice-design speech (AudioCpp Breeze).
- `language`: language practice: a lightweight multilingual model, fast Kokoro speech and
  recognition that reads the practice languages (Qwen3-ASR by default).
- `coding`: coding: a coding model behind an agent client (Pi, DeepSeek Harness, LittleCoder).

## Examples

```powershell
# Coding: llama.cpp plus the Pi agent client
C:\AI\bat\launch_llamacpp_pi_agent.bat

# Character chat: KoboldCpp with Breeze speech through the AudioCpp proxy
C:\AI\bat\browser\launch_kobold.bat

# Language practice: chat, speech and recognition behind one gateway
C:\AI\bat\browser\launch_language_kobold.bat

# Compare the practice stack with Lemonade on chat, speech and recognition
C:\AI\bat\benchmarks\benchmark_framework_compare.bat

# Refresh the last-run evidence table for the long opt-in checks
C:\AI\scripts\.venv\Scripts\python.exe -m scripts.tools.capability_matrix
```

Long runs record provenance (workspace and framework commits, weight identity, effective
settings, corpus revision and manifest hash), so a later run can tell what changed, and a stale
result is marked rather than silently compared. Recognition is scored on a pinned multilingual
corpus with word and character error rates, and synthesised speech is rejected when it cannot be
the sentence it claims to be.

## Layout

Launchers are in [bat/](bat). Project code, configuration, and setup instructions
are documented in [scripts/](scripts/README.md). Project-wide notes live in
[notes/](notes/); working rules live in [AGENTS.md](AGENTS.md) and [.agents/](.agents/).

The data/, frameworks/ and trash/ folders are intentionally excluded from Git.
See [onboarding](notes/ONBOARDING.md) to recreate the required installations.
