# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration, shortest first.

## Reliability
Defects and safety gaps: something behaves wrongly or can run away, and the fix is code or configuration.

- [ ] Add an operating-system backstop for the deep-scan rule: a profile tool guard (`scripts/state/plugins/guard-deep-scan`, installed in the desktop profile) refuses a recursive shell scan, a glob or a grep under `data/` and `frameworks/`, but it only binds harnesses that load that plugin. An ACL that denies the agent process read access to those roots, or allows only named subpaths, is the only rule no tool call can bypass. Test with a fresh shell as the agent's user, then remove the guard if the ACL holds. ~45 min

## Standardization
A rule or a shape to decide, where the code is already correct and the question is which convention to keep.


- [ ] Decide whether a repeated expression earns a name: `_dump_without_docstrings` repeated `node.body` four times and `_from_import_target` computed `node.level - 1` twice before both were named. A probe counting non-`self` attribute chains of two or more segments, and binary operations, repeated three or more times per function finds 75 functions and 85 repeats, so a gate rule would flag a slice of idiomatic code rather than a defect; the enforceable narrowings are repeats inside one condition (where the `isinstance` chain lived) or repeats inside one statement. ~30 min


- [ ] Decide what to do with the 646 parameter defaults the census counts (python -m scripts.review.checks.annotations --census): keep rgv, decide whether a derived default becomes a required argument, and audit the 231 carried ones where None is also a legal value, which needs a sentinel. Owner: [annotations check](../scripts/review/checks/annotations.py). ~2 h

- [ ] Decide the docstring voice repo-wide: PEP 257 asks for imperative mood ("Return the path"), and 127 of 1157 docstrings here do that while 1030 describe ("The path..."). `scripts/shared/import_graph.py` and `scripts/tests/scoped_selection.py` are on the standard as the reference. The same pass settles the `# - ` comment marker, 517 lines of which the two files no longer use. Migrate area by area, then state the rule in [code](../.agents/CODE.md) and check it in `scripts/review/checks/comments.py` only if the opening word can be measured. ~3 h

- [ ] Decide whether vague names get an audit, and at what strictness: 784 public functions in `scripts` are one word (310 distinct names, led by `start`, `command`, `close`, `run`, `ready`), so a blanket rule would flag most idiomatic code; the enforceable part is a short banned list for names that carry no object (`run`, `check`, `handle`, `process`, `data`, `utils`, `helpers`, `common`, `base`, `manager`), checked like `owned_tokens.py`, plus the [folder](../.agents/FOLDERS.md) rule "a name states its scope" extended to modules and functions. The earlier module pass found only `engines/base.py` under that list; `scoping` was vague but no banned word, and became `selection`. ~30 min
- [ ] Decide a grouping rule for long modules: named section headers (`# --- Name ---...`) split a file into its stages, and the refactored `scripts/tests/scoped_selection.py` uses four; the open question is the cap, because a file with twelve groups is harder to read than one with none. Candidates: a maximum of four or five groups, a minimum lines-per-group, or no cap with review. Set it in [code](../.agents/CODE.md) and check it in `scripts/review/checks/inventory_code.py` only if the number can be measured. ~30 min
- [ ] Decide the retired TTS pipeline in `scripts/launchers/audiocpp/tts_legacy_buffered.py`: nothing imports it, its own docstring calls it retired, and the active path is `tts_text_processing.py`. Delete it, or name the usefulness it still has; either way drop the `RETIRED` entry in `scripts/review/checks/dead_code.py` with it. ~20 min
- [ ] Roll the llama.cpp Vulkan build back: b12422 kills the 27B server while re-prefilling a 3,707-token prompt, so the coding model and the 27B benchmark arm do not run on it ([builds](../scripts/config/llamacpp/BUILDS.md)). Reinstall b12363, confirm one Pi `proverb` run finishes, then finish the Strata/27B pair on that tag. ~30 min
- [ ] Repair the Strata install: the native updater kept engine 0.1.59 because 0.1.60 failed its test start, while control reached 0.1.60, so a launch now exits before serving because the image encoder child cannot start (`WinError 5`). `update_frameworks` reports this and installs nothing; repair it in the Strata app (control reports `failed-before` for the engine) and confirm a plain launch serves without the vision-free config the benchmark used. ~20 min
- [ ] Judge the duplicate blocks the baseline still holds: `matching_server` is four identical one-liners (`whispercpp/server`, `embeddings/server`, `audiocpp/asr`, `asr/llamacpp/llama_audio`), `audiocpp.py::main` against `llamacpp.py::main` is two launchers with different wiring, and `launcher_config.py` carries the same three-line `exe` property on three build classes. Fold the one-liners if the wrapper is not the seam a test patches; leave the other two. [code pairs](../scripts/review/SIMILARITY.md). ~30 min
- [ ] Wire `python -m scripts.review.checks.duplicates` into an opt-in batch and settle its baseline granularity: it records a file pair plus a block count, so a second block in a known pair fails while a moved block does not. pylint needs about a minute over `scripts`. ~30 min
- [ ] Move the `codebase-memory-mcp` uv tool to Python 3.14 (`uv tool install --python 3.14 codebase-memory-mcp --force`), then uninstall the managed 3.13 interpreter; the tool currently runs on `cpython-3.13-windows-x86_64-none`, which blocked `uv python uninstall 3.13`. ~5 min
- [ ] Find which update path keeps creating an empty `bin` directory; it was archived 70 times into `trash/` on 2026-11-15. `archive_path` now removes empty directories instead of trashing them, so the churn is invisible, but the source is still unknown. ~20 min

- [ ] Batch the upstream reads in the scope: `_code_changed_since_upstream` runs one `git show` per changed `.py` file, which is fine for a commit and slow for a large change set or a rebase. Options: one `git show` per file is already batched by path, or `git diff --name-only` first and only parse files whose text differs, or a read-cache keyed on the upstream ref. Measure a 50-file change set before deciding. ~30 min
- [ ] Apply the no-nested-call rule repo-wide: a call is never an argument of another call. `scripts/tests/scoped_selection.py` had five by AST count (two direct, three inside `any`/`sum` generators); the two direct ones are fixed, and the rest of `scripts/` is unaudited. Decide whether the generator form counts before sweeping, then measure the total. ~1 h

- [ ] Decide a retention rule for run evidence: `scripts/tests/output` holds 1.05 GB across 451,937 files and `scripts/benchmarks/output` 0.92 GB, and neither has a prune path; `state_cleanup` covers only logs and download leftovers (8 MB of old run logs today). Options: keep the latest run per area and archive the rest to `trash`, keep anything a tracked document cites, or leave it and rely on manual emptying. Owners: [tests/output](../scripts/tests/) and [benchmarks/output](../scripts/benchmarks/). ~1 h


## Needs a model run or device
Work that cannot be settled without a live run: weights, a device, a server or a human at the machine.

### Requires user input

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/benchmarks/asr/coverage.py). ~45-60 min

### Unattended

- [ ] Explain why generation stops after a few tokens at a 96K prompt: reasoning on returns only `<think>`,
  reasoning off a 17-token fragment, both far under a 256-token budget, while 32K, 40K and 64K answer fully.
  Probe once with a plain long-generation prompt at 96K: if that also stops early the deep allocation is the
  cause, and if it runs the fault is in the rewrite prompt or the grading path. [Result](../scripts/tests/notes/OUTCOMES.md).
  ~30 min
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The pair now exists on ROCm for `proverb` and `ledger` (27B 23.2 s and 59.3 s against Strata's 74.1 s and 144.0 s, Pi client), but the Vulkan arm still needs the b12422 crash resolved before it can be repeated on the default build. Turn-budget cleanup stays unverified. [Results](../scripts/tests/notes/OUTCOMES.md). ~1 h

- [ ] Report the Loom 0.2.0 Windows device failure upstream, then retry the comparison: the SDK installs and serves on this box but the model cannot run. `--device=amdgpu`, `rdna`, `rdna://1` and `cdna` all answer `NOT_FOUND; no AMD endpoint matches the selected family and path` from `runtime/src/iree/hal/driver/amd/driver.c:843`, while `amdf-info` sees the RX 7800 XT as `rdna://1`, gfx1102, 60 CU. `--device=vulkan` creates the device, then the Qwen2.5-0.5B port fails to lower: `llm.loom:37054:5: LOWERING/045: select-templates cannot resolve template.apply against template family <sel11_g_attention_split>: target_mismatch` (10,224 errors). Baseline for the same GGUF on llama.cpp Vulkan 1.0.0-dev (12422, a681a53b6): 472 tok/s median over five 128-token runs. The run set (SDK venv, model package, logs) is preserved at `trash/2026-11-19/loom-0.2.0-experiment/`; a retry needs a registered component under `frameworks/` and `HF_HOME` pointed at its models dir, since a raw install trips the layout check. ~2 h
