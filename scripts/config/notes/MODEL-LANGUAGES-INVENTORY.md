# Model language inventory

Query, inspection and native discovery procedures for the speech model→language
catalog in [MODEL-LANGUAGES](MODEL-LANGUAGES.md).

## Offline query

```powershell
C:/AI/bat/models/report_model_languages.bat
C:/AI/bat/models/report_model_languages.bat --task tts --details
C:/AI/bat/models/report_model_languages.bat --task asr --language French
C:/AI/bat/models/report_model_languages.bat --model nemotron --details
C:/AI/bat/models/report_model_languages.bat --json
```

`--model` also accepts canonical download IDs. `--details` prints complete names,
codes, locale/dialect lists, sources and local frontend limits. The command uses
no network, inference, model loading or native backend. Unknown Gemma coverage is
omitted from language-filter matches rather than assumed supported.

## Native discovery

No universal `--languages` flag exists. Verified installed commands:

- AudioCpp: `audiocpp_cli.exe --model PATH --inspect` prints `languages=...`.
- speech.cpp: `speech.exe info PATH --json` includes `languages` without loading weights.
- NeMo: `nemo-speech.exe model info PATH`; Parakeet: `parakeet-cli.exe info PATH`. Their metadata is not guaranteed to enumerate languages.
- Whisper's `--language CODE` selects recognition language; it does not list per-checkpoint coverage.
- Piper voice `.onnx.json` supplies its locale; Sherpa coverage depends on the selected checkpoint/frontend.

When adding/updating speech checkpoints, review this catalog against primary cards,
tokenizer maps and installed metadata. HF language tags alone can be incomplete.
