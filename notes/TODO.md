# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration, shortest first.

## Reliability

- [ ] Rewrite the no-model provider seed, which external-LLM mode needs: KoboldCpp then runs without a model, so the page has to be pointed at llama-server or generation fails until someone picks the custom provider by hand. `external_script` writes `kaihordewebui_*` localStorage keys while Lite reads one `settings` record from the IndexedDB database `e_kaihordewebui_`, so seed that record once instead. The patch needs the live page: save one with `kobold_lite --export-html` during the next session and reuse it through `--source-file`. ~30 min

## Standardization

- [ ] Move the remaining `urllib.request` callers to `requests`, which the [code rules](../.agents/CODE.md) name as the client: 26 files, of which 18 are tests holding `urllib` patches. The code left is `launchers/audiocpp/tts_proxy.py`, `launchers/koboldcpp/{external_bridge,kobold_lite}.py`, `launchers/lemonade_server/lemonade.py`, `launchers/llamacpp/llamacpp_dsh.py`, `launchers/proxy_util.py`, `launchers/runtime/image_on_demand.py`, `shared/{http_server,service_identity}.py`. Convert a code file with the tests that patch it, so the suite stays green per commit. ~2-3 h
- [ ] Decide the retired TTS pipeline in `scripts/launchers/audiocpp/tts_legacy_buffered.py`: nothing imports it, its own docstring calls it retired, and the active path is `tts_text_processing.py`. Delete it, or name the usefulness it still has; either way drop the `RETIRED` entry in `scripts/review/unused.py` with it. ~20 min
- [ ] Revisit the three declined library swaps in [review libraries](../scripts/review/LIBRARIES.md) once `unused.py` has a few weeks of findings: vulture for unused code, eradicate for the commented-out rule, a Markdown parser for links. Each trades a dependency for local code, so the decision needs the false-positive record first. ~1 h
- [ ] Try vale with the styles that fit this voice: `Voices` (hedging and puffery core, Direct and Simple voices), `AiTells` (the tells of generated prose) and `Readability`. Proselint and write-good alone measured nothing worth gating. Vale is one binary with no fix mode, so the work is a `.vale.ini` that selects rules and disables quote and ellipsis checks. ~1-2 h
- [ ] Re-run both similarity modes: documents last ran 2026-11-10 22:15 and code 21:56, since when the review pages, this TODO and several guides changed. The pair count in [resolved questions](OPEN-QUESTIONS-RESOLVED.md) carries that date for that reason. Needs the embedding model, so it is a live run. `check_document_similarity.bat` and `check_code_similarity.bat`. ~15 min

## Needs a model run or device

### Requires user input

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/benchmarks/asr/coverage.py). ~45-60 min

### Unattended

- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md). ~1.5-2 h
