# TTS Test Spawning

- Run slow TTS tests (Qwen3-TTS, Chatterbox, Sesame CSM) in a visible console that stays open after completion.
- Run quick tests (Kokoro, Edge TTS) inline.
- Wait for the user before starting another slow model test.
- Use launch_util.launch_module(..., mode=cfg.ConsoleTerminalLaunchMode.SPLIT_INDEPENDENT) for the visible console lifecycle. Follow [package execution](CODE.md#execution).
