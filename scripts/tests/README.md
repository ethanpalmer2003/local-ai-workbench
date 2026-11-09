# Tests

- Regression setup: [shared fixtures and adapter contracts](shared/FIXTURES.md).

- Sources/UI: `cases/<component>/`, `ui/<component>/`; cross-component cases are grouped by purpose under `cases/shared/`. Functional smoke checks stay here.
- `run.py` imports every test class explicitly and hands pytest node ids for exactly those classes: a new module stays outside the default suite until its class is registered, and live modules are never collected by accident. Ad-hoc run: `pytest scripts/tests/cases/<area> -q`.
- Regression execution is pytest; the artifacts keep their existing shape (`report.md`, `timings.json`, `unittest.txt`). Model and install checks (what a GGUF, catalog entry or installed framework declares) sit behind `requires_model_check`: they skip in the default run and execute with `AI_MODEL_CHECKS=1`, after a download or framework update. Behaviour this repository owns stays in the default suite.
- New test output mirrors source through `CasePaths`: `output/<component>/<case>/<outcome>/<run>/{logs,artifacts,temp}`. Media-generation areas (`sdcpp`, `comfyui`) nest under `output/personal/`; Kobold, AudioCpp, `tts_engines` and `asr` stay at the root because the same engines serve language practice. Historical results stay at their original paths.
- Performance runners and new results live in [`scripts/benchmarks`](../benchmarks/README.md); downloaded upstream benchmark tools remain in `frameworks/benchmarks`.

| Purpose | Entry / guide |
| --- | --- |
| Lint, structure/docs, types and the repository review | `C:/AI/scripts/review/check_repo.bat` or `python -m scripts.review` |
| Model-free suite (no VRAM) | `C:/AI/bat/tests/test_model_free.bat` |
| Live launcher/proxy wiring (VRAM) | `C:/AI/bat/tests/test_live_launchers.bat`: `sdcpp`, `audiocpp`, `llamacpp` (Pi + LittleCoder), `kobold` (+ combined-proxy readiness), `dsh-headless`, `practice` gateway |
| Live backend probes (VRAM) | `C:/AI/bat/tests/test_live_backends.bat`: `parakeet`, `whisper`, `practice-whisper`, `practice-qwen`, `gemma`, `kokoro`, `images`, `ming3-tts`; `--only NAME...` narrows |
| Both native suites | `C:/AI/bat/tests/test_live_all.bat` |
| Piper / Sherpa resident speed | [benchmark_tts_speed.bat](../../bat/benchmarks/benchmark_tts_speed.bat); shared lifecycle, voice loaded once, WAV saving excluded |
| Audio model setup | [guide](../config/audiocpp/MODELS.md); loader checks passed, synthesis prepared |
| ASR | [framework/shared suites](cases/asr/README.md) |
| Coding clients | [benchmark guide](../benchmarks/coding_agents/README.md) |
| Model/profile comparisons | [guide](../benchmarks/MODEL-COMPARISONS.md) |
| Native llama.cpp benchmarks | [guide](../benchmarks/llamacpp/README.md) |
| Audio streaming UI | [page](ui/speech.html), [procedure](../launchers/audiocpp/README.md) |
| ComfyUI video | [procedure](../benchmarks/personal/comfyui/README.md) |

Native partition: launchers own user-facing start/stop, ports and proxy wiring; backends own direct engine/model probes. The sets are disjoint: AudioCpp Breeze2 is launcher-only and `ming3-tts` is the remaining AudioCpp backend case. Additional coding clients and Strata live runs belong to the coding benchmark; ComfyUI is vendor-managed. Both suites refuse an occupied port instead of stopping a session, show a per-target progress bar, and write the same `results.json`/`report.json` shape. All native workers join the kill-on-close job; closing the test terminal stops everything the run started. An automated run opens no browser window: a page under test is driven in place or left to a live check.

Execution rules, evidence conventions and report/status categories are documented in [EXECUTION-AND-REPORTING.md](EXECUTION-AND-REPORTING.md).
