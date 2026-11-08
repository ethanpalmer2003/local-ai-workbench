# Batch entry points

Coding-agent entry points stay at the root. Browser, model, test, and benchmark batches are grouped by role; each launcher passes `%*` through to its Python module. Browser names state which HTML they open first: `launch_test*` is the shared `/test/` page, `launch_language*` is the shared `/practice` page, `launch_kobold*` is the KoboldCpp chat stack, and `launch_sdcpp` / `launch_comfyui` are each framework's own built-in UI.

## Root

| Batch | Purpose |
| --- | --- |
| [update_frameworks.bat](update_frameworks.bat) | Check/apply framework updates (`--check-only`, `--only KEY`, `--category`). |
| [manage_kill_ai_services.bat](manage_kill_ai_services.bat) | Stop C:\AI-owned listeners; `--non-agents` keeps coding agents, llama.cpp and Strata running. |
| [launch_llamacpp_pi_agent.bat](launch_llamacpp_pi_agent.bat) | llama.cpp coding agent, default Pi; `--client little-coder`, `ohmypi`, `nanocoder`, or `none`. |
| [launch_strata_pi_agent.bat](launch_strata_pi_agent.bat) | Strata coding agent with Pi. |

## Browser launchers

| Batch | HTML opened |
| --- | --- |
| [launch_test.bat](browser/launch_test.bat) | Shared `/test/` page, every stage on demand. |
| [launch_test_asr.bat](browser/launch_test_asr.bat) | Shared `/test/` page, ASR only. |
| [launch_test_llm.bat](browser/launch_test_llm.bat) | Shared `/test/` page, LLM only. |
| [launch_language.bat](browser/launch_language.bat) | Shared `/practice` page on the llama.cpp stack. |
| [launch_language_kobold.bat](browser/launch_language_kobold.bat) | Shared `/practice` page on the KoboldCpp stack. |
| [launch_language_kobold_no_model.bat](browser/launch_language_kobold_no_model.bat) | Same page: llama.cpp serves, KoboldCpp is UI only. |
| [launch_kobold.bat](browser/launch_kobold.bat) | KoboldCpp's own browser UI on its own model, plus AudioCpp/image proxies. |
| [launch_kobold_no_model.bat](browser/launch_kobold_no_model.bat) | Same stack on llama.cpp: Lite proxy and TTS chain, no local model. |
| [launch_sdcpp.bat](browser/launch_sdcpp.bat) | sd.cpp's own image-generation UI at `/`. |
| [launch_comfyui.bat](browser/comfyui/launch_comfyui.bat) | ComfyUI's own UI with default attention/VRAM settings. |
| [comfyui_bootstrap.bat](browser/comfyui/comfyui_bootstrap.bat) | Shared ComfyUI bootstrap (not a UI launcher). |

## Models

| Batch | Purpose |
| --- | --- |
| [download_models.bat](models/download_models.bat) | Download/verify catalog models. |
| [check_installed_models.bat](models/check_installed_models.bat) | Audit installed files against the catalog. |
| [analyze_model_metadata.bat](models/analyze_model_metadata.bat) | Inspect model metadata into inventory. |
| [report_model_languages.bat](models/report_model_languages.bat) | Offline language-coverage inventory. |

## Tests

| Batch | Purpose |
| --- | --- |
| [test_model_free.bat](tests/test_model_free.bat) | Model-free regression suite; no VRAM, no models, no port kills. |
| [test_live_launchers.bat](tests/test_live_launchers.bat) | Live launcher/proxy wiring: starts each launcher, generates output, stops owned. |
| [test_live_backends.bat](tests/test_live_backends.bat) | Live backend probes: every model loads and answers; `--only` narrows it. |
| [test_live_all.bat](tests/test_live_all.bat) | Both native suites: launchers first, then every backend probe. |

Live entries free their ports instead of refusing.

## Review

- Formatting wrapper: [scripts/review/format_py.bat](../scripts/review/format_py.bat).
- Repository review: [scripts/review/check_repo.bat](../scripts/review/check_repo.bat).

## Benchmarks

| Batch | Purpose |
| --- | --- |
| [benchmark_asr_compare.bat](benchmarks/benchmark_asr_compare.bat) | ASR resident comparison. |
| [benchmark_tts_speed.bat](benchmarks/benchmark_tts_speed.bat) | Piper/Sherpa TTS speed screen. |
| [benchmark_coding_agents.bat](benchmarks/benchmark_coding_agents.bat) | Coding-agent comparisons; defaults to one task, one repeat. |
| [benchmark_strata_avalon.bat](benchmarks/benchmark_strata_avalon.bat) | Strata vs Avalon, same weights: prefill, decode, TTFT. |
| [benchmark_framework_compare.bat](benchmarks/benchmark_framework_compare.bat) | Practice stack vs Lemonade on the language profile: chat, Kokoro speech, recognition WER/CER. |

Routine LLM check: `benchmark_strata_avalon.bat` (engine speed) then `benchmark_coding_agents.bat` (agent completion).

Benchmark implementations and new benchmark results live in `scripts/benchmarks/`.
