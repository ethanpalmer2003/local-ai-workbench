# llama-ui with workspace speech

- Launch `bat/browser/launch_language.bat --ui llama`, or open `http://127.0.0.1:5003/llama-ui`. The gateway must run; `/practice` and `/test/` remain available.
- Mic and Send remain separate; Stop appears during generation/playback. The native microphone button runs the selected external ASR, including streaming/VAD where supported. Native editor bindings accept transcripts in plain or rich mode. A typed draft is preserved for review; empty drafts submit automatically. Recorded-turn models transcribe when recording stops, with a 30-second limit.
- Assistant replies use the selected TTS automatically. Native Stop cancels generation, capture and playback. There is no floating speech panel. Audio attachments still follow native multimodal behavior.
- The sidebar Workspace settings icon opens `/test/` in a native side drawer. It reuses the full test page, hiding only its duplicate header. Opening stops native capture/playback; closing refreshes speech profiles and saved language.
- Language follows shared saved preferences, defaulting to French. Set model/language choices on `/test/` before opening native UI. Its conversation/system prompt remains independent; language selection controls recognition and pronunciation.
- Opening native UI loads the selected chat model; ASR/TTS remain lazy. One live microphone session per gateway. Capture is silenced during generation/playback. Resumed historical streams, reasoning and tool preambles are not spoken.
- The gateway serves the locally rebuilt frontend from `frameworks/llamacpp/additions/speech-ui`. Native backend binaries are unchanged. Shared transport: [speech_client.js](../shared/browser/speech_client.js); bridge: [speech_ui.js](speech_ui.js); serving: [speech_ui.py](speech_ui.py). PWA workers cannot take over the shared origin.

- Patch and rebuild steps: [llama.cpp UI patch guide](patches/README.md).

## Validation

`python -m unittest scripts.tests.cases.llamacpp.test_speech_ui scripts.tests.cases.asr.shared.test_practice` covers shared transport and native bridge contracts without devices/models. Native `npm run check` and build validate the Svelte bindings. Live microphone/inference checks remain opt-in.
