# Automatic ASR turns

Nemotron streaming ASR and Kokoro TTS share one Vulkan AudioCpp server. A small
AudioCpp CLI helper runs native Silero on CPU. The installed HTTP API has no
stateful live VAD session, so this uses **one server plus one VAD helper process**.
It does not silently start a second ASR/TTS server or rebuild AudioCpp.

## Settings and model

`launcher_config.AUDIOCPP_VAD` owns threshold **0.5**, silence **700 ms**, pre-roll
**300 ms**, server port **8894**, 16 kHz mono PCM16/512-sample frames and a
30-second turn limit. Native Silero's default negative-threshold hysteresis applies.
Streaming thresholds/silence are **session options**, not request options in this
release. Pre-roll is buffered by the controller; native speech padding is zero.

The pinned, SHA-256-verified 1.24 MB safetensors asset lives under
`models/audiocpp/silero-vad/`; download ID `audiocpp/silero-vad` in the canonical
catalog. Other frameworks' Silero GGUFs are not interchangeable.

## Use

```powershell
C:/AI/bat/browser/launch_test_asr.bat
```

In the page, enable **Recognize speech**, then either use the microphone or
choose **Replay WAV (turns)** to stream a saved file through the same live
session. The replay runs at speaking speed, adds two seconds of silence after
EOF so the VAD closes the turn, and writes the result into the transcript.
**Upload WAV** remains the one-shot transcription path. The gateway reuses a
matching healthy server, refuses mismatched occupied ports, and stops only
processes it owns. Normal context/permission rules apply.

Streaming engines, page integration and the gateway session API are detailed in
[ASR-VAD-STREAMING-INTEGRATION.md](ASR-VAD-STREAMING-INTEGRATION.md).

## Verified scope

[Brief checks](../../tests/notes/audiocpp/AUDIOCPP-VAD.md) pass silence rejection, a complete
utterance while Kokoro runs, and a 350 ms internal pause retained as one turn.
Final text arrived about 0.86 seconds after Silero's speech-end estimate.

The page and both gateways connect automatic turns to Gemma and Kokoro.
[Saved-PCM checks on both chat runtimes](../../tests/notes/PRACTICE-INTEGRATION.md)
and simulated browser contracts pass. They are separate from physical
microphone/playback, acoustic echo cancellation, interruption, learner accents
and multilingual quality checks, which remain unverified.
