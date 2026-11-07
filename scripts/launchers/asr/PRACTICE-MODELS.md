# Speech workspace models

Model selection, residency and saved UI state for the [speech workspace](PRACTICE-WORKSPACE.md).

## Models

- ASR model is primary; runtime conversions share one choice. Auto prefers
  AudioCpp, NeMo-Speech.cpp, then parakeet.cpp CPU streaming for Nemotron,
  skipping unavailable runtimes. Other models use available implementations.
  Manual runtime overrides persist per model. The runtime tooltip identifies
  the registered weights; conversions remain separate files.
- LLM and TTS choices retain their registered model identities.
- Opening the page starts only the gateway. Requests start required services;
  typed messages skip ASR. Load all active preloads enabled stages; Send and
  Listen apply pending choices for enabled stages first. Changes stop
  capture and unload the previous owned setup; conversation history stays.
- ASR/TTS/LLM selections persist in `scripts/state/asr/shared/practice_models.json`.
  Disabled stages retain their selection. Explicit CLI ASR selection wins.
- Unchecking unloads that stage's owned model; Unload all releases every owned
  stage and clears the stage toggles.
  AudioCpp ASR/TTS share one lazy server with per-model residency. Its last unload
  stops the process. Shared Gemma audio/chat uses one process only when both select
  the same Gemma weights; a different LLM gets a separate chat server.
  Reused/unowned services are preserved and reported.
- Startup failures remain visible for retry or another selection. Large/untested
  profiles are not automatically benchmarked. Drama validation remains opt-in.

## Saved state

- Both routes restore `speech-workspace.preferences.v1` (models, language, level, corrections, auto-send) and the `speech-workspace.catalog.v1` cache; cached controls stay disabled until re-verified, and restoring never loads a model. Pending choices apply on Send, Listen or Load all active; unavailable choices fall back to the server.
- `/test/` Settings (overrides, transport, mode, buffer, rate, voice) never persist: each load refetches `/proxy/config` and resets them. Comparison selections are unsaved; Kobold Lite keeps its own `kobold-audio-streaming`.
