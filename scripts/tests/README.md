# Tests

- Regression setup: [shared fixtures and adapter contracts](shared/FIXTURES.md).

- Sources/UI: `cases/<component>/`, `ui/<component>/`; cross-component cases are grouped by purpose under [cases/shared](cases/shared/README.md), the gate's own cases under [cases/review](cases/review/README.md), and the modules behind the run commands under [cases/suites](cases/suites/README.md). Functional smoke checks stay here.
- `registry.py` finds every `test_*.py` class by parsing the file and imports its module by path, and names the suite classes that live beside their workers (including `frameworks_smoke.DEFAULT_CLASSES`); `run.py` hands pytest node ids for those classes. A test file needs no registry edit; a class added to a non-test module must be named. Ad-hoc run: `pytest scripts/tests/cases/<area> -q`.
- The default run is a feedback loop ([selection](scoped_selection.py) owns the rule): it keeps the classes one import hop from a Python change, so a test module one hop beyond the code under test is not selected and waits for the push; `--all` before a push is what catches the rest, as [validate](validate.py) does. A clean tree runs none and a branch without an upstream keeps every class; a change set with no Python module, and a comment or docstring edit anywhere, run none; the graph reads every Python file under `scripts/` that git lists; a dynamic import is refused by the gate, and a file reached by path stays invisible. Only [registry.py](registry.py), [run.py](run.py) and [scoped_selection.py](scoped_selection.py) keep every class, and only when their code changes.
- Regression execution is pytest; the artifacts keep their existing shape (`report.md`, `timings.json`, `unittest.txt`). Model and install checks (what a GGUF, catalog entry or installed framework declares) sit behind `requires_model_check`: they skip in the default run and execute with `AI_MODEL_CHECKS=1`, after a download or framework update. The criterion is what a check asserts, never how long it takes: only a download, framework update or machine change can break them, while behavior this repository owns stays in the default suite at any duration. `pytest-timeout` gives every test a [60-second deadline](../../pyproject.toml), so a hung probe or socket fails that test.
- New test output mirrors source through `CasePaths`: `output/<component>/<case>/<outcome>/<YYYY-MM-DD>/<run>/{logs,artifacts,temp}`. A suite or regression case runs on every commit, so it writes under `state/temp/runs/`, pruned on the ordinary window; benchmarks and probes keep permanent evidence. Media-generation areas (`sdcpp`, `comfyui`) nest under `output/personal/`; Kobold, AudioCpp, `tts_engines` and `asr` stay at the root because the same engines serve language practice. Historical results stay at their original paths.
- Retired runners and their evidence: [notes/RETIRED.md](notes/RETIRED.md) records what moved, where it went and why; the archived evidence itself stays untracked.
- Performance runners and new results live in [`scripts/benchmarks`](../benchmarks/README.md).

| Purpose | Entry / guide |
| --- | --- |
| Lint, structure/docs, types and the repository review | `C:/AI/scripts/review/check_repo.bat` or `python -m scripts.review` |
| Model-free suite (no VRAM) | `C:/AI/bat/checks/test_model_free.bat` |
| Live launcher/proxy wiring (VRAM) | `C:/AI/bat/checks/test_live_launchers.bat`: `sdcpp`, `audiocpp`, `llamacpp` (Pi), `kobold` (+ proxy readiness), `practice` |
| Live backend probes (VRAM) | `C:/AI/bat/checks/test_live_backends.bat`: `parakeet`, `practice-whisper`, `practice-qwen`, `gemma`, `images`, `ming3-tts`; one arm each; calls: [suite calls](shared/suite_calls.py) |
| Both native suites | `C:/AI/bat/checks/test_live_all.bat` |
| Everything, skip-aware, one progress bar | `C:/AI/bat/checks/test_full.bat`: updates frameworks, then the gate, the suite (model and install checks on) and both live suites; `--models` adds the catalog source check, `--no-update` drops the preflight; expected ranges live in [stage_times](../config/shared/stage_times.py) |
| One long model test | `python -m scripts.tests.model_run --label NAME --minutes 20 MODULE -- --module-args` [owner](model_run.py): `--dry-run` proves inputs and ports first; the run kills the tree after the cap or after `--silence` seconds without output and CPU |
| Piper / Sherpa resident speed | [benchmark_tts_speed.bat](../../bat/benchmarks/benchmark_tts_speed.bat); shared lifecycle, voice loaded once, WAV saving excluded |
| Audio model setup | [guide](../config/audiocpp/MODELS.md); loader checks passed, synthesis prepared |
| ASR | [framework/shared suites](cases/asr/README.md) |
| Coding clients | [benchmark guide](../benchmarks/coding_agents/README.md) |
| Model/profile comparisons | [guide](../benchmarks/MODEL-COMPARISONS.md) |
| Native llama.cpp benchmarks | [guide](../benchmarks/llamacpp/README.md) |
| Audio streaming UI | [page](ui/speech.html), [procedure](../launchers/audiocpp/README.md) |
| ComfyUI video | [procedure](../benchmarks/personal/comfyui/README.md) |

Native partition: launchers own user-facing start/stop, ports and proxy wiring; backends own direct engine/model probes. The sets are disjoint: AudioCpp Breeze2 is launcher-only and `ming3-tts` is the remaining AudioCpp backend case; `practice-whisper` also grades Kobold's embedded Whisper on the server it starts. Both suites skip when the sources, installed models and frameworks are unchanged since their last pass (metadata only; `AI_LIVE_FORCE=1` reruns) and refuse an occupied port instead of stopping a session, show a per-target progress bar, and write the same `results.json`/`report.json` shape. All native workers join the kill-on-close job; closing the test terminal stops everything the run started. An automated run opens no browser window: a page is driven in place or left to a live check.

Execution rules, evidence conventions and report/status categories are documented in [EXECUTION-AND-REPORTING.md](EXECUTION-AND-REPORTING.md).
