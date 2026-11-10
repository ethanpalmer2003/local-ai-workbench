# ASR checkpoint

Current implementation summary; [test status](../../scripts/tests/notes/STATUS.md) owns validation evidence.

## Implemented

- Common ASR API/upload parsing and practice UI; AudioCpp Nemotron/Silero is default.
- Framework adapters in `launchers/asr/{whispercpp,llamacpp,koboldcpp,parakeetcpp,handy}`; shared request/HTTP helpers under `asr/shared`.
- Both chat consumers offer automatic turns with AudioCpp/NeMo Vulkan Nemotron, Parakeet CPU Nemotron, speech.cpp Qwen 0.6B, Whisper turbo and Parakeet v3; manual Gemma/Qwen 1.7B alternatives remain available. Gemma can share one chat/audio model per runtime; separate Gemma-ASR plus Kobold chat loads two instances.
- Gemma audio: strict prompted transcription on prepared audio; its format limits are owned by [the launcher limits](../../scripts/launchers/asr/README-LANGUAGES-API-LIMITS.md).
- Parakeet file CLI plus CPU/Vulkan release updater; Handy portable app/model link; v3 resident gateway uses the shared Silero controller.
- Canonical model/install/test paths and concise docs guard follow the [structure contract](../reviews/STRUCTURE-REVIEW.md). Shared corpus/metrics are independent of backend probes.

Pending evaluation work is owned by the [TODO](../TODO.md); selection rationale and
known model limits are in the [ASR evaluation](ASR-EVALUATION.md). [Commands/options](../../scripts/launchers/asr/README.md)
and [test layout](../../scripts/tests/cases/asr/README.md) remain the procedure references.
