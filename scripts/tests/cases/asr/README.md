# ASR checks

- Cross-framework inventory and comparison limits: [comparison guide](COMPARISON.md).
- New file profiles/models: [commands](../../../launchers/asr/FILE-ENGINES.md); `bat/benchmarks/benchmark_asr_compare.bat` previews assets, `--run` explicitly opts into inference. Native validation remains pending approval.

- `whispercpp/`: Whisper profiles; `llamacpp/`: Qwen profiles and Gemma boundary/response contracts.
- `parakeetcpp/smoke.py`: CPU/Vulkan transcription with/without Silero, plus VAD-only checks.
- Dedicated Handy and KoboldCpp test coverage is deferred; shared probes exercise embedded Whisper/Gemma.
- `shared/`: corpus preparation, metrics, multipart fixtures and cross-runtime/integration probes.
- Global updater/catalog contracts stay under `cases/shared/`.

```powershell
C:/AI/bat/tests/test_model_free.bat
C:/AI/bat/tests/test_live_backends.bat --only whisper parakeet practice-whisper practice-qwen gemma
```

- Quick validation runs native probes sequentially on temporary ports, preserves logs and returns failure if any probe fails. Processes are task-owned; existing native sessions are retained/refused.
- Optional selections cover Kokoro, images and AudioCpp; the default batch now runs only a brief Breeze comparison. Expect several minutes; execution-context and long-run rules apply.
- Gemma unit checks cover empty/exactly-30/over-limit input, stereo resampling, malformed audio, response formats and invalid/truncated transcripts.
- Synthetic English clips establish compatibility and bounded timing. Fair multilingual/noisy/cold-versus-cached evaluation needs controlled inputs/settings.
- Output mirrors source via `CasePaths`; historical output stays in place. [Current evidence](../../../../notes/NATIVE-VALIDATION.md), [test rules](../../README.md).
