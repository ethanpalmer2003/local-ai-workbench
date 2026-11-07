# Conversation deployment and concurrency

Target: Gemma E4B chat in llama.cpp or Kobold, selected ASR, AudioCpp TTS.
Preferred architecture: one AudioCpp server for Nemotron ASR + Kokoro TTS.
[Alternating/concurrent/paced checks pass](../../tests/notes/audiocpp/AUDIOCPP-SINGLE-SERVER.md);
Practice gateways integrate Gemma; acoustic interruption remains pending.
AudioCpp is the TTS choice; framework comparisons are closed. A loaded model
consumes memory even when idle. Loaded together, serving together and computing
in parallel are different capabilities.

## Five arrangements, two chat runtimes

Each arrangement can pair with llama.cpp or Kobold chat: **10 deployment layouts**.
These combinations are not ten validated presets.

| Arrangement | Concrete example | What needs checking |
| --- | --- | --- |
| One AudioCpp server, ASR + TTS | Nemotron and Kokoro under distinct IDs | Residency/routing and overlapping clients pass; add Gemma and real playback |
| Two AudioCpp servers | ASR on one port; TTS on another | Process isolation versus added memory/workspaces; shared GPU contention |
| Dedicated non-llama ASR + AudioCpp TTS | speech.cpp/Qwen 0.6B; Gemma chat separately | Independent ASR/TTS scheduling, VAD finalization and combined memory |
| Separate llama.cpp ASR + AudioCpp TTS | Qwen 1.7B ASR server plus Gemma chat server | Separate weights/KV/workspaces, compatible session ownership and GPU contention |
| Shared Gemma audio/chat + AudioCpp TTS | One Gemma model handles transcription and replies | Shared weights/projector, request serialization, audio context and chat isolation |

One process or separate ports do not guarantee parallel GPU execution. Each model
needs memory/workspaces; exclude lazy loading from resident timing.

Our Gemma audio llama.cpp command uses `-np 1`: a shared chat/audio instance has
one configured slot. Requests may queue; more slots require an explicit settings
comparison and additional context memory. Separate llama.cpp models use separate
servers in our setup. Kobold shared-model request scheduling also needs measurement;
sharing Gemma weights does not prove simultaneous recognition/generation.

Practice defaults to one AudioCpp Nemotron/Kokoro server. NeMo/Parakeet CPU stream; Qwen, Whisper and
Parakeet v3 decode Silero segments with separate Kokoro servers; Gemma/Qwen
1.7B use manual turns. Recognition pauses during tutor replies.

Workload scenarios, the layout matrix and the measurement contract: [MULTIUSE-SCENARIOS.md](MULTIUSE-SCENARIOS.md).
