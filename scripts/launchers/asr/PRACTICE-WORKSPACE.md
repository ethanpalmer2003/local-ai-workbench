# Speech workspace

`/practice` shows model and language selectors, conversation, microphone and Send/Cancel. Tutor settings use defaults. `/test/` shows all settings and diagnostics. Both routes share one [HTML](../../tests/ui/speech.html) document and chat controller; hiding controls does not change model lifecycle or measurements.

Use [ASR-only](../../../bat/browser/launch_test_asr.bat), [LLM-only](../../../bat/browser/launch_test_llm.bat), or [all-stage](../../../bat/browser/launch_test.bat) launchers for `/test/`. AudioCpp `/test/` redirects here. Practice hides diagnostics.

Model selection, residency and saved UI state: [PRACTICE-MODELS.md](PRACTICE-MODELS.md).

## Conversation

- Choose language, CEFR level and brief corrections; type or toggle the microphone
  beside Send/Cancel. Disable auto-send to review recognized text first.
- Cancel aborts browser requests/playback. Clear also stops capture. Enabled models
  stay loaded until unchecked or unloaded together. Save downloads conversation JSON.
- Languages follow enabled stages: ASR/TTS intersection when both run, ASR coverage
  alone for recognition, installed voices for TTS alone. Unknown coverage is explicit.
- Native llama-ui can use the same speech gateway through the [speech adapter](../llamacpp/SPEECH-UI.md).

## Measurements

- Collapsed initially, newest first. Each row captures the actual model identity;
  switching models never relabels history. Unknown older identities say Not recorded.
- Server rows separate startup/readiness, explicit AudioCpp loading, requests and
  unload. Inseparable startup/loading is labelled combined; unknown splits stay null.
  Browser wall times include transfer/cold startup; live-turn time includes capture/VAD.
- Dated JSONL evidence in `scripts/state/logs/asr/shared/practice-lifecycle-*.jsonl`
  includes model, PID, ownership and execution context. These diagnostics do not
  replace [resident benchmarks](../../benchmarks/README.md).

Owners: [ASR](shared/practice_asr.py), [LLM](../llamacpp/chat_models.py),
[TTS](shared/practice_models.py), [selection](shared/practice_selection.py),
[workspace](shared/workspace.py) and [chat adapter](../llamacpp/language_practice.py). Kobold retains launcher-selected models.
