# McCabe debt

Functions above the gate of 10. Each carries `# noqa: C901`; delete the annotation when the function is split.
Regenerate with `python -m scripts.review.inventory_code --complexity-debt` rather than editing by hand.

| Complexity | Function |
| ---: | --- |
| 12 | `scripts/benchmarks/asr/asr_resident_compare.py:94` `run_engine` |
| 12 | `scripts/benchmarks/asr/audiocpp_drama3_offload.py:255` `serve` |
| 12 | `scripts/benchmarks/asr/audiocpp_drama3_offload.py:44` `weight_estimates` |
| 12 | `scripts/download/models/download_catalog.py:48` `main` |
| 12 | `scripts/launchers/asr/parakeetcpp/transcribe.py:13` `main` |
| 12 | `scripts/launchers/asr/shared/live.py:58` `request` |
| 12 | `scripts/launchers/llamacpp/llamacpp_coding.py:15` `prepare_pi_env` |
| 12 | `scripts/review/structure_docs.py:177` `owner_issues` |
| 11 | `scripts/benchmarks/asr/asr_resident_compare.py:170` `main` |
| 11 | `scripts/benchmarks/llamacpp/benchmark_context_stream.py:66` `stream_request` |
| 11 | `scripts/config/sync_configs.py:65` `sync_comfyui` |
| 11 | `scripts/download/models/analyze_model.py:98` `enrich_hub` |
| 11 | `scripts/download/models/hub_transfer.py:11` `download_ranges` |
| 11 | `scripts/launchers/asr/shared/file_cli.py:20` `build_command` |
| 11 | `scripts/launchers/asr/shared/file_cli.py:61` `main` |
| 11 | `scripts/launchers/asr/shared/turns.py:91` `poll` |
| 11 | `scripts/launchers/audiocpp/asr.py:66` `transcribe` |
| 11 | `scripts/launchers/runtime/gpu_memory.py:452` `_get_process_vram` |
| 11 | `scripts/review/public_audit.py:89` `scan_text` |
| 11 | `scripts/review/structure_docs.py:276` `naming_issues` |
| 11 | `scripts/tests/cases/asr/shared/latency.py:58` `replay` |
| 11 | `scripts/tests/cases/koboldcpp/kobold_image_swap.py:144` `run` |
| 11 | `scripts/tests/cases/llamacpp/hrx/hrx_update_validation.py:131` `verify_candidate_evidence` |
| 11 | `scripts/tools/rewrite_imports.py:88` `rewrite_file` |

Remaining: 24.
