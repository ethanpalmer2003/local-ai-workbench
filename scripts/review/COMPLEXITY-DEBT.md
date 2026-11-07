# McCabe debt

Functions above the gate of 10. Each carries `# noqa: C901`; delete the annotation when the function is split.
Regenerate with `python -m scripts.review.inventory_code --complexity-debt` rather than editing by hand.

| Complexity | Function |
| ---: | --- |
| 22 | `scripts/benchmarks/coding_agents/shared/benchmark_requests.py:232` `handler` |
| 16 | `scripts/tests/cases/audiocpp/audiocpp_backend_compare.py:306` `main` |
| 16 | `scripts/tests/cases/audiocpp/audiocpp_streaming.py:140` `run_comparison` |
| 15 | `scripts/review/structure_docs.py:64` `configuration_issues` |
| 15 | `scripts/tests/cases/shared/live_frameworks.py:301` `running_framework` |
| 14 | `scripts/benchmarks/koboldcpp/kobold_stack_vram.py:249` `run` |
| 14 | `scripts/config/comfyui/workflow_overrides.py:191` `apply` |
| 14 | `scripts/launchers/llamacpp/llamacpp_dsh.py:220` `main` |
| 14 | `scripts/review/model_references.py:16` `inspect` |
| 14 | `scripts/tests/cases/asr/shared/language_practice_whisper.py:38` `main` |
| 13 | `scripts/benchmarks/koboldcpp/kobold_stack_vram.py:45` `generate` |
| 13 | `scripts/benchmarks/personal/comfyui/comfyui_video.py:668` `_resolve_arguments` |
| 13 | `scripts/config/comfyui/workflow_overrides.py:275` `workflow` |
| 13 | `scripts/download/input/get_tts_voices.py:1149` `validate_character` |
| 13 | `scripts/download/input/get_tts_voices.py:1320` `main` |
| 13 | `scripts/download/models/metadata_evidence.py:18` `measurements` |
| 13 | `scripts/launchers/koboldcpp/kobold.py:38` `server_command` |
| 12 | `scripts/benchmarks/asr/asr_resident_compare.py:94` `run_engine` |
| 12 | `scripts/benchmarks/asr/audiocpp_drama3_offload.py:255` `serve` |
| 12 | `scripts/benchmarks/asr/audiocpp_drama3_offload.py:44` `weight_estimates` |
| 12 | `scripts/benchmarks/coding_agents/shared/benchmark_requests.py:250` `do_POST` |
| 12 | `scripts/download/models/download_catalog.py:48` `main` |
| 12 | `scripts/launchers/asr/parakeetcpp/transcribe.py:13` `main` |
| 12 | `scripts/launchers/asr/shared/live.py:58` `request` |
| 12 | `scripts/launchers/llamacpp/llamacpp_coding.py:15` `prepare_pi_env` |
| 12 | `scripts/review/structure_docs.py:147` `owner_issues` |
| 11 | `scripts/benchmarks/asr/asr_resident_compare.py:170` `main` |
| 11 | `scripts/benchmarks/llamacpp/benchmark_context_stream.py:66` `stream_request` |
| 11 | `scripts/benchmarks/personal/comfyui/comfyui_video.py:199` `_consume_events` |
| 11 | `scripts/config/comfyui/workflow_overrides.py:16` `text_nodes` |
| 11 | `scripts/config/sync_configs.py:65` `sync_comfyui` |
| 11 | `scripts/download/models/analyze_model.py:98` `enrich_hub` |
| 11 | `scripts/download/models/hub_transfer.py:11` `download_ranges` |
| 11 | `scripts/launchers/asr/shared/file_cli.py:20` `build_command` |
| 11 | `scripts/launchers/asr/shared/file_cli.py:61` `main` |
| 11 | `scripts/launchers/asr/shared/turns.py:91` `poll` |
| 11 | `scripts/launchers/audiocpp/asr.py:66` `transcribe` |
| 11 | `scripts/launchers/runtime/gpu_memory.py:452` `_get_process_vram` |
| 11 | `scripts/review/public_audit.py:89` `scan_text` |
| 11 | `scripts/review/structure_docs.py:246` `naming_issues` |
| 11 | `scripts/tests/cases/asr/shared/latency.py:58` `replay` |
| 11 | `scripts/tests/cases/koboldcpp/kobold_image_swap.py:144` `run` |
| 11 | `scripts/tests/cases/llamacpp/hrx/hrx_update_validation.py:131` `verify_candidate_evidence` |
| 11 | `scripts/tools/rewrite_imports.py:88` `rewrite_file` |

Remaining: 44.
