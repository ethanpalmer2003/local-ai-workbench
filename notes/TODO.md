# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration, shortest first.

## Reliability
Defects and safety gaps: something behaves wrongly or can run away, and the fix is code or configuration.

- [ ] Add an operating-system backstop for the deep-scan rule: a profile tool guard (`scripts/state/plugins/guard-deep-scan`, installed in the desktop profile) refuses a recursive shell scan, a glob or a grep under or above the ignored trees, and derives those names from the ignore files, but it only binds harnesses that load that plugin. An ACL that denies the agent process read access to those roots, or allows only named subpaths, is the only rule no tool call can bypass. Test with a fresh shell as the agent's user, then remove the guard if the ACL holds. ~45 min

## Standardization
A rule or a shape to decide, where the code is already correct and the question is which convention to keep.


- [ ] Decide whether a repeated expression earns a name: `_dump_without_docstrings` repeated `node.body` four times and `_from_import_target` computed `node.level - 1` twice before both were named. A probe counting non-`self` attribute chains of two or more segments, and binary operations, repeated three or more times per function finds 75 functions and 85 repeats, so a gate rule would flag a slice of idiomatic code rather than a defect; the enforceable narrowings are repeats inside one condition (where the `isinstance` chain lived) or repeats inside one statement. ~30 min


- [ ] Decide what to do with the 661 parameter defaults the census counts (`python -m scripts.review.checks.annotations --census`: 238 carried, 227 literal, 89 derived, 52 argv): keep `argv`, decide whether a derived default becomes a required argument, and audit the carried ones where `None` is also a legal value, which needs a sentinel. Owner: [annotations check](../scripts/review/checks/annotations.py). ~2 h

- [ ] Decide the docstring voice repo-wide: PEP 257 asks for imperative mood ("Return the path"). Of the 1,238 module, class and function docstrings, the first word is a determiner ("The path...") in 287, an imperative verb in 211, and neither in 740, so a first-word gate would judge under half of them and the rule is a decision before it is a check. `scripts/shared/import_graph.py` and `scripts/tests/scoped_selection.py` are on the standard as the reference. The same pass settles the `# - ` comment marker, 517 lines of which the two files no longer use. Migrate area by area, then state the rule in [code](../.agents/CODE.md) and add a check in `scripts/review/checks/comments.py` only if the opening word can be measured. ~3 h

- [ ] Decide whether vague names get an audit, and at what strictness: 801 public functions in `scripts` are one word over 314 distinct names, led by `main` (143), `start` (32), `command` (21), `close` (17) and `run` (16), so a blanket rule would flag most idiomatic code; `main` is an entry point. The enforceable part is a short banned list for names that carry no object (`run`, `check`, `handle`, `process`, `data`, `utils`, `helpers`, `common`, `base`, `manager`), checked like `owned_tokens.py`, plus the [folder](../.agents/FOLDERS.md) rule "a name states its scope" extended to modules and functions. The earlier module pass found only `engines/base.py` under that list; `scoping` was vague but no banned word, and became `selection`. ~30 min
- [ ] Decide a grouping rule for long modules: named section headers (`# --- Name ---...`) split a file into its stages, and the refactored `scripts/tests/scoped_selection.py` uses four; the open question is the cap, because a file with twelve groups is harder to read than one with none. Candidates: a maximum of four or five groups, a minimum lines-per-group, or no cap with review. Set it in [code](../.agents/CODE.md) and check it in `scripts/review/checks/inventory_code.py` only if the number can be measured. ~30 min
- [ ] Wire `python -m scripts.review.checks.duplicates` into an opt-in batch and settle its baseline granularity: it records a file pair plus a block count, so a second block in a known pair fails while a moved block does not. pylint needs about a minute over `scripts`. ~30 min
- [ ] Batch the upstream reads in the scope: `_code_changed_since_upstream` runs one `git show` per changed `.py` file, which is fine for a commit and slow for a large change set or a rebase. Options: one `git show` per file is already batched by path, or `git diff --name-only` first and only parse files whose text differs, or a read-cache keyed on the upstream ref. Measure a 50-file change set before deciding. ~30 min
- [ ] Apply the no-nested-call rule repo-wide: a call is never an argument of another call. `scripts/tests/scoped_selection.py` had five by AST count (two direct, three inside `any`/`sum` generators); the two direct ones are fixed, and the rest of `scripts/` is unaudited. Decide whether the generator form counts before sweeping, then measure the total. ~1 h

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
- [ ] Return to the newest Vulkan build once its two faults clear: the installed pin is `vulkan-1.0.0`, because b12421 and b12422 exit the embedding server on a multi-text `/v1/embeddings` request and kill the 27B server while re-prefilling 3,707 tokens ([builds](../scripts/config/llamacpp/BUILDS.md)). The catalog entry still reports the newest tag (b12554 today) and applying `llamacpp/vulkan` reinstalls a rolling build, so the test is those two requests on the new tag; only then does `LLAMACPP_DEFAULT_BUILD` move off the pin. ~30 min
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The pair now exists on ROCm for `proverb` and `ledger` (27B 23.2 s and 59.3 s against Strata's 74.1 s and 144.0 s, Pi client). The Vulkan arm runs the `vulkan-1.0.0` pin, which is clean on this run (36.3 s, 371 tok/s prefill, 32.8 decode) but slower than ROCm, so repeat it there only if the pin is the build worth reporting; the rolling build is not installed. Turn-budget cleanup stays unverified. [Results](../scripts/tests/notes/OUTCOMES.md). ~1 h

- [ ] Take the Loom device failure upstream once it is confirmed, then retry the comparison: it now reproduces on the installed release - `loom-serve --device=amdgpu`, `rdna`, `rdna://1` and `amdgpu://1` all exit 1 with `NOT_FOUND; no AMD endpoint matches the selected family and path` (`runtime/src/iree/hal/driver/amd/driver.c:843`) whatever `HIP_VISIBLE_DEVICES` or `ROCR_VISIBLE_DEVICES` say, while `amdf-info --device=rdna --activate` reports `Activation: OK` on `rdna://0`, the integrated adapter, and `--format=json` lists the RX 7800 XT as `gfx1102`, ordinal 1. `--device=task` starts and registers `Qwen/Qwen2.5-0.5B-Instruct`, but a chat request was still 503 after four minutes. Next: let the CPU path finish to prove the package and the server, then try an explicit device document, and only then write the upstream question; the console scripts need `PYTHONPATH` pointing at `frameworks/loom/sdk`, since their shims load the `loom` package from beside them, and `loom-fetch` writes its hub cache into `data/huggingface/models` unless `--cache` names `data/huggingface/hub`, which the layout check reads as an unregistered model root. The symptom is recorded in [upstream](../notes/UPSTREAM-INDEX.md). Baseline for the same GGUF on llama.cpp Vulkan 1.0.0-dev (12422, a681a53b6): 472 tok/s median over five 128-token runs. ~2 h
