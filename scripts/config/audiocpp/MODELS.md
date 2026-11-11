# Audio models

Model files live under `data/huggingface/models/audiocpp/`; the installed AudioCpp build
registers every family listed in [server.json](server.json). Ids, download sizes and output
modes are owned by the [model catalog](../models/catalog.json), and `server.json` loads the
same entries.

| Family | Use |
| --- | --- |
| `supertonic` | Practice default. 31 languages, preset voices `M1`-`M5`/`F1`-`F5`, no cloning, streaming. One self-contained GGUF. |
| `breeze_tts` | Voice cloning plus instruction-driven design; streaming. |
| `ming3_tts`, `ming3_audio` | Named voices such as `US_James`; the heavier checkpoint is Complete WAV only. |
| `fish_drama3` | Heavy, CPU-expert offload; streaming. |

Supertonic, Ming and Drama play at 44100 Hz. Lemonade serves only its own `kokoro-v1`
speech entry, so Supertonic stays on AudioCpp and KoboldCpp.

Supertonic voices: `M1`, `M2`, `M3`, `M4`, `M5`, `F1`, `F2`, `F3`, `F4`, `F5`. `F1` is
the practice default; change `SUPERTONIC_TTS.voice` and the `default_request_options`
voice in [server.json](server.json) together, then restart the speech server.

KoboldCpp 1.124.2 serves the same GGUF natively through `--ttsmodel`; it ports a subset of
the audio.cpp families, so files are interchangeable and options are not. Its speech
endpoint reads the top-level `voice` and ignores `options.voice_id`, while AudioCpp accepts
either. The launcher therefore sends `voice` to native KoboldCpp and `options.voice_id`
through the AudioCpp proxy, which strips `voice` for preset-voice models.

## Test page

- Start `bat/browser/launch_test.bat`; the TTS model selector lists the configured families.
- Existing character voices use reference cloning.
- Streaming and Complete WAV are both available except where a family rejects streaming.
- Instruction maps to the native field each family takes (`instruction` or `instruct`).
- Models load lazily; selecting a dropdown does not synthesize speech.

## Brief checks

```powershell
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case ming3-tts
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case ming3-audio --loaders-only
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case ming3-audio --backend vulkan
```

- Omit `--backend` to check both official builds sequentially. Default: one short warmup and one
  measured request. `--text`, `--samples`, `--timeout` are available.
- Generated smoke configs contain only the selected model. Existing services on test ports are
  preserved or refused.
- A single sentence is a compatibility screen, not a quality or ranking benchmark.
- Supertonic synthesized English, French and Japanese on the Vulkan backend in a one-request
  check. Its first timing pair against Kokoro is recorded in
  [the TTS screen](../../tests/notes/SUPERTONIC-TTS-SCREEN.md): RTF 0.027 against 0.033, 481 MiB
  against 694 MiB peak process VRAM.

Editable native model and session options: [server.json](server.json). Model guides:
[TTS](https://github.com/0xShug0/audio.cpp/blob/v0.9.4/docs/models/ming3_tts.md),
[heavier](https://github.com/0xShug0/audio.cpp/blob/v0.9.4/docs/models/ming3_audio.md).
Pinned download identities stay in the [model catalog](../models/catalog.json); bulk restore
remains opt-in.
