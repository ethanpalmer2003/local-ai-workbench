# McCabe debt

Functions above the gate of 10. Each carries `# noqa: C901`; delete the annotation when the function is split.
Regenerate with `python -m scripts.review.inventory_code --complexity-debt` rather than editing by hand.

| Complexity | Function |
| ---: | --- |
| 11 | `scripts/benchmarks/llamacpp/benchmark_context_stream.py:66` `stream_request` |
| 11 | `scripts/config/sync_configs.py:65` `sync_comfyui` |
| 11 | `scripts/launchers/runtime/gpu_memory.py:452` `_get_process_vram` |
| 11 | `scripts/tests/cases/asr/shared/latency.py:58` `replay` |
| 11 | `scripts/tests/cases/koboldcpp/kobold_image_swap.py:144` `run` |
| 11 | `scripts/tests/cases/llamacpp/hrx/hrx_update_validation.py:131` `verify_candidate_evidence` |
| 11 | `scripts/tools/rewrite_imports.py:88` `rewrite_file` |

Remaining: 7.
